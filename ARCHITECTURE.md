# ShelfGuard AI — System Architecture

## 1. Problem Statement

Online shoppers buying any date-sensitive goods—from fresh food and beverages to cosmetics, skincare, and supplements governed by Best Before and Best After rules— expect fresh deliveries that last in their fridge or freezer. Standard warehouse picking relies on basic FIFO without verifying remaining shelf life, resulting in customers receiving items expiring within 24 hours. Meanwhile, store owners lack early visibility into slow-moving perishable batches, and cloud AI tools fail during fibre outages or load-shedding.

## 2. Hybrid Deterministic + Local AI Architecture

ShelfGuard AI separates **strict mathematical rules** (handled by Python and SQLite so dates, quantities, and Rand prices are never hallucinated) from **schema mapping and natural-language reasoning** (handled locally by QVAC).

```text
+-----------------------------------------------------------------------+

|                    DESKTOP PRESENTATION LAYER (OFFLINE)               |
|         Standalone Desktop Window (http://127.0.0.1:8000)             |
|  - Live FEFO Batch Table     - Plan Switcher (R299 / R499 / R999)     |
|  - Online Order Simulator    - CSV Dropzone & Promo Strategy Console  |
+-----------------------------------+-----------------------------------+
                                    | REST API (JSON / Multipart)
                                    v
+-----------------------------------------------------------------------+

|                    FASTAPI BACKEND & ORCHESTRATOR                     |
|                         (desktop_app.py)                              |
|  - Tier-Based Feature Gatekeeper   - Async QVAC Lifecycle Manager     |
+-----------------------------------+-----------------------------------+
                                    |
                 +------------------+------------------+

                 |                                     |
                 v                                     v
+---------------------------------+   +---------------------------------+

|   DETERMINISTIC LOGIC ENGINE    |   |   LOCAL QVAC AI RUNTIME         |
|          (tools.py)             |   |   (tetherto.qvac_sdk)           |
|  - FEFO & 10-Day Rule Math      |   |  - Agent 1: CSV Schema Mapper   |
|  - Auto Stock Deduction         |   |  - Agent 2: Fulfillment Guard   |
|  - ZAR Risk & Tier Calculations |   |  - Agent 3: Promo Strategist    |
+----------------+----------------+   +----------------+----------------+

                 |                                     |
                 +------------------+------------------+
                                    | SQL Queries & Audit Logs
                                    v
+-----------------------------------------------------------------------+

|                  LOCAL PERSISTENCE LAYER (R0 COST)                    |
|                     SQLite Database (shelfguard.db)                   |
|  - products   - batches   - store_subscription   - alerts_log         |
+-----------------------------------------------------------------------+
```

## 3. Database Schema (`shelfguard.db`)

* **`products`**: `sku` (PK), `name`, `category`, `price_zar`, `min_online_days`
* **`batches`**: `batch_id` (PK), `sku` (FK), `quantity`, `expiry_date`, `status`
* **`store_subscription`**: `id`, `plan_code` (`STARTER`, `GROWTH`, `BUSINESS`), `updated_at`
* **`alerts_log`**: `id`, `created_at`, `agent_role`, `summary`

## 4. Subscription Tier Matrix

* **Starter (`R299/mo`)**: Up to 25 active batches + Online Order Fulfillment Guard + Basic expiry alerts.
* **Growth (`R499/mo`)**: Up to 150 active batches + AI CSV Batch Extraction + Daily Rand (`R`) Promo Advisor.
* **Business (`R999/mo`)**: Unlimited batches + Unlimited Bulk CSV Batch Processing + Full AI Strategy & Audit Logs.
