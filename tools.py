from datetime import datetime
from database import PLANS, get_connection

def get_active_plan() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT plan_code, updated_at FROM store_subscription WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    code = row[0] if row else "STARTER"
    plan = PLANS.get(code, PLANS["STARTER"]).copy()
    plan["code"] = code
    plan["updated_at"] = row[1] if row else ""
    return plan

def set_active_plan(plan_code: str) -> dict:
    code = plan_code.strip().upper()
    if code not in PLANS:
        return {"status": "ERROR", "message": f"Unknown plan '{plan_code}'."}

    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat(timespec="seconds")
    cursor.execute("""
        INSERT INTO store_subscription (id, plan_code, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            plan_code = excluded.plan_code,
            updated_at = excluded.updated_at
    """, (code, now_str))
    conn.commit()
    conn.close()
    return get_active_plan()

def scan_expiring_stock(warning_days: int = 10) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().date()

    cursor.execute("""
        SELECT b.batch_id, p.sku, p.name, b.quantity, b.expiry_date, p.price_zar
        FROM batches b
        JOIN products p ON b.sku = p.sku
        WHERE b.quantity > 0
        ORDER BY b.expiry_date ASC
    """)

    flagged = []
    for batch_id, sku, name, qty, exp_str, price in cursor.fetchall():
        exp_date = datetime.fromisoformat(exp_str).date()
        days_left = (exp_date - today).days

        if days_left <= warning_days:
            risk_zar = round(qty * price, 2)
            if days_left <= 2:
                rule = "CRITICAL (<=2 days): Block online sales immediately. Apply 50% flash clearance."
            elif days_left <= 5:
                rule = "HIGH RISK (3-5 days): Hold from online orders. Run 35% bundle discount."
            else:
                rule = "10-DAY EARLY WARNING (6-10 days): Launch 20% promo to accelerate sell-through."

            flagged.append({
                "batch_id": batch_id,
                "sku": sku,
                "product": name,
                "days_left": days_left,
                "quantity": qty,
                "value_at_risk_zar": risk_zar,
                "system_rule": rule,
            })

    conn.close()
    return flagged

def evaluate_online_order(sku: str, requested_qty: int, auto_deduct: bool = True) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().date()

    cursor.execute("SELECT name, min_online_days FROM products WHERE sku = ?", (sku,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        return {"status": "ERROR", "message": f"SKU {sku} not found in database."}

    name, min_days = product

    cursor.execute("""
        SELECT batch_id, quantity, expiry_date
        FROM batches
        WHERE sku = ? AND quantity >= ?
        ORDER BY expiry_date ASC
    """, (sku, requested_qty))

    blocked_batches = []
    for batch_id, qty, exp_str in cursor.fetchall():
        days_left = (datetime.fromisoformat(exp_str).date() - today).days
        if days_left >= min_days:
            remaining_qty = qty - requested_qty
            if auto_deduct:
                cursor.execute(
                    "UPDATE batches SET quantity = ? WHERE batch_id = ?",
                    (remaining_qty, batch_id),
                )
                conn.commit()
            conn.close()
            return {
                "status": "APPROVED",
                "sku": sku,
                "product": name,
                "pick_batch": batch_id,
                "picked_qty": requested_qty,
                "remaining_batch_qty": remaining_qty,
                "days_left": days_left,
                "blocked_near_expiry": blocked_batches,
                "rule_applied": f"Meets {min_days}-day minimum online freshness rule.",
            }
        else:
            blocked_batches.append(f"{batch_id} (only {days_left} day(s) left)")

    conn.close()
    return {
        "status": "BLOCKED",
        "sku": sku,
        "product": name,
        "reason": f"No batch meets the {min_days}-day online shelf-life threshold.",
        "blocked_near_expiry": blocked_batches,
    }

def upsert_extracted_batch(
    sku: str,
    name: str,
    category: str,
    price_zar: float,
    batch_id: str,
    quantity: int,
    expiry_date: str,
    min_online_days: int = 10,
) -> dict:
    plan = get_active_plan()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM batches WHERE quantity > 0")
    active_count = cursor.fetchone()[0]
    if active_count >= plan["max_batches"]:
        conn.close()
        return {
            "status": "PLAN_LIMIT_REACHED",
            "message": f"{plan['name']} (R{plan['price_zar']}/mo) allows max {plan['max_batches']} active batches.",
        }

    cursor.execute("""
        INSERT INTO products (sku, name, category, price_zar, min_online_days)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO UPDATE SET
            name = excluded.name,
            price_zar = excluded.price_zar
    """, (sku.strip().upper(), name.strip(), category.strip(), float(price_zar), int(min_online_days)))

    cursor.execute("""
        INSERT INTO batches (batch_id, sku, quantity, expiry_date, status)
        VALUES (?, ?, ?, ?, 'ONLINE_ELIGIBLE')
        ON CONFLICT(batch_id) DO UPDATE SET
            quantity = excluded.quantity,
            expiry_date = excluded.expiry_date
    """, (batch_id.strip().upper(), sku.strip().upper(), int(quantity), expiry_date.strip()))

    conn.commit()
    conn.close()
    return {"status": "SAVED", "batch_id": batch_id.strip().upper(), "sku": sku.strip().upper(), "expiry_date": expiry_date.strip()}

def get_all_batches() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().date()

    cursor.execute("""
        SELECT b.batch_id, p.sku, p.name, p.category, b.quantity, b.expiry_date, p.price_zar
        FROM batches b
        JOIN products p ON b.sku = p.sku
        ORDER BY b.expiry_date ASC
    """)

    rows = []
    for batch_id, sku, name, category, qty, exp_str, price in cursor.fetchall():
        days_left = (datetime.fromisoformat(exp_str).date() - today).days
        rows.append({
            "batch_id": batch_id,
            "sku": sku,
            "product": name,
            "category": category,
            "quantity": qty,
            "expiry_date": exp_str,
            "days_left": days_left,
            "price_zar": price,
        })
    conn.close()
    return rows

def get_realtime_telemetry() -> dict:
    batches = get_all_batches()
    warnings = scan_expiring_stock(warning_days=10)

    total_value_zar = round(sum(b["quantity"] * b["price_zar"] for b in batches if b["quantity"] > 0), 2)
    at_risk_zar = round(sum(w["value_at_risk_zar"] for w in warnings), 2)
    blocked_count = sum(1 for b in batches if b["days_left"] <= 2 and b["quantity"] > 0)
    warning_count = sum(1 for b in batches if 2 < b["days_left"] <= 10 and b["quantity"] > 0)
    healthy_count = sum(1 for b in batches if b["days_left"] > 10 and b["quantity"] > 0)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_at, agent_role, summary FROM alerts_log ORDER BY id DESC LIMIT 5")
    recent_events = [
        {"time": row[0], "agent": row[1], "summary": row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()

    return {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "total_inventory_zar": total_value_zar,
        "at_risk_zar": at_risk_zar,
        "blocked_batches": blocked_count,
        "warning_batches": warning_count,
        "healthy_batches": healthy_count,
        "recent_events": recent_events,
    }

def log_agent_decision(agent_role: str, summary: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO alerts_log (created_at, agent_role, summary) VALUES (?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), agent_role, summary),
    )
    conn.commit()
    conn.close()
