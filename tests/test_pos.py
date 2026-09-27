import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import installer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.vendor'))
from sanitary_pos.db import Store, UserError, scaled, line_total
from sanitary_pos.receipts import write_receipt, write_label


class PosTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path / 'shop.sqlite3')
        self.values = dict(name='PVC Pipe',code='P-01',qr='',category='Pipes',brand='Master',purchase='80',selling='125.50',stock='10',unit='Meter',description='')
        self.pid = self.store.save_product(self.values)

    def tearDown(self):
        self.store.conn.close()
        self.temp.cleanup()

    def cart(self, qty=1000):
        return [{'id':self.pid,'qty':qty,'price':12550}]

    def test_installer_source_falls_back_to_repo_bundle(self):
        candidate = installer.resolve_payload_source()
        self.assertTrue(candidate.exists())
        self.assertTrue((candidate / 'SanitaryShopPOS.exe').exists())

    def test_source_installer_copies_setup_not_python(self):
        base = self.path / 'source'
        bundle = base / 'dist' / 'SanitaryShopPOS'
        bundle.mkdir(parents=True)
        (bundle / 'SanitaryShopPOS.exe').write_bytes(b'app')
        (base / 'dist' / 'SanitaryShopPOS-Setup.exe').write_bytes(b'setup')
        destination = self.path / 'installed'
        with patch.object(installer, '__file__', str(base / 'installer.py')), patch.object(installer.sys, 'frozen', False, create=True):
            installer.copy_application(destination)
        self.assertEqual((destination / 'Uninstall.exe').read_bytes(), b'setup')
        self.assertEqual((destination / 'SanitaryShopPOS.exe').read_bytes(), b'app')

    def test_search_and_exact_scan(self):
        for query in ('p','PIPE','master','p-01','Pipes'):
            self.assertEqual(len(self.store.products(query)),1)
        self.assertEqual(self.store.exact('p-01')['id'],self.pid)
        self.assertEqual(self.store.products('%'),[])

    def test_sale_money_stock_and_idempotence(self):
        sale_id=self.store.complete_sale(self.cart(2500),'13.75','400','unique')
        sale,items=self.store.sale(sale_id)
        self.assertEqual(sale['subtotal_paisa'],31375)
        self.assertEqual(sale['total_paisa'],30000)
        self.assertEqual(self.store.product(self.pid)['stock_milli'],7500)
        self.assertEqual(self.store.complete_sale(self.cart(2500),'13.75','400','unique'),sale_id)
        self.assertEqual(self.store.product(self.pid)['stock_milli'],7500)
        self.assertEqual(len(items),1)

    def test_percentage_discount(self):
        sale_id = self.store.complete_sale(self.cart(), '10', '', 'percentage-sale', discount_mode='percent')
        sale, _ = self.store.sale(sale_id)
        self.assertEqual((sale['subtotal_paisa'], sale['discount_paisa'], sale['total_paisa']), (12550, 1255, 11295))
        with self.assertRaises(UserError):
            self.store.complete_sale(self.cart(), '100.01', '', 'invalid-percentage', discount_mode='percent')

    def test_stock_failure_rolls_back_whole_sale(self):
        second=self.store.save_product(self.values | {'code':'P-02','qr':'','stock':'1'})
        cart=self.cart()+[{'id':second,'qty':2000,'price':100}]
        with self.assertRaises(UserError):
            self.store.complete_sale(cart,'0','','x')
        self.assertEqual(self.store.product(self.pid)['stock_milli'],10000)
        self.assertEqual(self.store.sales(),[])

    def test_database_failure_rolls_back(self):
        self.store.conn.execute("CREATE TRIGGER fail_stock BEFORE UPDATE OF stock_milli ON products BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.complete_sale(self.cart(),'0','','x')
        self.assertEqual(self.store.sales(),[])
        self.assertEqual(self.store.product(self.pid)['stock_milli'],10000)

    def test_invalid_numbers_and_discounts(self):
        for value in ('-1','NaN','Infinity','1.234','garbage'):
            with self.assertRaises(UserError):
                scaled(value)
        self.assertEqual(line_total(101,500),51)
        with self.assertRaises(UserError):
            self.store.complete_sale(self.cart(),'200','','x')
        with self.assertRaises(UserError):
            self.store.complete_sale(self.cart()+self.cart(),'0','','x')

    def test_draft_recovery_and_clear(self):
        draft={'cart':self.cart(),'discount':'0','paid':'','token':'x'}
        self.store.save_draft(draft)
        other=Store(self.store.path)
        self.assertEqual(other.load_draft(),draft)
        other.conn.close()
        self.store.complete_sale(self.cart(),'0','','x')
        self.assertEqual(self.store.load_draft()['cart'],[])

    def test_history_snapshots_and_archive(self):
        sale_id=self.store.complete_sale(self.cart(),'0','50','x')
        self.store.save_product(self.values | {'name':'Renamed','selling':'900'},self.pid)
        self.store.archive(self.pid)
        sale,items=self.store.sale(sale_id)
        self.assertEqual(items[0]['name'],'PVC Pipe')
        self.assertEqual(items[0]['price_paisa'],12550)
        self.assertEqual(sale['paid_paisa'],5000)
        self.assertEqual(self.store.products(),[])
        self.assertEqual(len(self.store.sales('000001',sale['created_at'][:10])),1)

    def test_backup_restore_and_safety_copy(self):
        backup=self.path/'backup.sqlite3'
        self.store.backup(backup)
        self.store.adjust_stock(self.pid,'2',False,'Damaged')
        safety=self.store.restore(backup)
        self.assertEqual(self.store.product(self.pid)['stock_milli'],10000)
        with closing(sqlite3.connect(safety)) as c:
            self.assertEqual(c.execute('SELECT stock_milli FROM products').fetchone()[0],8000)
        bad=self.path/'bad.sqlite3'
        bad.write_text('not a database')
        with self.assertRaises(UserError):
            self.store.restore(bad)
        self.assertEqual(self.store.product(self.pid)['stock_milli'],10000)

    def test_duplicate_scan_identity_prevented(self):
        with self.assertRaises(UserError):
            self.store.save_product(self.values | {'code':'P-02','qr':'p-01'})
        with self.assertRaises(UserError):
            self.store.save_product(self.values | {'code':'p-01'})

    def test_stock_adjustment_validation(self):
        with self.assertRaises(UserError):
            self.store.adjust_stock(self.pid,'11',False,'Correction')
        self.store.adjust_stock(self.pid,'0.125',True,'Delivery')
        self.assertEqual(self.store.product(self.pid)['stock_milli'],10125)

    def test_receipt_and_qr_are_local_and_escaped(self):
        self.store.save_settings(self.store.settings() | {'shop_name':'Shop <script>'})
        sale_id=self.store.complete_sale(self.cart(),'0','','x')
        html=write_receipt(self.store,sale_id,self.path).read_text(encoding='utf-8')
        self.assertIn('Shop &lt;script&gt;',html)
        self.assertNotIn('src="http',html)
        self.assertIn('Bill #000001',html)
        label=write_label(self.store.product(self.pid),self.path).read_text(encoding='utf-8')
        self.assertIn('<svg',label)

    def test_variants_gst_and_historical_sale_snapshot(self):
        variants = []
        for size, code, price, stock in (('1 inch', 'GP-001', '400', '100'), ('2 inch', 'GP-002', '650', '60'), ('3 inch', 'GP-003', '900', '30')):
            variants.append(self.store.save_product(self.values | {'name': 'Gas Pipe', 'code': code, 'qr': code + '-QR', 'size_variant': size, 'selling': price, 'stock': stock}))
        self.assertEqual(len(self.store.products('Gas Pipe 2')), 1)
        self.store.save_settings(self.store.settings() | {'tax_enabled': 'On', 'gst_rate': '18', 'tax_label': 'GST'})
        sale_id = self.store.complete_sale([{'id': variants[1], 'qty': 2000, 'price': 65000}], '100', '1500', 'gst-sale')
        sale, items = self.store.sale(sale_id)
        self.assertEqual((sale['subtotal_paisa'], sale['taxable_paisa'], sale['gst_paisa'], sale['total_paisa'], sale['change_paisa']), (130000, 120000, 21600, 141600, 8400))
        self.assertEqual((items[0]['size_variant'], self.store.product(variants[1])['stock_milli']), ('2 inch', 58000))
        text = __import__('sanitary_pos.printing', fromlist=['receipt_text']).receipt_text(self.store, sale_id)
        self.assertIn('2 inch', text)
        self.assertIn('GST (18%)', text)
        self.assertIn('Change Returned', text)
        self.store.save_settings(self.store.settings() | {'gst_rate': '5'})
        self.assertEqual(self.store.sale(sale_id)[0]['gst_rate_bps'], 1800)


if __name__=='__main__':
    unittest.main()
