# Development performance testing

This tool is development-only. It is not imported by `app.py`, is not included by the PyInstaller entry point, and must never be shipped to customers.

## Start the tool

From the repository root on the developer workstation:

```powershell
python developer_tools/performance_data.py
```

Or double-click `developer_tools/start-performance-test.bat`.

The GUI works only with a marked development database. It can create a blank database or make a read-only copy of an existing shop database into `.performance-data`. The customer database is never seeded directly.

Choose 100, 500, 1000, 1500, or 5000 products, then choose **Generate Test Products**. Every generated row has a `[TEST]` name, a `TEST-` SKU, a generated QR equal to the SKU, and a unique run marker tracked in `dev_generated_products`.

After generation, select the `interactive.sqlite3` file and click **Launch POS With Test Database**. This starts the actual existing POS UI with:

```text
python app.py --data-dir .performance-data\interactive.sqlite3 --performance-test-db
```

The POS title/header shows `TEST DATABASE — DEVELOPMENT MODE`. Products, Stock, Billing, search, SKU/QR lookup, editing, and sales screens then operate on that SQLite file. The real `%LOCALAPPDATA%\SanitaryShopPOS` database is not opened or changed. The same launch is available from `developer_tools/start-pos-performance-test.bat`.

The flag requires the development marker table and is rejected by frozen/packaged builds. Therefore the customer production executable cannot enter this test mode, and the developer seeder is not included in the PyInstaller payload.

**Delete Test Products** removes only rows whose product id, SKU, and development marker still match the generator record. Products used by a bill or unfinished draft are kept. Real products are never deleted.

## Automated benchmark

Run:

```powershell
python developer_tools/performance_data.py --benchmark
```

This creates isolated marked databases for 1,500 and 5,000 products, measures database searches, exact SKU/QR lookup, Products/Stock/Sales refresh, scrolling, billing searches, add-to-bill, edit, and billing refresh, and writes JSON to `.performance-data/performance-report.json`.

The benchmark disables automatic update checks in its isolated copy so network/update work cannot contaminate timings. It does not alter customer data or the normal POS database.

## What to inspect

Check the report for:

- database query time
- product page refresh time
- stock page refresh time
- name, SKU, category, brand, and size search time
- exact QR/SKU lookup time
- add-to-bill time
- edit-product time
- billing refresh time
- scrolling responsiveness

The current billing search already bounds visible results to 60 rows. Products and Stock tables are intentionally measured with the complete active result set so a developer can see when pagination or lazy rendering becomes necessary for a target laptop.

## Production boundary

Do not add `developer_tools.performance_data` to `app.py`, the PyInstaller spec, or runtime imports. Do not point the tool at the live customer database. Use a separate development copy and delete `.performance-data` after testing when its results are no longer needed.
