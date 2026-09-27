# Verification — 2026-09-15

- 12 automated tests pass, including real Tk windows, repeated scans, payment/change, stock deduction, transaction rollback, draft recovery, backup/restore and historical bill snapshots.
- Billing actions remain visible at 1180×780 and 980×680.
- Native System.Drawing print layout rendered a long test document across five pages; first page visually inspected for QR and wrapped text.
- Packaged application startup/shutdown test passed with exit code 0 and an isolated data folder.
- Final self-contained installer startup/shutdown test passed with exit code 0 using a temporary folder inside the workspace. The restricted execution environment could not initialize Tcl from its default user temporary folder, so normal default-folder startup on a fresh laptop remains unverified.
- No physical printer, USB scanner, second laptop, actual installation/uninstallation, or disconnected-device test was performed. Follow ACCEPTANCE.md before shop deployment.

Deliverable: `dist/SanitaryShopPOS-Setup.exe`. Its SHA-256 is in `dist/SHA256.txt`. The installer is unsigned. Shop data is stored separately from installed application files.

## UI redesign and installer correction

- Light blue/white theme, restyled navigation and buttons, split billing workspace with a payment panel.
- Optional customer information opens in a small dialog; primary payment actions remain visible at 980×680 and 1180×780.
- 15 automated tests pass, including panel-boundary checks and source installer regression coverage.
- Installer supports source and packaged paths without requiring `_MEIPASS` during source execution. The installed uninstaller is the setup executable, not a copied Python interpreter.

## 2026-09-16 requested changes

- 19 tests pass, including centered headings/cells, select-all behavior, history deletion without stock changes, non-reused bill numbers, exact QR module dimensions, multipage labels, and logo backup/restore/PDF embedding.
- A 55-product label export was rendered and both pages visually inspected. A rendered 300 dpi QR decoded to the correct product code with OpenCV.
- Native print drawing was exercised for both 20 mm QR/code labels and logo receipts using bitmap rendering; physical printer output remains untested.
- Settings controls fit at 980×680, including the logo picker and Save settings.
