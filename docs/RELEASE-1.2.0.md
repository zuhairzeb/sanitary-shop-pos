# Version 1.2.0

- Sales History: Return items / bill restores only the selected unreturned quantities. Returns require the `sales.return` permission. Duplicate submissions are idempotent. Discount and GST are allocated from the original bill; partial returns cannot exceed the original line quantity or value.
- Return slips are saved separately and can be previewed, printed and reprinted. They show refund method, reason, processor, stock disposition and return value. The original invoice remains unchanged, with original, returned and net quantity visible from Open / View bill. Physical printer verification remains a shop acceptance step.
- Stock: All Products, Low Stock and Out of Stock filters combine with the search text. Low Stock excludes zero stock.
- Owner and staff creation offer preset security questions. Answers are salted hashes and checked without case sensitivity. Existing accounts retain their configured questions. Accounts without a question still need Owner/vendor assistance.
- Database schema 6 adds return records and indexes, with a migration safety copy. Existing product, user, license and sale records are preserved.
- Product and stock tables render in batches of 100 to keep the event loop available during large loads.

## Development performance utility

Open `developer_tools/start-performance-test.bat`. Choose 100, 500, 1000, 1500 or 5000 products. The tool uses a marked development database under `.performance-data`; Copy existing database uses SQLite's backup API with a read-only source connection. Unmarked/live files are rejected.

Delete Test Products checks the ownership table, exact product ID, code and marker. It preserves untracked products, including real products whose SKU begins with TEST. Products referenced by bills, return slips or the current draft are kept. Source POS business rules create every product.

Run `python developer_tools/performance_data.py --benchmark` to measure 1500 then 5000 products. Timings include database searches, actual Tk table rendering/scrolling, stock, billing, editing and exact scanner lookup. Logs and test databases stay in `.performance-data` and are excluded from the customer build. Benchmarks do not simulate physical scanners/printers or large sales histories.
