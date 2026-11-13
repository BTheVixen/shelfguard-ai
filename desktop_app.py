import asyncio
import csv
import io
import json
import os
import re
import shutil
import subprocess
import webbrowser
import threading
import time
import urllib.request
import traceback
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from tetherto.qvac_sdk import Client, completion, load_model, unload_model
from tetherto.qvac_sdk.models import LLAMA_3_2_1B_INST_Q4_0

from database import PLANS, init_database, seed_sample_stock
import tools

qvac_state = {"client": None, "transport": None, "model_id": None}


def open_desktop_window(url: str) -> None:
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for browser_path in candidates:
        if browser_path and os.path.exists(browser_path):
            subprocess.Popen([browser_path, f"--app={url}", "--window-size=1280,840"])
            return
    webbrowser.open(url)


async def ask_qvac_text(system_prompt: str, user_prompt: str) -> str:
    t = qvac_state["transport"]
    model_id = qvac_state["model_id"]
    run = completion(
        t,
        model_id=model_id,
        history=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    chunks = []
    async for event in run.events:
        if event.type == "contentDelta":
            chunks.append(event.text)
    return "".join(chunks).strip()


async def realtime_watchdog():
    """Background loop that scans expiry thresholds every 15 seconds when Growth/Business is active."""
    last_snapshot = None
    while True:
        await asyncio.sleep(15)
        try:
            plan = tools.get_active_plan()
            if plan.get("realtime_tracker"):
                telemetry = tools.get_realtime_telemetry()
                snapshot = (
                    telemetry["blocked_batches"],
                    telemetry["warning_batches"],
                    telemetry["at_risk_zar"],
                )
                if snapshot != last_snapshot:
                    tools.log_agent_decision(
                        "Real-Time Watchdog",
                        f"Live scan: {telemetry['blocked_batches']} blocked, "
                        f"{telemetry['warning_batches']} in 10-day warning | R{telemetry['at_risk_zar']:.2f} at risk.",
                    )
                    last_snapshot = snapshot
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    seed_sample_stock()
    client = Client()
    await client.connect()
    t = client.transport
    model_id = await load_model(t, model_src=LLAMA_3_2_1B_INST_Q4_0)
    qvac_state["client"] = client
    qvac_state["transport"] = t
    qvac_state["model_id"] = model_id

    watchdog_task = asyncio.create_task(realtime_watchdog())
    open_desktop_window("http://127.0.0.1:8000")
    open_desktop_window("http://127.0.0.1:8000")
    yield

    watchdog_task.cancel()
    try:
        await unload_model(t, model_id)
        await client.close()
    except Exception:
        pass


app = FastAPI(title="ShelfGuard AI Desktop", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(open("ui.html",encoding="utf-8").read())
@app.get("/api/state")
async def api_state():
    return {
        "plan": tools.get_active_plan(),
        "plans": PLANS,
        "batches": tools.get_all_batches(),
        "warnings": tools.scan_expiring_stock(warning_days=10),
        "telemetry": tools.get_realtime_telemetry(),
    }


@app.post("/api/plan")
async def api_change_plan(plan_code: str = Form(...)):
    updated = tools.set_active_plan(plan_code)
    return JSONResponse(updated)


@app.post("/api/pick")
async def api_pick_order(sku: str = Form(...), quantity: int = Form(...)):
    try:
        result = tools.evaluate_online_order(
            sku=sku.strip().upper(), requested_qty=quantity, auto_deduct=True
        )
        ai_note = await ask_qvac_text(
            system_prompt="You are ShelfGuard Fulfillment Guard. Give a concise 2-sentence picking instruction for warehouse staff.",
            user_prompt=f"Order check result:\n{json.dumps(result, indent=2)}",
        )
        tools.log_agent_decision("Fulfillment Guard", ai_note)
        return {"result": result, "ai_instruction": ai_note}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/api/upload-csv")
async def api_upload_csv(file: UploadFile = File(...)):
    try:
        plan = tools.get_active_plan()
        if not plan["csv_ai_enabled"]:
            return JSONResponse(
                status_code=403,
                content={
                    "error": f"Locked on {plan['name']} (R{plan['price_zar']}/mo). Switch to Growth (R499) or Business (R999) in the top right to unlock AI CSV Extraction."
                },
            )

        raw_bytes = await file.read()
        raw_csv = raw_bytes.decode("utf-8", errors="ignore").strip()
        reader = csv.DictReader(io.StringIO(raw_csv))
        rows = list(reader)
        if not rows or not reader.fieldnames:
            return JSONResponse(
                status_code=400, content={"error": "CSV file is empty or missing headers."}
            )

        sample_preview = json.dumps(
            {"headers": reader.fieldnames, "sample_row": rows[0]}, indent=2
        )
        system_prompt = (
            "You are a schema-mapping AI. Map the supplier CSV headers to our exact database keys: "
            "batch_id, sku, name, category, price_zar, quantity, expiry_date. "
            "Return ONLY a JSON object mapping each target key to the exact supplier header name."
        )
        raw_ai = await ask_qvac_text(
            system_prompt, f"Map these CSV headers:\n{sample_preview}"
        )
        match = re.search(r"\{.*\}", raw_ai, re.DOTALL)
        if not match:
            return JSONResponse(
                status_code=400,
                content={"error": "AI could not map CSV headers.", "raw": raw_ai},
            )

        raw_map = json.loads(match.group(0))
        # Normalize even if 1B model flips key/value direction
        col_map = {}
        for k, v in raw_map.items():
            kl, vl = str(k).lower(), str(v).lower()
            if k in reader.fieldnames:
                col_map[vl] = k
            elif v in reader.fieldnames:
                col_map[kl] = v
        # Deterministic synonym fallback so small models never fail on key names
        for h in reader.fieldnames:
            hl = h.lower()
            if "batch" in hl or "lot" in hl: col_map.setdefault("batch_id", h)
            elif "sku" in hl or "item_code" in hl or "product_sku" in hl: col_map.setdefault("sku", h)
            elif "name" in hl or "desc" in hl or "title" in hl: col_map.setdefault("name", h)
            elif "cat" in hl or "dept" in hl or "group" in hl: col_map.setdefault("category", h)
            elif "price" in hl or "rand" in hl or "zar" in hl or "cost" in hl: col_map.setdefault("price_zar", h)
            elif "qty" in hl or "quant" in hl or "pack" in hl: col_map.setdefault("quantity", h)
            elif "exp" in hl or "best" in hl or "date" in hl: col_map.setdefault("expiry_date", h)
        imported = []
        for row in rows:
            raw_price = (
                str(row[col_map["price_zar"]]).replace("R", "").replace(",", "").strip()
            )
            res = tools.upsert_extracted_batch(
                sku=str(row[col_map["sku"]]),
                name=str(row[col_map["name"]]),
                category=str(row.get(col_map.get("category", ""), "General")),
                price_zar=float(raw_price),
                batch_id=str(row[col_map["batch_id"]]),
                quantity=int(float(str(row[col_map["quantity"]]).strip())),
                expiry_date=str(row[col_map["expiry_date"]]).strip(),
            )
            imported.append(res)

        tools.log_agent_decision(
            "CSV Extraction Agent",
            f"Mapped headers and imported {len(imported)} rows from {file.filename}",
        )
        return {"imported": imported, "mapped_headers": col_map}
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": f"CSV import failed: {exc}"})


@app.post("/api/promo-report")
async def api_promo_report():
    try:
        plan = tools.get_active_plan()
        warnings = tools.scan_expiring_stock(warning_days=10)
        if not plan["promo_ai_enabled"]:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "AI Promo Advisor is locked on Starter (R299/mo). Switch to Growth (R499) or Business (R999) in the top right.",
                    "basic_warnings": warnings,
                },
            )

        report = await ask_qvac_text(
            system_prompt=(
                "You are ShelfGuard Promo Advisor for a South African online grocery & retail warehouse. "
                "Use ZAR (R) currency. Summarize total Rand value at risk and give short, actionable markdown promos."
            ),
            user_prompt=f"Flagged batches within 10 days of expiry:\n{json.dumps(warnings, indent=2)}",
        )
        tools.log_agent_decision("Promo Advisor", report)
        return {"report": report, "warnings": warnings}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
