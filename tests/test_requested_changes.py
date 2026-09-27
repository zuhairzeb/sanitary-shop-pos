import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import app
from PIL import Image
from pypdf import PdfReader
from sanitary_pos.db import Store, UserError
from sanitary_pos.labels import export_labels, qr_matrix, QR_MM
from sanitary_pos.logos import encode_logo
from sanitary_pos.printing import _save_pdf


class RequestedChangesTests(unittest.TestCase):
    def test_delete_all_products_keeps_previous_bills_and_stock_records(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'shop.sqlite3')
            try:
                first = store.save_product(dict(name='Pipe', code='P1', purchase='50', selling='100', stock='10', unit='Piece'))
                second = store.save_product(dict(name='Tap', code='T1', purchase='80', selling='150', stock='8', unit='Piece'))
                sale = store.complete_sale([{'id': first, 'qty': 1000, 'price': 10000}], '0', '', 'delete-all-products')
                stock_after_sale = store.product(first)['stock_milli']
                self.assertEqual(store.archive_all_products(), 2)
                self.assertEqual(store.products(), [])
                self.assertEqual(store.conn.execute('SELECT stock_milli FROM products WHERE id=?', (first,)).fetchone()[0], stock_after_sale)
                self.assertEqual(store.sale(sale)[0]['id'], sale)
                self.assertEqual(store.conn.execute('SELECT active FROM products WHERE id=?', (second,)).fetchone()[0], 0)
            finally:
                store.conn.close()

    def test_delete_history_keeps_stock_and_bill_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'shop.sqlite3')
            try:
                pid = store.save_product(dict(name='Pipe', code='P1', purchase='50', selling='100', stock='10', unit='Piece'))
                cart = [{'id':pid, 'qty':1000, 'price':10000}]
                first = store.complete_sale(cart, '0', '', 'one')
                second = store.complete_sale(cart, '0', '', 'two')
                stock = store.product(pid)['stock_milli']
                safety = store.delete_sales([first])
                self.assertTrue(safety.exists())
                self.assertEqual(len(store.sales()), 1)
                self.assertEqual(store.today_total(), 10000)
                self.assertEqual(store.product(pid)['stock_milli'], stock)
                with self.assertRaises(UserError):
                    store.delete_sales([second, 9999])
                self.assertIsNotNone(store.sale(second)[0])
                store.delete_sales()
                self.assertEqual(store.sales(), [])
                self.assertEqual(store.today_total(), 0)
                self.assertEqual(store.product(pid)['stock_milli'], stock)
                self.assertEqual(store.next_sale_number(), 3)
                self.assertEqual(store.complete_sale(cart, '0', '', 'three'), 3)
                self.assertEqual(store.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
            finally:
                store.conn.close()

    def test_label_pdf_contains_every_code_and_fixed_module_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'labels.pdf'
            products = [{'code': f'PIPE{i:03}', 'qr':f'PIPE{i:03}'} for i in range(55)]
            self.assertEqual(export_labels(products, path), 55)
            pdf = PdfReader(path)
            self.assertEqual(len(pdf.pages), 2)
            text = ''.join(p.extract_text() for p in pdf.pages)
            for p in products:
                self.assertIn(p['code'], text)
            matrix = qr_matrix('PIPE000')
            self.assertEqual(QR_MM, 20)
            # Every vector square has the exact module width for a 20 mm symbol.
            expected = 20*72/25.4/len(matrix)
            rectangles = [args for args, op in pdf.pages[0].get_contents().operations if op == b're']
            self.assertAlmostEqual(float(rectangles[0][2]), expected, places=5)

    def test_logo_backup_and_receipt_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            Image.new('RGB', (200, 100), '#176b67').save(path/'logo.jpg')
            logo = encode_logo(path/'logo.jpg')
            self.assertEqual(Image.open(BytesIO(base64.b64decode(logo))).format, 'PNG')
            store = Store(path/'shop.sqlite3')
            try:
                store.save_settings(store.settings() | {'shop_logo': logo})
                store.backup(path/'backup.sqlite3')
                store.save_settings(store.settings() | {'shop_logo': ''})
                store.restore(path/'backup.sqlite3')
                self.assertEqual(store.settings()['shop_logo'], logo)
                _save_pdf('Test Shop\nTOTAL: 100', path/'receipt.pdf', '80mm', logo)
                pdf = PdfReader(path/'receipt.pdf')
                self.assertEqual(len(pdf.pages[0].images), 1)
                self.assertIn('TOTAL: 100', pdf.pages[0].extract_text())
            finally:
                store.conn.close()
