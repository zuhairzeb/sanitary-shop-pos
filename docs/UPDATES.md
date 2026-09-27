# Software updates

## Customer update behavior

Sanitary Shop POS remains fully usable offline. Update checks are the only network operation. Automatic checks are limited to once per day and never install without Owner confirmation.

Configure the real HTTPS manifest endpoint in `sanitary_pos/updater.py` by setting `UPDATE_MANIFEST_URL`. Leave it empty in development builds. The production value must be reviewed before packaging; never ship a test endpoint to customers.

A manifest contains:

```json
{
  "latest_version": "1.1.1",
  "download_url": "https://updates.example.com/SanitaryShopPOS-Setup.exe",
  "sha256": "64 hexadecimal characters",
  "release_notes": ["Fixed QR scanning", "Improved receipt printing"]
}
```

The download must use HTTPS, end in `.exe`, and match the manifest SHA-256 exactly. An optional Ed25519 signature can be enabled by setting `UPDATE_MANIFEST_PUBLIC_KEY_HEX`; the signature covers the manifest JSON excluding the `signature` field, serialized with sorted keys and compact separators. If a Windows signing certificate is available, set `EXPECTED_PUBLISHER` to a stable publisher-subject fragment and Authenticode verification will run before launch. Unverified or malformed updates are never started.

Before an update starts, the POS creates a timestamped `before-update-*.sqlite3` copy beside the shop database. Application files live under `%LOCALAPPDATA%\\Programs\\SanitaryShopPOS`; shop data, settings, users, license, logs, and backups live under `%LOCALAPPDATA%\\SanitaryShopPOS` and are not replaced by an application update.

Only the Owner has `software.update`. Managers and Cashiers can see an available version but cannot install it. The existing valid device-bound license is not regenerated or replaced.

## Release workflow

1. Make the source change.
2. Change `APP_VERSION` in `sanitary_pos/version.py` using semantic versioning: patch for fixes, minor for compatible features, major for breaking changes.
3. Add concise release notes to the update manifest.
4. Run `python -m unittest discover -s tests -v`.
5. Build with `./build.ps1`.
6. Code-sign `dist/SanitaryShopPOS-Setup.exe` when a Windows signing certificate is available.
7. Calculate SHA-256 for the final installer: `Get-FileHash dist/SanitaryShopPOS-Setup.exe -Algorithm SHA256`.
8. Upload the installer to HTTPS hosting.
9. Update and publish the manifest only after the installer upload succeeds.
10. Test Check for Updates, Later, Owner Update Now, wrong-hash rejection, and offline behavior on a separate data directory.

Do not replace the manifest before the installer is reachable and its final hash is known. Do not use a database downgrade as a rollback mechanism; restore the timestamped database safety copy manually if a migration requires recovery.

## Local development test

Keep `UPDATE_MANIFEST_URL` empty in normal development so no endpoint is contacted. For a local test, patch the module value at runtime or use a test manifest with a local HTTP mock only in automated tests; production validation rejects non-HTTPS URLs. Use a temporary `--data-dir` and a signed or hash-matching test installer. Never put development URLs or test private keys in a production build.
