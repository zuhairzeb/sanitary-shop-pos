import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

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
    def test_failed_check_reaches_ui_callback(self):
        from sanitary_pos.ui import App
        window = Mock()
        window._closed = False
        callback = Mock()
        error = UserError('No internet connection.')
        with patch.object(updater, 'fetch_manifest', side_effect=error):
            App._check_updates_worker(window, True, callback)
        window.after.assert_any_call(0, callback, None, error)

    def test_download_schedules_install_on_main_thread(self):
        from sanitary_pos.ui import App
        window = Mock()
        status = Mock()
        with patch.object(updater, 'download_verified', return_value=Path('update.exe')), patch.object(updater, 'verify_windows_signature'), patch.object(updater, 'update_backup') as backup:
            App._download_update_worker(window, {}, Mock(), status, Mock())
        backup.assert_not_called()
        window.after.assert_called_once_with(0, window._install_downloaded_update, Path('update.exe'), status)

    def test_fetch_uses_configured_endpoint_and_reports_offline_error(self):
        document = {'latest_version': '1.2.5', 'download_url': 'https://example.test/app.exe',
                    'sha256': hashlib.sha256(b'installer').hexdigest(), 'release_notes': []}
        with patch.object(updater, 'UPDATE_MANIFEST_URL', 'https://example.test/update.json'), patch.object(updater, 'UPDATE_MANIFEST_PUBLIC_KEY_HEX', ''):
            with patch.object(updater.urllib.request, 'urlopen', return_value=FakeResponse(json.dumps(document).encode())) as request:
                self.assertEqual(updater.fetch_manifest(), document)
                self.assertEqual(request.call_args.args[0].full_url, 'https://example.test/update.json')
            with patch.object(updater.urllib.request, 'urlopen', side_effect=OSError('offline')):
                with self.assertRaisesRegex(UserError, 'No internet'):
                    updater.fetch_manifest()

    def test_prepare_update_hashes_final_installer(self):
        from developer_tools.prepare_update import prepare_update
        with tempfile.TemporaryDirectory() as folder:
            installer = Path(folder) / 'setup.exe'
            installer.write_bytes(b'final installer')
            output = Path(folder) / 'update.json'
            result = prepare_update(installer, 'https://example.test/setup.exe', output, ['QR preview fixed'])
            self.assertEqual(result['sha256'], hashlib.sha256(installer.read_bytes()).hexdigest())
            self.assertEqual(json.loads(output.read_text()), result)

    def test_signed_manifest_rejects_tampering_and_unsigned_updates(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from developer_tools.prepare_update import prepare_update
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            key = Ed25519PrivateKey.generate()
            private = folder / 'signing.key'
            private.write_bytes(key.private_bytes_raw())
            installer = folder / 'setup.exe'
            installer.write_bytes(b'installer')
            with patch.object(updater, 'UPDATE_MANIFEST_PUBLIC_KEY_HEX', key.public_key().public_bytes_raw().hex()):
                manifest = prepare_update(installer, 'https://example.test/setup.exe', folder / 'update.json', [], private_key=private)
                updater._verify_manifest_signature(manifest)
                with self.assertRaises(UserError):
                    updater._verify_manifest_signature(manifest | {'latest_version': '9.9.9'})
                with self.assertRaises(UserError):
                    updater._verify_manifest_signature({k: v for k, v in manifest.items() if k != 'signature'})

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
