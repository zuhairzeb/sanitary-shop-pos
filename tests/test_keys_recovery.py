import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sanitary_pos.db import Store, UserError
from sanitary_pos import licensing, recovery
from developer_tools.license_generator import generate_license, sign_recovery


class KeyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'shop.sqlite3')
        self.key = Ed25519PrivateKey.generate()
        self.key_path = self.root / 'vendor.privatekey'
        self.key_path.write_bytes(self.key.private_bytes_raw())
        self.public = patch.object(licensing, 'PUBLIC_KEY_HEX', self.key.public_key().public_bytes_raw().hex())
        self.public.start()
        self.owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        self.staff = self.store.create_user('Staff', 'CASHIER', '5678', 'First shop?', 'green')

    def tearDown(self):
        self.public.stop()
        self.store.conn.close()
        self.temp.cleanup()

    def test_file_and_key_same_device_and_tamper_checks(self):
        path, payload = generate_license(self.key_path, 'Shop', self.store.device_id(), 'LIFETIME', 'TEST-1', self.root / 'test.lic')
        document = licensing.decode_key(path.with_suffix('.key.txt').read_text())
        self.assertEqual(licensing.validate_license(path, self.store.device_id()), licensing.validate_license(document, self.store.device_id()))
        with self.assertRaises(UserError): licensing.validate_license(document, 'OTHER-PC')
        document['license']['licensed_to'] = 'Tampered'
        with self.assertRaises(UserError): licensing.validate_license(document, self.store.device_id())

    def test_recovery_once_only_and_staff_denied(self):
        request = recovery.create_request(self.store, self.owner)
        key = sign_recovery(self.key_path, request)
        with self.assertRaises(UserError): recovery.apply_recovery(self.store, key[:-8] + 'INVALID!', '9999')
        recovery.apply_recovery(self.store, key, '9999')
        self.store.authenticate(self.owner, '9999')
        with self.assertRaises(UserError): recovery.apply_recovery(self.store, key, '1111')
        with self.assertRaises(UserError): recovery.create_request(self.store, self.staff)

    def test_recovery_wrong_device_expired_and_replaced(self):
        request = recovery.create_request(self.store, self.owner)
        key = sign_recovery(self.key_path, request)
        with patch.object(self.store, 'device_id', return_value='OTHER-PC'):
            with self.assertRaises(UserError): recovery.apply_recovery(self.store, key, '9999')
        recovery.create_request(self.store, self.owner)
        with self.assertRaises(UserError): recovery.apply_recovery(self.store, key, '9999')
        request['expires_at'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError): sign_recovery(self.key_path, request)

    def test_reset_and_change_own_pin(self):
        with self.assertRaises(UserError): self.store.reset_pin(self.owner, '9999')
        self.store.authenticate(self.staff, '5678')
        with self.assertRaises(UserError): self.store.reset_pin(self.owner, '9999')
        with self.assertRaises(UserError): self.store.change_own_pin('0000', '7777')
        self.store.change_own_pin('5678', '7777')
        self.store.authenticate(self.staff, '7777')
        self.store.logout()
        self.store.authenticate(self.owner, '1234')
        self.store.reset_pin(self.staff, '8888')
        self.store.authenticate(self.staff, '8888')
