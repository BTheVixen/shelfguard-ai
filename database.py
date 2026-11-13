import sqlite3
from datetime import datetime, timedelta

DB_PATH = "shelfguard.db"

PLANS = {
    "STARTER": {
        "name": "Starter",
        "price_zar": 299,
        "max_batches": 25,
        "csv_ai_enabled": False,
        "promo_ai_enabled": False,
        "realtime_tracker": False,
        "audit_feed_enabled": False,
        "summary": "Up to 25 batches + Online Order Fulfillment Guard",
    },
    "GROWTH": {
        "name": "Growth",
        "price_zar": 499,
        "max_batches": 150,
        "csv_ai_enabled": True,
        "promo_ai_enabled": True,
        "realtime_tracker": True,
        "audit_feed_enabled": False,
        "summary": "Up to 150 batches + Real-Time Expiry Telemetry + AI CSV & Promo Advisor",
    },
    "BUSINESS": {
        "name": "Business",
        "price_zar": 999,
        "max_batches": 999999,
        "csv_ai_enabled": True,
        "promo_ai_enabled": True,
        "realtime_tracker": True,
        "audit_feed_enabled": True,
        "summary": "Unlimited batches + Full Real-Time Command Center + Live AI Watchdog Feed",
    },

}

def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)

def init_database() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price_zar REAL NOT NULL,
            min_online_days INTEGER DEFAULT 10
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            batch_id TEXT PRIMARY KEY,
            sku TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            expiry_date TEXT NOT NULL,
            status TEXT DEFAULT 'ONLINE_ELIGIBLE',
            FOREIGN KEY (sku) REFERENCES products (sku)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            summary TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_subscription (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            plan_code TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO store_subscription (id, plan_code, updated_at)
        VALUES (1, 'STARTER', ?)
    """, (datetime.now().isoformat(timespec="seconds"),))

    conn.commit()
    conn.close()

def seed_sample_stock() -> None:
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().date()

    products = [
        ("MEAT-101", "A-Grade Beef Rump Steak 500g", "Meat (Best Before)", 135.00, 10),
        ("MEAT-102", "Free-Range Chicken Fillets 1kg", "Meat (Best Before)", 98.00, 10),
        ("DAIRY-201", "Full Cream Fresh Milk 2L", "Dairy (Best Before)", 38.50, 7),
        ("DELI-301", "Smoked Pork Russians 750g", "Deli (Best Before)", 74.99, 10),
        ("SKIN-401", "Vitamin C Repair Serum 30ml (Best After 6M)", "Cosmetics (Best After)", 249.00, 30),
        ("SUPP-501", "Omega-3 Fish Oil Capsules 60s", "Supplements (Best Before)", 189.00, 30),
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO products (sku, name, category, price_zar, min_online_days)
        VALUES (?, ?, ?, ?, ?)
    """, products)

    batches = [
        ("B-001", "MEAT-101", 12, (today + timedelta(days=1)).isoformat(), "ONLINE_ELIGIBLE"),
        ("B-002", "MEAT-101", 30, (today + timedelta(days=15)).isoformat(), "ONLINE_ELIGIBLE"),
        ("B-003", "MEAT-102", 20, (today + timedelta(days=8)).isoformat(), "ONLINE_ELIGIBLE"),
        ("B-004", "DAIRY-201", 45, (today + timedelta(days=11)).isoformat(), "ONLINE_ELIGIBLE"),
        ("B-005", "DELI-301", 18, (today + timedelta(days=4)).isoformat(), "ONLINE_ELIGIBLE"),
        # Non-food Best After / Best Before items showing 30-day online rule in action
        ("B-006", "SKIN-401", 15, (today + timedelta(days=9)).isoformat(), "ONLINE_ELIGIBLE"),
        ("B-007", "SUPP-501", 40, (today + timedelta(days=60)).isoformat(), "ONLINE_ELIGIBLE"),
    ]

    cursor.executemany("""
        INSERT OR IGNORE INTO batches (batch_id, sku, quantity, expiry_date, status)
        VALUES (?, ?, ?, ?, ?)
    """, batches)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database()
    seed_sample_stock()
    print("Database initialized with subscription tiers.")
