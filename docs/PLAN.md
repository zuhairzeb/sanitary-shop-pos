# Sanitary Shop POS — implementation plan

## Stack and scope
Python 3.13, Tkinter desktop controls, SQLite, and the small `qrcode` library for printable SVG labels. PyInstaller is a build-only tool. No server, accounts, browser framework, external fonts, or network calls at runtime. Windows 10/11 is the initial supported target; older Windows versions require separate compatibility testing. Use a folder-based executable bundle for predictable startup and USB distribution. Receipts and QR labels use native Tk previews and Windows printing through bundled PowerShell code. The printer dialog controls paper size. The self-contained installer includes the runtime; shop data survives uninstall.

## Architecture
`app.py` starts the window; `sanitary_pos/ui.py` owns screens; `db.py` owns validation, transactions, backup and persistence; `receipts.py` produces local receipts and QR labels. SQLite data lives in the user's Local AppData/SanitaryShopPOS folder by default; `--data-dir` overrides it. Separate source code and customer data. One application instance per data folder. No demo data in the live database.

## SQLite tables and relationships
- **products**: id PK, unique code, unique QR payload, name, category, brand, purchase_paisa, selling_paisa, stock_milli, unit, description, active. Stock uses thousandths so meter quantities can be fractional. Deletion archives products to retain relationships.
- **sales**: id PK, unique checkout token, created_at local ISO timestamp, subtotal_paisa, discount_paisa, total_paisa, paid_paisa, shop_json. Bill number derives from id. Shop details are captured at sale time.
- **sale_items**: id PK, sale_id FK → sales, product_id FK → products, name/code/unit snapshots, quantity_milli, price_paisa, total_paisa. Historical bills survive later product edits.
- **stock_movements**: id PK, product_id FK → products, delta_milli, reason, created_at. Records opening stock, edits and completed sales.
- **settings**: key PK, value; shop name, phone, address, receipt size, low-stock threshold.
- **draft**: id fixed to 1, payload JSON; current cart, checkout token, discount and payment. Updated on each bill change; cleared inside the completed-sale transaction.

All SQL uses bound values. Sale completion uses BEGIN IMMEDIATE, rechecks stock, validates amounts, records immutable line snapshots, deducts stock and clears draft in one transaction. A unique checkout token prevents double billing after retries. Prices use integer paisa, quantities integer thousandths, and line totals round half up.

## Screens and flows
1. **Billing** (startup): prominent scan/search field → instant matching name/code/category/brand → click result or Enter exact scan → one row per product → select row to increase/decrease/set quantity/remove → discount and payment → Save Bill / Print Bill. Enter suffix required on USB keyboard scanner; F2 returns focus to scan/search. Completion saves first, then opens receipt, so a printer failure cannot lose a sale.
2. **Products**: search list → Add/Edit dialog for all product fields → save; archive requires confirmation; default QR payload equals product code, custom payload supported; printable QR label.
3. **Stock**: product/category/price/stock table, low/out-of-stock colors and words → select product → stock adjustment with reason.
4. **Sales**: today's final sales amount → bill number/date filters → open receipt → print again.
5. **Settings**: shop details, paper width, low stock limit → Save; Backup Data to selected USB/folder; Restore Data validates schema/integrity then confirms replacement and saves safety backup.

Navigation preserves draft. Closing preserves draft. Clearing a bill and deleting products require confirmation. Out-of-stock results stay visible. Empty state guides first-time users to Add Product. Simple error messages with technical details only in a local log.

## Folder structure
```
app.py
sanitary_pos/{__init__,db,ui,receipts}.py
tests/test_pos.py
docs/PLAN.md
README.md
requirements.txt
build.ps1
start.bat
```

## Development phases
1. Storage and validation: schema, fixed-point arithmetic, transactions, draft recovery.
2. Core MVP: products → scan/search → cart → complete sale → stock update → receipt.
3. Operational screens: inventory adjustments, sales lookup/reprint, settings, QR labels, backup/restore.
4. Verification and distribution: business-rule tests, real Tk smoke tests, Windows executable build and operator instructions. Physical printer/scanner testing requires shop hardware.

## Implemented additions
Dedicated Backup tab; optional PNG/GIF photos stored in SQLite; multiple QR label copies; native printing with wrapping and pagination; installer and Start menu shortcut. Automated tests cover 12 business and real-window integration cases. See ACCEPTANCE.md for hardware tests still required.
