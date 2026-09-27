# Release acceptance checklist

Automated tests do not replace physical-device testing. Record laptop model, Windows version, scanner model, printer/driver, date and result for each run.

- Copy installer to a second Windows 10/11 x64 laptop with no Python or Node installed.
- Disconnect internet, install, open from Start menu.
- Add Master Ceramic Basin, BASIN001, purchase 4000, selling 4800, stock 10.
- View QR and print one label and three copies. Scan printed label using a USB QR-capable keyboard scanner with Enter suffix.
- Scan twice: one bill row, quantity 2, total Rs. 9600. Search by partial name, code, category and brand.
- Apply Rs. 100 discount and Rs. 10000 payment: total 9500, change 500.
- Save bill: stock becomes 8. Reprint from Sales. Cancelling the print dialog must not create another bill.
- Test A4, narrow receipt and a bill spanning multiple pages; check every item and totals. Test long product names and non-English text.
- Save another bill with partial payment and verify remaining amount.
- Test stock corrections, low stock and an attempt to oversell.
- Close/reopen: saved bills, stock and unfinished cart remain available.
- Backup to USB, change data, restore backup, verify original data and safety backup.
- Reject a damaged/non-shop backup without changing current data.
- Uninstall and reinstall offline: original shop data remains available.
- Repeat on another normal laptop and real shop printer/scanner.

Physical printing, QR decoding by hardware, disconnected fresh-laptop installation and uninstall/reinstall are pending until performed on those devices.

## Users and licensing

- Generate a signed Lifetime license with the vendor-only utility and activate it on the displayed Device ID.
- Restart the POS: the license remains active and the User/PIN login appears.
- Copy the database and license file to a different Windows installation: activation must be rejected as another device.
- Change any character of the license JSON: activation must be rejected.
- Start a trial; move the Windows date backwards; confirm the POS asks for vendor help rather than silently extending the trial.
- Create Owner, Manager and Cashier users. Confirm PINs are not readable in SQLite or logs.
- Sign in as Cashier: create/print a bill; verify product deletion, price changes, stock updates, Settings and sales cancellation are denied.
- Sign in as Manager: confirm normal product and stock work; confirm Users, license administration and Restore are denied by default.
- As Owner, change Cashier permissions, sign out/in as Cashier, and confirm the new permissions apply.
- Confirm Owner PIN approval works for a Cashier discount and Restore backup.
- Review Audit history for bill creation, user changes, stock movements, product changes and sales cancellation. Confirm no PIN appears.
- Backup and restore. Confirm users and permissions return, then verify the current computer still independently passes license validation.
