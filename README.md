# Sanitary Shop POS 1.2.3

A Windows desktop cash register that stores products, bills, stock and backups on the laptop. No accounts, browser, internet, Python installation or database server is needed by the shopkeeper.

## Install and use

Copy `SanitaryShopPOS-Setup.exe` from `dist` to a Windows 10/11 x64 laptop. Open it and choose **Install and Open**. Later, open **Sanitary Shop POS** from the Start menu. The installer is unsigned; Windows may display a publisher warning.

1. In **Settings**, enter the shop name, phone and address.
2. In **Products**, add a name, unique code, prices and stock. Leave QR value blank to use the product code.
3. Select a product and choose **Print QR label**. View the QR, set copies and print. Choose paper dimensions in the Windows printer dialog; each copy is one label.
4. In **Billing**, click the large search box or press F2. Type part of a name, code, category or brand, or scan with a USB QR scanner configured as a keyboard with an Enter suffix.
5. Repeated scans increase quantity. Select a bill row to adjust quantity or remove it. Enter discount and payment; blank payment means paid in full.
6. **Save Bill** completes the sale and reduces stock. **Print Bill** saves and opens a native receipt preview. In that preview, choose Print to select a Windows printer. Cancelling printing keeps the sale saved. **New Bill** clears the unfinished bill after confirmation.
7. **Stock** lets you add deliveries or correct quantities. Low stock is marked with both color and words.
8. **Sales** opens and reprints past bills. Prices and shop details on saved bills are preserved.
9. In **Backup**, save a backup to a USB drive regularly. Restore replaces current data after confirmation and first saves a safety copy.

## Data and printing

Data: `%LOCALAPPDATA%\SanitaryShopPOS\shop.sqlite3`. Unfinished bills survive closing. Backup includes the database. Uninstall keeps shop data; reinstall reuses it. Keep backups on another device to protect against losing the laptop.

Native Windows printing uses the installed Windows PowerShell and printer drivers. Install the printer driver before offline use. Select the correct A4, 58 mm, 80 mm or label paper in printer properties. The Settings paper value is retained for HTML exports; native printing uses the selected printer's paper settings. Printing supports wrapped text and multiple pages. Hardware compatibility requires testing with your printer and scanner.

## Developer build

Python 3.13 with Tkinter; SQLite is bundled with Python. Runtime packages: `qrcode==8.2` and `opencv-python-headless==4.10.0.84` for offline laptop-webcam QR scanning. Build tool: PyInstaller 6.16.0. The checked local `.vendor` folder supplies dependencies in this workspace. Run `python -m unittest discover -s tests -v`, then `./build.ps1` to produce the portable folder and self-contained installer. No runtime network calls are made.

For daily coding, do not install or uninstall the packaged app. Run `start-dev.bat` (or `python app.py`) from this folder; it loads the current source files and uses the same shop data folder. Rebuild the installer only when you need to test or distribute a new packaged version. See [docs/UPDATES.md](docs/UPDATES.md) for the HTTPS manifest, hash verification, Owner-only installation flow, release process, and migration safety. For isolated 1,500/5,000-product stress testing, use [docs/PERFORMANCE-TESTING.md](docs/PERFORMANCE-TESTING.md); the developer tool can launch the actual POS UI against the marked test database and is intentionally excluded from the customer build.

See `docs/ACCEPTANCE.md` for fresh-laptop verification. Optional PNG/GIF product photos (up to 5 MB) are stored in the database and included in backups.


## QR labels, logo and sales history

- All table headings and values are centered.
- Products supports Ctrl/Shift multi-selection. **Select all products** clears the search and selects the entire active catalog. **Download selected QR labels** saves an A4 PDF, with a copies-per-product option. Each QR square is exactly 20 × 20 mm including its quiet zone; the product code is underneath. Print at **Actual size / 100%**, not Fit to page. Single QR previews also support this PDF export and native 20 mm printing.
- Settings → **Add / change shop logo** accepts PNG/JPG/GIF up to 5 MB. The logo is stored in the database, appears in the app and on new receipt previews/prints/PDFs, and is included in backups. Old bills keep their original logo.
- Sales → **Delete selected bills** or **Clear all sales** removes history and updates sales totals after confirmation. **Stock stays unchanged**. Clear all affects even bills hidden by filters. A safety backup is saved beside the database before deletion, and bill numbers are never reused.

## Users and offline licensing

On startup, the POS verifies a device-bound signed license locally, then displays the user/PIN login screen. PINs use salted `scrypt` hashes and are never stored as plain text. The first activated run creates the Owner account. The Owner can add Manager and Cashier accounts, reset staff PINs, customize Manager/Cashier role permissions, and review audit history.

Licenses are signed with Ed25519. The customer POS has only the public verification key. The vendor-only [license generator](developer_tools/license_generator.py) takes a private key supplied as a file path; it does not contain or create a customer-distributed private key. Keep the private key outside this repository, installer, backups and customer computers. The license file is stored separately as `%LOCALAPPDATA%\SanitaryShopPOS\license.json`; copying it or the database to another Windows installation fails the current-device check.

Users can start a 14-day offline trial. The POS stores a last-seen date to catch clock rollback without relying only on the current Windows date. For a forgotten Owner PIN, use the login screen to create a recovery request and send it to the software vendor; there is no built-in master password.

## Copyright

© 2026 [Sociapi](https://sociapis.vercel.app/). All rights reserved. Built by [Zuhair](https://xuhair.netlify.app/).
