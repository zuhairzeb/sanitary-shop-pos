"""Prepare an update manifest for an installer uploaded to HTTPS hosting."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sanitary_pos.updater import validate_manifest
from sanitary_pos.version import APP_VERSION


def prepare_update(installer, download_url, output, notes, version=APP_VERSION, private_key=None):
    installer = Path(installer)
    with installer.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest = validate_manifest({
        'latest_version': version,
        'download_url': download_url,
        'sha256': digest,
        'release_notes': notes,
    })
    if private_key is not None:
        from developer_tools.license_generator import load_private_key
        from sanitary_pos.updater import UPDATE_MANIFEST_PUBLIC_KEY_HEX
        key = load_private_key(private_key)
        if key.public_key().public_bytes_raw().hex() != UPDATE_MANIFEST_PUBLIC_KEY_HEX:
            raise ValueError('The signing key does not match the public key trusted by the POS.')
        signature = key.sign(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        manifest['signature'] = base64.b64encode(signature).decode('ascii')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', default='dist/SanitaryShopPOS-Setup.exe')
    parser.add_argument('--download-url', required=True)
    parser.add_argument('--out', default='dist/update.json')
    parser.add_argument('--note', action='append', default=[])
    parser.add_argument('--private-key', help='Vendor-only Ed25519 signing key')
    args = parser.parse_args()
    prepare_update(args.installer, args.download_url, args.out, args.note, private_key=args.private_key)
    print(f'Update manifest saved: {args.out}')
    print('Upload the installer first, then publish this manifest at the configured update URL.')


if __name__ == '__main__':
    main()
