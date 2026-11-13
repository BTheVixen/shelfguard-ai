import asyncio
import json
import os
import re
import sys

from tetherto.qvac_sdk import Client, completion, load_model, unload_model
from tetherto.qvac_sdk.models import LLAMA_3_2_1B_INST_Q4_0

from database import PLANS, init_database, seed_sample_stock
from tools import (
    evaluate_online_order,
    get_active_plan,
    get_all_batches,
    log_agent_decision,
    scan_expiring_stock,
    set_active_plan,
    upsert_extracted_batch,
)

def print_progress(p) -> None:
    line = (
        f"Downloading {p.percentage:.0f}% "
        f"({p.downloaded / 1e6:.1f}/{p.total / 1e6:.1f} MB)"
    )
    print(line, end="\r" if sys.stderr.isatty() else "\n", file=sys.stderr)
    if p.percentage >= 100:
        print(file=sys.stderr)

async def ask_qvac(transport, model_id: str, system_prompt: str, user_prompt: str, stream: bool = True) -> str:
    run = completion(
        transport,
        model_id=model_id,
        history=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    chunks = []
    async for event in run.events:
        if event.type == "contentDelta":
            if stream:
                sys.stdout.write(event.text)
                sys.stdout.flush()
            chunks.append(event.text)
    if stream:
        print("\n")
    return "".join(chunks)

async def extract_csv_with_ai(transport, model_id: str, csv_path: str) -> None:
    plan = get_active_plan()
    if not plan["csv_ai_enabled"]:
        print(
            f"\n[FEATURE LOCKED — {plan['name']} Plan (R{plan['price_zar']}/mo)]\n"
            "AI CSV Batch Extraction is not included in the R299 Starter package.\n"
            "Select Option 5 to upgrade to Growth (R499/mo) or Business (R999/mo) to unlock AI CSV ingestion.\n"
        )
        return

    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}\n")
        return

    with open(csv_path, "r", encoding="utf-8") as f:
        raw_csv = f.read()

    print("\n[AI Extraction Agent] Reading and normalizing supplier CSV...")
    system_prompt = (
        "You are ShelfGuard CSV Extraction AI. Convert messy supplier CSV rows into a strict JSON array. "
        "Each object MUST have exact keys: sku (string), name (string), category (string), "
        "price_zar (number, strip R symbol), batch_id (string), quantity (integer), expiry_date (YYYY-MM-DD). "
        "Return ONLY valid JSON array, no markdown, no extra text."
    )
    user_prompt = f"Extract all stock rows from this CSV into JSON:\n\n{raw_csv}"

    raw_response = await ask_qvac(transport, model_id, system_prompt, user_prompt, stream=False)

    match = re.search(r"\[.*\]", raw_response, re.DOTALL)
    if not match:
        print("AI Extraction failed to return valid JSON. Raw output:\n", raw_response)
        return

    try:
        items = json.loads(match.group(0))
        for item in items:
            res = upsert_extracted_batch(
                sku=item["sku"],
                name=item["name"],
                category=item.get("category", "General"),
                price_zar=float(item["price_zar"]),
                batch_id=item["batch_id"],
                quantity=int(item["quantity"]),
                expiry_date=item["expiry_date"],
            )
            if res["status"] == "SAVED":
                print(f"  + Imported Batch {res['batch_id']} | {res['sku']} | Exp: {res['expiry_date']}")
            else:
                print(f"  ! Skipped: {res['message']}")
        log_agent_decision("CSV Extraction Agent", f"Imported {len(items)} batches from {csv_path}")
        print()
    except Exception as exc:
        print(f"Could not parse extracted records: {exc}\nRaw output:\n{raw_response}\n")

