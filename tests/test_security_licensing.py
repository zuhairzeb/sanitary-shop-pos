import base64
import json
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.vendor'))

from developer_tools import license_generator

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from sanitary_pos.db import Store, UserError
from sanitary_pos import licensing
from sanitary_pos.security import PERMISSIONS


def signed_document(private_key, payload):
    signature = private_key.sign(licensing.canonical(payload))
    return json.dumps({'license': payload, 'signature': base64.b64encode(signature).decode('ascii')})


class SecurityAndLicensingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / 'shop.sqlite3')

    def tearDown(self):
        self.store.conn.close()
        self.temp.cleanup()

    def test_users_permissions_audit_and_pin_hashing(self):
        owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        self.store.authenticate(owner, '1234')
        cashier = self.store.create_user('Ali', 'CASHIER', '2345', 'First shop?', 'green')
        row = self.store.conn.execute('SELECT pin_salt,pin_hash FROM pos_users WHERE id=?', (cashier,)).fetchone()
        self.assertNotIn(b'2345', row['pin_salt'] + row['pin_hash'])
        self.store.authenticate(cashier, '2345')
        self.assertTrue(self.store.allowed('billing.create'))
        self.assertFalse(self.store.allowed('products.delete'))
        with self.assertRaises(UserError):
            self.store.archive(999)
        self.store.authenticate(owner, '1234')
        self.store.set_role_permissions('CASHIER', {permission: permission == 'sales.view' for permission in PERMISSIONS})
        self.store.authenticate(cashier, '2345')
        self.assertTrue(self.store.allowed('sales.view'))
        self.assertFalse(self.store.allowed('billing.create'))
        self.assertTrue(self.store.verify_owner_pin('1234'))
        self.assertFalse(self.store.verify_owner_pin('0000'))
        actions = [row['action'] for row in self.store.audit_history()]
        self.assertIn('Created user', actions)
        self.assertNotIn('2345', json.dumps([dict(row) for row in self.store.audit_history()]))

    def test_remove_user_deactivates_account_and_preserves_last_owner(self):
        owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        second_owner = self.store.create_user('Second Owner', 'OWNER', '5678', 'First shop?', 'yellow')
        cashier = self.store.create_user('Ali', 'CASHIER', '2345', 'First shop?', 'green')
        self.store.authenticate(owner, '1234')

        self.store.remove_user(cashier)
        self.assertEqual([dict(row) for row in self.store.users()], [dict(self.store.user(owner)), dict(self.store.user(second_owner))])
        with self.assertRaises(UserError):
            self.store.authenticate(cashier, '2345')
        self.store.remove_user(second_owner)
        with self.assertRaises(UserError):
            self.store.remove_user(owner)
        self.assertTrue(self.store.user(owner)['active'])

    def test_remove_user_cannot_remove_current_account(self):
        owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        self.store.authenticate(owner, '1234')
        with self.assertRaises(UserError):
            self.store.remove_user(owner)

    def test_security_answer_resets_pin(self):
        owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        self.store.reset_pin_with_answer(owner, 'BLUE', '9876')
        self.store.authenticate(owner, '9876')
        with self.assertRaises(UserError):
            self.store.reset_pin_with_answer(owner, 'wrong', '1111')

    def test_signed_device_bound_license_and_trial_clock_guard(self):
        private = Ed25519PrivateKey.generate()
        public_hex = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        device = self.store.device_id()
        payload = {'license_id':'SSP-2026-0001','licensed_to':'ABC Sanitary Store','device_id':device,
                   'license_type':'LIFETIME','issue_date':'2026-09-18','expiry_date':None,'product':'Sanitary Shop POS'}
        license_path = self.folder / 'license.json'
        license_path.write_text(signed_document(private, payload), encoding='utf-8')
        with patch.object(licensing, 'PUBLIC_KEY_HEX', public_hex):
            status = licensing.license_status(self.store, license_path)
            self.assertTrue(status['valid'])
            self.assertEqual(status['payload']['licensed_to'], 'ABC Sanitary Store')
            copied = self.folder / 'copied.json'
            payload['device_id'] = 'SSP-OTHER-DEVICE'
            copied.write_text(signed_document(private, payload), encoding='utf-8')
            self.assertFalse(licensing.license_status(self.store, copied)['valid'])
            license_path.write_text('{bad json', encoding='utf-8')
            self.assertFalse(licensing.license_status(self.store, license_path)['valid'])
        self.store.update_license_state(trial_started='2026-09-10', last_seen_date='2026-09-19')
        with patch('sanitary_pos.licensing.date') as clock:
            clock.today.return_value = date(2026, 9, 18)
            clock.fromisoformat = date.fromisoformat
            state = licensing.trial_status(self.store)
        self.assertFalse(state['valid'])

    def test_license_generator_module_can_emit_signed_lic_files(self):
        private = Ed25519PrivateKey.generate()
        key_path = self.folder / 'vendor-private.key'
        key_path.write_bytes(private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
        out = self.folder / 'sanitary-shop.lic'
        license_generator.generate_license(
            private_key_path=key_path,
            shop='Sanitary Shop',
            device_id=self.store.device_id(),
            license_type='LIFETIME',
            license_id='SSP-DEV-0001',
            output_path=out,
            issue_date='2026-09-18',
        )
        self.assertTrue(out.exists())
        public_hex = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        with patch.object(licensing, 'PUBLIC_KEY_HEX', public_hex):
            status = licensing.license_status(self.store, out)
            self.assertTrue(status['valid'])
            self.assertEqual(status['payload']['license_id'], 'SSP-DEV-0001')

    def test_backup_contains_users_but_not_license_file(self):
        owner = self.store.create_user('Owner', 'OWNER', '1234', 'First shop?', 'blue')
        self.store.authenticate(owner, '1234')
        backup = self.folder / 'backup.sqlite3'
        self.store.backup(backup)
        self.assertTrue(backup.exists())
        self.assertNotIn('license.json', backup.read_bytes().decode('latin1', 'ignore'))
