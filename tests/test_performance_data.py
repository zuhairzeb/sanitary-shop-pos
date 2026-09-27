import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch
from developer_tools.performance_data import prepare, generate, delete_generated, assert_development, launch_test_pos, ROOT
from sanitary_pos.db import Store, UserError


class DevelopmentDataTests(unittest.TestCase):
    def test_tool_is_not_a_customer_application_dependency(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn('performance_data', (root / 'app.py').read_text(encoding='utf-8'))
        self.assertNotIn('performance_data', (root / 'SanitaryShopPOS.spec').read_text(encoding='utf-8'))

    def test_real_products_and_drafts_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / 'live.sqlite3'
            store = Store(live)
            real = store.save_product(dict(name='Real Pipe',code='TEST-PVC-00001',category='Pipes',brand='Real',unit='Piece',purchase='10',selling='20',stock='5'))
            original = dict(store.product(real))
            store.conn.close()
            original_bytes = live.read_bytes()
            with self.assertRaises(UserError): assert_development(live)
            with self.assertRaises(UserError): generate(live,100)
            with self.assertRaises(UserError): delete_generated(live)
            target = prepare(Path(folder) / 'dev.sqlite3', live)
            generate(target,100)
            store = Store(target)
            self.assertEqual(len(store.products()),101)
            owned = store.conn.execute('SELECT product_id FROM dev_generated_products').fetchone()[0]
            store.save_draft({'cart':[{'id':owned}]})
            for row in store.products():
                if row['id'] == real: continue
                self.assertGreater(row['selling_paisa'],row['purchase_paisa'])
                self.assertTrue(0 <= row['stock_milli'] <= 500000)
                self.assertEqual(row['qr'],row['code'])
            store.conn.close()
            result = delete_generated(target)
            self.assertEqual(result,dict(deleted=99,skipped_in_bills=1))
            store = Store(target)
            self.assertEqual(dict(store.product(real)),original)
            store.save_draft({'cart':[]})
            store.conn.close()
            self.assertEqual(delete_generated(target)['deleted'],1)
            self.assertEqual(delete_generated(target)['deleted'],0)
            self.assertEqual(live.read_bytes(),original_bytes)

    def test_test_pos_launcher_uses_only_marked_database(self):
        with tempfile.TemporaryDirectory() as folder:
            target = prepare(Path(folder) / 'dev.sqlite3')
            with patch('developer_tools.performance_data.subprocess.Popen') as launch:
                launch_test_pos(target)
                args = launch.call_args.args[0]
                self.assertIn('--performance-test-db', args)
                self.assertEqual(args[args.index('--data-dir') + 1], str(target.resolve()))

    def test_performance_mode_is_source_only(self):
        source = Path(__file__).resolve().parents[1] / 'app.py'
        text = source.read_text(encoding='utf-8')
        self.assertIn("getattr(sys, 'frozen', False)", text)
        self.assertIn("args.data_dir if args.performance_test_db", text)
