# Users, permissions and offline licensing

## License keys and PIN recovery

The generator writes both a `.lic` file and a `.key.txt` file. Use Copy key in the generator to share the entire SSP1 key. Customers may select the license file or paste the key on activation; both verify the same signature and device binding. These are long offline keys, not short online activation codes.

Switch User saves the current bill draft and returns to login. The next user receives their own permissions. Change my PIN requires the current PIN. An Owner can reset staff PINs under Users & Privileges.

For a forgotten Owner PIN, select the Owner on login and click Forgot PIN. Save the recovery request and send it to the vendor. The vendor verifies the customer independently, uses Approve owner PIN recovery in the private generator, and sends the SSPR1 key back. The Owner pastes it and enters a new PIN twice. Requests expire after three days, are bound to the device and Owner, and are consumed after use. Creating a new request replaces the previous request. No universal PIN is included.

## Customer POS

The customer application verifies signed Ed25519 license documents using the public key in `sanitary_pos/licensing.py`. It does not include a private signing key or a license generator. The activation screen displays the current device ID and accepts a signed JSON license file. Licenses check product name, signature, device ID, type and optional expiry date before login.

The device ID is derived from the Windows installation MachineGuid (with a conservative fallback) and an installation salt stored in local SQLite. A copied database therefore produces a different device ID on another Windows installation. The license file is not part of the SQLite backup. User configuration and audit history are backed up, but a restored backup does not bypass the new computer's license check.

## Vendor process

Use `developer_tools/license_generator.py` only on the vendor/admin machine. Supply the vendor-held raw 32-byte Ed25519 private key with `--private-key` or by selecting it in the GUI; do not put that key in the repository, customer project, backup, installer or license file.

### 1. Start the private License Generator

Either run the GUI:

```
python developer_tools/license_generator.py
```

or use the command line:

```
python developer_tools/license_generator.py --private-key developer_keys\ssp-ed25519.privatekey --shop "ABC Sanitary Store" --device-id SSP-0000-0000-0000-0000 --type LIFETIME --license-id SSP-2026-0001 --out developer_keys\generated_licenses\ABC-Sanitary.lic
```

### 2. Where generated .lic files are saved

The generator defaults to:

```
developer_keys/generated_licenses/
```

Each file is named using the customer name and device ID, for example:

```
developer_keys/generated_licenses/ABC-Sanitary-SSP-0000-0000-0000-0000.lic
```

### 3. How to issue a license to a new customer

1. Enter the customer/shop name, the exact Device ID shown in the POS activation screen, the license type, issue date, expiry date for trial keys, and the license ID.
2. Click Generate License or run the CLI with `--shop`, `--device-id`, `--type`, `--license-id`, and optional `--expiry-date`.
3. Send the resulting `.lic` file to the customer. The customer selects that file on the activation screen in the POS. The file is signed with the private key and the POS validates it with the public key embedded in the application.
4. For a device transfer, verify the customer's old and new Device IDs through your vendor support process, then issue a replacement license for the new Device ID. Customers cannot create a replacement license.

### 4. How the POS verifies the license

The POS does not use a private key. It only contains the public Ed25519 verification key in `sanitary_pos/licensing.py` and verifies the signature over the canonical JSON payload. The validation process checks:

- the signature matches the embedded public key
- the `product` field is `Sanitary Shop POS`
- the `device_id` matches the current device exactly
- the `license_type` is `LIFETIME` or `TRIAL`
- the trial expiry date is still valid when applicable

If any check fails, activation is rejected and the customer must obtain a valid license.

### 5. Safe private key storage and backup

Store the private key in a dedicated offline vault only accessible to the developer/vendor. For example:

- keep it outside the repository and outside the installer
- keep it on an encrypted developer workstation or encrypted USB drive
- maintain a backup in a secure, restricted-access location
- never include it in customer backups, `dist`, `build`, `installer.py`, or any shipped product package

Recommended backup pattern:

```
D:\vendor-keys\ssp-ed25519.privatekey
D:\vendor-keys\backup\ssp-ed25519.privatekey.2026-09-18
```

The customer POS should never receive the private key or the generator utility. Only the public key is embedded in the application.

For forgotten Owner PINs, the customer exports an owner recovery request. The vendor validates the shop and device details out of band, then follows its controlled support process. The customer POS deliberately has no universal reset password.

## Permissions

Permissions are persisted by role in SQLite. Owners always begin with full access. Manager and Cashier defaults can be changed by the Owner. Sensitive Store methods and UI entry points verify their permission; the controls are not merely hidden. Important business actions write a compact local audit record with date/time, user, action and reference, never a PIN.
