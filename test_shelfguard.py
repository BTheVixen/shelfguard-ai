import os
import unittest

import database
from tools import (
    evaluate_online_order,
    get_active_plan,
    scan_expiring_stock,
    set_active_plan,
    upsert_extracted_batch,
)


class TestShelfGuardCore(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_shelfguard_temp.db"
        database.DB_PATH = self.test_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        database.init_database()
        database.seed_sample_stock()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_1_subscription_tier_gating(self):
        plan = get_active_plan()
        self.assertEqual(plan["code"], "STARTER")
        self.assertFalse(plan["csv_ai_enabled"])

        upgraded = set_active_plan("BUSINESS")
        self.assertEqual(upgraded["price_zar"], 999)
        self.assertTrue(upgraded["csv_ai_enabled"])

    def test_2_online_order_blocks_near_expiry_meat(self):
        # B-001 expires in 1 day (must be skipped); B-002 expires in 15 days (must be picked)
        res = evaluate_online_order(sku="MEAT-101", requested_qty=2, auto_deduct=True)
        self.assertEqual(res["status"], "APPROVED")
        self.assertEqual(res["pick_batch"], "B-002")
        self.assertEqual(res["remaining_batch_qty"], 28)
        self.assertTrue(any("B-001" in b for b in res["blocked_near_expiry"]))

    def test_3_cosmetics_best_after_30_day_rule(self):
        # SKIN-401 (B-006) has 9 days left vs 30-day minimum -> must be BLOCKED
        res = evaluate_online_order(sku="SKIN-401", requested_qty=1, auto_deduct=True)
        self.assertEqual(res["status"], "BLOCKED")

    def test_4_ten_day_early_warning_scanner(self):
        warnings = scan_expiring_stock(warning_days=10)
        batch_ids = [w["batch_id"] for w in warnings]
        self.assertIn("B-001", batch_ids)
        self.assertIn("B-003", batch_ids)
        self.assertIn("B-006", batch_ids)
        self.assertNotIn("B-007", batch_ids)  # 60 days left -> safe

    def test_5_supplier_batch_ingestion(self):
        set_active_plan("GROWTH")
        saved = upsert_extracted_batch(
            sku="BEV-601",
            name="Cold-Pressed Orange Juice 1L",
            category="Beverages",
            price_zar=34.50,
            batch_id="SUPB-701",
            quantity=18,
            expiry_date="2026-11-18",
        )
        self.assertEqual(saved["status"], "SAVED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
