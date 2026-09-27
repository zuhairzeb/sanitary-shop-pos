import tempfile
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path
from sanitary_pos.db import Store, UserError
from sanitary_pos.return_ui import return_text


class ReturnTests(unittest.TestCase):
    def test_partial_full_duplicate_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'shop.sqlite3')
            try:
                owner=store.create_user('Owner','OWNER','1234','First school?','Example')
                store.authenticate(owner,'1234')
                pid=store.save_product(dict(name='Pipe',code='P1',category='Pipes',brand='Test',unit='Piece',purchase='50',selling='100',stock='10'))
                sid=store.complete_sale([dict(id=pid,qty=3000,price=10000)],'10','290',str(uuid.uuid4()))
                item=store.sale(sid)[1][0]['id']
                token=str(uuid.uuid4())
                rid=store.return_sale(sid,{item:{'quantity':'1','to_stock':True}},token,'Customer Return','Cash')
                self.assertEqual(store.product(pid)['stock_milli'],8000)
                self.assertEqual(store.return_sale(sid,{item:{'quantity':'1','to_stock':True}},token,'Customer Return','Cash'),rid)
                self.assertEqual(store.product(pid)['stock_milli'],8000)
                with self.assertRaises(UserError): store.return_sale(sid,{item:{'quantity':'3','to_stock':True}},str(uuid.uuid4()))
                damaged=store.return_sale(sid,{item:{'quantity':'1','to_stock':False}},str(uuid.uuid4()),'Damaged / Defective','Other / Original Method')
                self.assertEqual(store.product(pid)['stock_milli'],8000)
                store.return_sale(sid,{item:{'quantity':'1','to_stock':True}},str(uuid.uuid4()))
                self.assertEqual(store.product(pid)['stock_milli'],9000)
                self.assertEqual(store.conn.execute('SELECT sum(total_paisa) FROM sale_returns').fetchone()[0],29000)
                self.assertIn('RETURN RECEIPT',return_text(store,rid))
                record, rows = store.return_record(damaged)
                self.assertEqual(record['refund_method'],'Other / Original Method')
                self.assertEqual(rows[0]['returned_to_stock'],0)
                self.assertEqual(store.sale_return_status(sid),'FULLY RETURNED')
                with self.assertRaises(UserError): store.return_sale(sid,{item:{'quantity':'1','to_stock':True}},str(uuid.uuid4()))
                backup=Path(folder)/'backup.sqlite3';store.backup(backup);Store.validate_backup(backup)
                store.restore(backup)
                self.assertEqual(store.product(pid)['stock_milli'],9000)
                store.logout()
                with self.assertRaises(UserError): store.return_sale(sid,{item:{'quantity':'1','to_stock':True}},str(uuid.uuid4()))
            finally: store.conn.close()

    def test_multi_item_discount_gst_price_change_permission_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder)/'shop.sqlite3')
            try:
                owner = store.create_user('Owner','OWNER','1234','First school?','Example')
                cashier = store.create_user('Cashier','CASHIER','5678','First school?','Example')
                store.authenticate(owner,'1234')
                a = store.save_product(dict(name='Original Pipe',code='A',category='Pipes',brand='Test',unit='Piece',purchase='10',selling='100',stock='10'))
                b = store.save_product(dict(name='Original Mixer',code='B',category='Faucets',brand='Test',unit='Piece',purchase='10',selling='200',stock='10'))
                store.save_settings(store.settings() | {'tax_enabled':'On','gst_rate':'10'})
                sale = store.complete_sale([dict(id=a,qty=2000,price=10000),dict(id=b,qty=1000,price=20000)],'30','297',str(uuid.uuid4()),'Ali','03000000000')
                sale_row, lines = store.sale(sale)
                self.assertEqual(sale_row['total_paisa'],40700)
                store.save_product(dict(name='Changed price',code='A',category='Pipes',brand='Test',unit='Piece',purchase='10',selling='999',stock='8'),a)
                quote_sale, quote, refund = store.return_quote(sale,{lines[0]['id']:'1',lines[1]['id']:'1'})
                self.assertEqual(quote_sale['id'],sale)
                self.assertEqual(refund,22275)  # original total allocation, not Rs. 999 current price
                store.logout(); store.authenticate(cashier,'5678')
                with self.assertRaises(UserError): store.return_sale(sale,{lines[0]['id']:'1'},str(uuid.uuid4()))
                store.logout(); store.authenticate(owner,'1234')
                before_stock = store.product(a)['stock_milli']
                with patch.object(store, '_movement', side_effect=RuntimeError('disk error')):
                    with self.assertRaises(RuntimeError): store.return_sale(sale,{lines[0]['id']:{'quantity':'1','to_stock':True}},str(uuid.uuid4()))
                self.assertEqual(store.product(a)['stock_milli'],before_stock)
                self.assertEqual(store.conn.execute('SELECT count(*) FROM sale_returns').fetchone()[0],0)
                rid = store.return_sale(sale,{lines[0]['id']:{'quantity':'1','to_stock':True},lines[1]['id']:{'quantity':'1','to_stock':False}},str(uuid.uuid4()),'Customer Return','Cash')
                self.assertEqual(store.return_record(rid)[0]['return_number'],f'RET-{rid:06d}')
                self.assertEqual(store.sale_return_status(sale),'PARTIALLY RETURNED')
                self.assertEqual([r['id'] for r in store.sales(customer='Ali')],[sale])
                self.assertEqual([r['id'] for r in store.returns(customer='03000000000')],[rid])
                gross, returns, net = store.sales_totals()
                self.assertEqual((gross,returns,net),(40700,22275,18425))
            finally: store.conn.close()
