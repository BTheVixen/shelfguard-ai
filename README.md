# ShelfGuard AI — Offline Multi-Agent Warehouse Intelligence

**ShelfGuard AI** is a 100% offline, local-first multi-agent inventory monitoring desktop application built with **Python**, **FastAPI**, **SQLite**, and **QVAC SDK (`tetherto.qvac_sdk`)**.

It solves a critical problem in South African online grocery and perishable fulfilment: preventing near-expiry all date-sensitive products (food, beverages, cosmetics, supplements, and pantry goods) governed by Best Before and Best After / Period-After-Opening rules from being shipped to online buyers while giving store owners a **10-day early-warning system** to turn potential food waste into revenue.

## Key Capabilities

* **Online Order Fulfillment Guard (FEFO + Minimum Shelf Life):** Enforces First-Expired, First-Out picking with a strict minimum online shelf-life threshold (default 10 days). Near-expiry batches are automatically blocked from online orders while fresh batches are allocated and deducted in real time.
* **10-Day Early Warning & Promo Advisor Agent:** Scans active batches approaching expiry, calculates exact South African Rand (`R`) revenue at risk, and recommends tiered clearance discounts (20%, 35%, or 50% flash sales).
* **AI Supplier CSV Batch Extraction:** Uses local QVAC text generation to map messy supplier spreadsheet headers (`LotCode`, `UnitRand`, `BestBefore`) to the warehouse schema and ingest batch deliveries into SQLite.
* **Self-Service SaaS Tier Gating:** Built-in subscription enforcement supporting **Starter (`R299/mo`)**, **Growth (`R499/mo`)**, and **Business (`R999/mo`)** tiers offline.

## Tech Stack & AI Capabilities

* **AI Runtime:** QVAC SDK (`tetherto.qvac_sdk`) running `LLAMA_3_2_1B_INST_Q4_0` locally on GPU/CPU (zero cloud API fees, load-shedding resilient).
* **AI Capabilities Showcased:** Text Generation (Structured JSON Schema Mapping & Operational Advisory) and Batch Processing (Bulk CSV Stock Ingestion).
* **Backend & Desktop UI:** Python 3, FastAPI, Uvicorn, SQLite3, and standalone desktop app mode (`--app`).

## Quick Start

1. Activate your virtual environment:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
2. Launch the ShelfGuard AI Desktop Application:
   ```powershell
   python desktop_app.py
   ```
3. To reset demo data before a presentation:
   ```powershell
   Remove-Item shelfguard.db -ErrorAction SilentlyContinue
   python desktop_app.py
   ```
