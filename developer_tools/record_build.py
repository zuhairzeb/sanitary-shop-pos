"""Record which source version produced the final installer."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sanitary_pos.version import APP_VERSION
from sanitary_pos.updater import UPDATE_MANIFEST_URL


def main():
    installer = ROOT / 'dist' / 'SanitaryShopPOS-Setup.exe'
    with installer.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    (installer.parent / 'release-build.json').write_text(json.dumps({
        'version': APP_VERSION, 'sha256': digest, 'manifest_url': UPDATE_MANIFEST_URL,
    }, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
