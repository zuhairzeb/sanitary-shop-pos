import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from sanitary_pos.db import Store


class ProductLocationTests(unittest.TestCase):
    def test_location_persists_searches_and_survives_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.sqlite3'
            store = Store(path)
            values = dict(name='Tap', code='002233', purchase='10', selling='20', stock='3', unit='Piece')
            try:
                pid = store.save_product(values | {'location': 'Godown B / Rack 12'})
                self.assertEqual(store.products('Rack 12')[0]['id'], pid)
                store.save_product(values, pid)
                self.assertEqual(store.product(pid)['location'], 'Godown B / Rack 12')
                backup = Path(folder) / 'backup.sqlite3'
                store.backup(backup)
                Store.validate_backup(backup)
                with closing(sqlite3.connect(backup)) as saved:
                    self.assertEqual(saved.execute('SELECT location FROM products').fetchone()[0], 'Godown B / Rack 12')
            finally:
                store.conn.close()
            store = Store(path)
            try:
                self.assertEqual(store.product(pid)['location'], 'Godown B / Rack 12')
                store.save_product(values | {'location': ''}, pid)
                self.assertEqual(store.product(pid)['location'], '')
            finally:
                store.conn.close()

    def test_version_8_migrates_without_losing_products(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.sqlite3'
            store = Store(path)
            pid = store.save_product(dict(name='Tap', code='002233', purchase='10', selling='20', stock='3', unit='Piece'))
            store.conn.execute('ALTER TABLE products DROP COLUMN location')
            store.conn.execute('PRAGMA user_version=8')
            store.conn.close()
            store = Store(path)
            try:
                self.assertEqual(store.product(pid)['location'], '')
                self.assertEqual(store.product(pid)['stock_milli'], 3000)
                self.assertTrue(list(Path(folder).glob('before-migration-*.sqlite3')))
            finally:
                store.conn.close()
