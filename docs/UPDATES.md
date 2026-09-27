# Software updates

## Update feed

Customer installers use the public releases repository:

https://github.com/zuhairzeb/sanitary-shop-pos-updates

Permanent manifest URL:

https://github.com/zuhairzeb/sanitary-shop-pos-updates/releases/latest/download/update.json

The public repository contains release installers and signed update manifests. The source checkout and vendor private key stay on the developer machine. No paid hosting, domain or customer GitHub login is required.

## Publish an update

1. Make and test the source changes.
2. Increase `APP_VERSION` in `sanitary_pos/version.py`. Never reuse a published version.
3. Edit `developer_tools/release-notes.txt` with the customer-facing changes.
4. Double-click `developer_tools/publish-update.bat`.

The script runs all tests, builds the app and installer, records the installer version/hash, signs `dist/update.json`, and uploads both files to a draft GitHub Release. Only after both uploads succeed does it publish the release as latest. Publishing requires the `zuhairzeb` account signed into Git Credential Manager and the matching private key in `developer_keys/ssp-ed25519.privatekey`. It never uploads that key or the source directory.

To inspect GitHub login without publishing:

```powershell
python developer_tools/publish_update.py
```

To publish an already built and verified installer:

```powershell
python developer_tools/publish_update.py --publish
```

If an upload fails, the release stays a draft. Retrying reuses complete assets whose hashes match. If the build changed after a partial upload, remove the conflicting draft asset in GitHub before retrying. Published releases are not overwritten. If you code-sign the installer after building, run `python developer_tools/record_build.py` before publishing to record the final installer hash.

## Client behavior

Existing clients need this updater-enabled version installed once. Afterward the installed POS checks daily while open (and checks on startup when due). A header button announces an available update. Owners use **Settings → Software Update → Update Now** to download it. The POS verifies the manifest's Ed25519 signature and installer SHA-256, makes a database backup, closes and opens the setup. The customer chooses **Update and Open** in setup. Managers and Cashiers cannot install updates.

The POS remains usable offline; failed update checks do not prevent billing. Development source sessions do not check automatically, but manual update checks remain available.

Application files live under `%LOCALAPPDATA%\Programs\SanitaryShopPOS`. Shop data and license live under `%LOCALAPPDATA%\SanitaryShopPOS`. Updating the app keeps that data and creates `before-update-*.sqlite3` before installation. Schema migrations create a separate safety copy when needed. Do not downgrade a migrated database by installing an older app.

## Verification

Run `python -m unittest discover -s tests -v`. The build runs this suite automatically. Test the packaged application using an isolated `--data-dir`; `dist/SanitaryShopPOS-Setup.exe --verify-install` verifies installation into a temporary directory without replacing the developer's installed POS.

After publishing, verify the public manifest and installer download. The publisher keeps the release in draft until both assets are uploaded.