async def interactive_console() -> int:
    init_database()
    seed_sample_stock()

    print("Booting ShelfGuard AI (100% Local QVAC Stack)...")

    async with Client() as client:
        t = client.transport
        try:
            model_id = await load_model(
                t, model_src=LLAMA_3_2_1B_INST_Q4_0, on_progress=print_progress
            )
            print("Local QVAC Model Ready.\n")

            while True:
                plan = get_active_plan()
                print("=" * 64)
                print(f"SHELFGUARD AI — ACTIVE PLAN: {plan['name'].upper()} (R{plan['price_zar']}/mo)")
                print(f"Included: {plan['summary']}")
                print("=" * 64)
                print("1. View Live Warehouse Batches")
                print("2. Upload & AI-Extract Supplier CSV Stock Sheet" + (" [LOCKED on R299]" if not plan["csv_ai_enabled"] else ""))
                print("3. Simulate Online Order Pick (Fulfillment Guard Agent)")
                print("4. Run 10-Day Early Warning & Promo Report" + (" [BASIC ONLY on R299]" if not plan["promo_ai_enabled"] else ""))
                print("5. Switch Store Subscription Plan (R299 / R499 / R999)")
                print("6. Exit")
                choice = input("\nSelect an option (1-6): ").strip()

                if choice == "1":
                    batches = get_all_batches()
                    print(f"\n--- LIVE WAREHOUSE INVENTORY ({len(batches)}/{plan['max_batches']} batch limit) ---")
                    for b in batches:
                        flag = " [EXPIRING SOON]" if b["days_left"] <= 10 else ""
                        print(
                            f"{b['batch_id']} | {b['sku']} | {b['product']} | "
                            f"Qty: {b['quantity']} | Exp: {b['expiry_date']} ({b['days_left']}d left) | R{b['price_zar']:.2f}{flag}"
                        )
                    print()

                elif choice == "2":
                    path = input("Enter CSV filename (press Enter for 'supplier_delivery.csv'): ").strip()
                    if not path:
                        path = "supplier_delivery.csv"
                    await extract_csv_with_ai(t, model_id, path)

                elif choice == "3":
                    sku = input("Enter SKU to pick (e.g. MEAT-101): ").strip().upper()
                    qty_str = input("Enter order quantity (e.g. 2): ").strip()
                    qty = int(qty_str) if qty_str.isdigit() else 1
                    result = evaluate_online_order(sku=sku, requested_qty=qty, auto_deduct=True)
                    print("\n[Fulfillment Guard Agent]")
                    reply = await ask_qvac(
                        t,
                        model_id,
                        system_prompt="You are ShelfGuard Fulfillment Guard. Give a short, clear warehouse picking instruction.",
                        user_prompt=f"Order check result:\n{json.dumps(result, indent=2)}\nTell the packer what to do.",
                    )
                    log_agent_decision("Fulfillment Guard", reply.strip())

                elif choice == "4":
                    warnings = scan_expiring_stock(warning_days=10)
                    if not plan["promo_ai_enabled"]:
                        print("\n[10-Day Basic Expiry Alert — Starter R299 Plan]")
                        for w in warnings:
                            print(f"  - {w['batch_id']} ({w['product']}): {w['days_left']} days left | Qty: {w['quantity']}")
                        print(
                            "\n[UPGRADE TIP] Upgrade to Growth (R499/mo) or Business (R999/mo) via Option 5 "
                            "to unlock Rand (R) loss calculations and AI markdown promo strategies.\n"
                        )
                    else:
                        print("\n[10-Day Early Warning & Promo Advisor Agent]")
                        reply = await ask_qvac(
                            t,
                            model_id,
                            system_prompt=(
                                "You are ShelfGuard Promo Advisor for a South African online grocery warehouse. "
                                "Use ZAR (R) currency. Summarize total Rand value at risk and give short promo actions."
                            ),
                            user_prompt=f"Flagged batches within 10 days of expiry:\n{json.dumps(warnings, indent=2)}",
                        )
                        log_agent_decision("Promo Advisor", reply.strip())

                elif choice == "5":
                    print("\n--- SELECT SHELFGUARD AI SUBSCRIPTION PACKAGE ---")
                    for code, info in PLANS.items():
                        print(f"  {code:<10} | R{info['price_zar']}/month | {info['summary']}")
                    selected = input("\nEnter plan code (STARTER, GROWTH, or BUSINESS): ").strip().upper()
                    updated = set_active_plan(selected)
                    if updated.get("status") == "ERROR":
                        print(f"{updated['message']}\n")
                    else:
                        print(f"\nPlan updated to {updated['name']} (R{updated['price_zar']}/mo)!\n")

                elif choice == "6":
                    print("Unloading model and shutting down ShelfGuard AI...")
                    break
                else:
                    print("Invalid option. Choose 1-6.\n")

            await unload_model(t, model_id)
        except Exception as error:
            print(f"Error: {error}", file=sys.stderr)
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(interactive_console()))
