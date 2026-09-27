import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanitary_pos.db import Store, UserError
from sanitary_pos import updater


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0
        self.headers = {'Content-Length': str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if self.offset >= len(self.payload):
            return b''
        end = min(len(self.payload), self.offset + (size if size > 0 else len(self.payload)))
        chunk = self.payload[self.offset:end]
        self.offset = end
        return chunk


class UpdateTests(unittest.TestCase):
    def test_manifest_requires_https_and_valid_hash(self):
        document = {
            'latest_version': '1.2.0',
            'download_url': 'https://updates.example.test/SanitaryShopPOS-Setup.exe',
            'sha256': hashlib.sha256(b'installer').hexdigest(),
            'release_notes': ['Improved receipts'],
        }
        self.assertEqual(updater.validate_manifest(document), document)
        with self.assertRaises(UserError):
            updater.validate_manifest(document | {'download_url': 'http://updates.example.test/app.exe'})
        with self.assertRaises(UserError):
            updater.validate_manifest(document | {'sha256': 'bad'})

    def test_download_rejects_wrong_hash_and_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'update.exe'
            target.write_bytes(b'current')
            manifest = {
                'latest_version': '1.2.0',
                'download_url': 'https://updates.example.test/app.exe',
                'sha256': hashlib.sha256(b'expected').hexdigest(),
                'release_notes': [],
            }
            with patch('sanitary_pos.updater.urllib.request.urlopen', return_value=FakeResponse(b'wrong')):
                with self.assertRaises(UserError):
                    updater.download_verified(manifest, target)
            self.assertEqual(target.read_bytes(), b'current')

    def test_owner_permission_is_only_update_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'shop.sqlite3')
            try:
                owner = store.create_user('Owner', 'OWNER', '1234', 'Shop?', 'blue')
                cashier = store.create_user('Cashier', 'CASHIER', '5678', 'Shop?', 'green')
                store.authenticate(cashier, '5678')
                self.assertFalse(store.allowed('software.update'))
                store.authenticate(owner, '1234')
                self.assertTrue(store.allowed('software.update'))
            finally:
                store.conn.close()


if __name__ == '__main__':
    unittest.main()
