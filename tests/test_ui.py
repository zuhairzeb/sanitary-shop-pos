"""Real Tk integration tests. Run on Windows with a desktop session."""
from pathlib import Path
import tempfile
import unittest
import app
from sanitary_pos.db import Store
from sanitary_pos.ui import App
from sanitary_pos.printing import preview, receipt_text


class WindowTests(unittest.TestCase):
    def test_scan_qr_uses_scanned_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.sqlite3'
            store = Store(path)
            pid = store.save_product(dict(name='Master Basin', code='BASIN001', category='Basin', brand='Master', purchase='4000', selling='4800', stock='10', unit='Piece'))
            window = App(store)
            try:
                window.update()
                for table in (window.cart_tree, window.product_tree, window.stock_tree, window.sale_tree):
                    for column in table['columns']:
                        self.assertEqual(str(table.column(column, 'anchor')), 'center')
                        self.assertEqual(str(table.heading(column, 'anchor')), 'center')
                window.product_search.set('not matching')
                window.select_all_products()
                self.assertEqual(window.product_tree.selection(), (str(pid),))
                window.scan_qr('BASIN001')
                self.assertEqual(len(window.cart), 1)
                self.assertEqual(window.cart[0]['id'], pid)
                self.assertEqual(window.cart[0]['qty'], 1000)
            finally:
                window.close()

    def test_scan_save_restart_and_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.sqlite3'
            store = Store(path)
            pid = store.save_product(dict(name='Master Basin', code='BASIN001', category='Basin', brand='Master', purchase='4000', selling='4800', stock='10', unit='Piece'))
            window = App(store)
            try:
                window.update()
                for dimensions in ('1180x780', '980x680'):
                    window.geometry(dimensions)
                    window.update()
                    self.assertTrue(window.complete_button.winfo_ismapped())
                    panel = window.complete_button.master
                    for control in panel.winfo_children():
                        self.assertLessEqual(control.winfo_y() + control.winfo_height(), panel.winfo_height())
                    self.assertLess(window.complete_button.winfo_rooty() + window.complete_button.winfo_height(), window.winfo_rooty() + window.winfo_height())
                for _ in range(2):
                    window.search.set('BASIN001')
                    window.enter_product()
                self.assertEqual(len(window.cart), 1)
                self.assertEqual(window.cart[0]['qty'], 2000)
                window.discount.set('100')
                window.paid.set('10000')
                window.complete(False)
                self.assertEqual(store.product(pid)['stock_milli'], 8000)
                text = receipt_text(store, 1)
                self.assertIn('TOTAL:', text)
                self.assertIn('9,500', text)
                self.assertIn('Change:', text)
                self.assertIn('500', text)
                receipt = preview(window, 'Receipt', text)
                receipt.update()
                receipt.destroy()
                label = preview(window, 'Label', 'Master Basin', 'BASIN001')
                label.update()
                label.destroy()
                window.add_product(pid)
            finally:
                window.close()
            store = Store(path)
            try:
                window = App(store)
                window.update()
                self.assertEqual(window.cart[0]['qty'], 1000)
                self.assertEqual(len(store.sales()), 1)
                self.assertEqual(store.product(pid)['stock_milli'], 8000)
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
