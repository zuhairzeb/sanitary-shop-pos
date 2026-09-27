"""Vendor workstation only. Never imported by the customer application.

Always works on a marked development database, optionally cloned from shop data.
"""
import argparse
import json
import random
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app  # configures the bundled local Python/Tk dependencies
from sanitary_pos.db import Store, UserError

WORK = ROOT / '.performance-data'
COUNTS = (100, 500, 1000, 1500, 5000)
BRANDS = ('Test AquaForge', 'Test FlowNest', 'Test PipeVale', 'Test ClearBrook', 'Test BasinCraft')
SIZES = ('1/2 inch', '3/4 inch', '1 inch', '1.25 inch', '1.5 inch', '2 inch', '3 inch', '4 inch')
CATALOG = (
    ('PVC Pipe','PVC','Pipes',120,1800), ('PPR Pipe','PPR','Pipes',180,2400),
    ('UPVC Pipe','UPV','Pipes',250,3200), ('Elbow','ELB','Fittings',30,600),
    ('Tee','TEE','Fittings',50,800), ('Socket','SOC','Fittings',20,450),
    ('Union','UNI','Fittings',80,1200), ('Valve','VAL','Valves',300,4000),
    ('Gate Valve','GAT','Valves',400,6000), ('Ball Valve','BAL','Valves',250,4000),
    ('Basin Mixer','BMX','Faucets',2500,18000), ('Kitchen Mixer','KMX','Kitchen',3000,22000),
    ('Shower','SHW','Bathroom',600,7000), ('Tap','TAP','Faucets',300,5000),
    ('Floor Drain','DRN','Drainage',150,1800), ('Water Tank Fitting','WTF','Accessories',100,1500),
    ('Flexible Pipe','FLX','Pipes',150,1500), ('Waste Pipe','WST','Drainage',80,900),
    ('Bottle Trap','BTR','Drainage',400,3500), ('Basin','BSN','Bathroom',3000,25000),
    ('Commode','COM','Bathroom',7000,60000), ('Flush Tank','FLT','Bathroom',2000,12000),
    ('Shower Set','SHS','Bathroom',1500,15000), ('Pipe Clamp','CLP','Accessories',20,350),
    ('Nipple','NIP','Fittings',30,800), ('Reducer','RED','Fittings',50,1200),
    ('Coupler','CPL','Fittings',30,900),
)


def prepare(path, source=None):
    path = Path(path).resolve()
    if path.exists():
        assert_development(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if source:
        source = Path(source).resolve()
        if source == path: raise UserError('Choose a separate development copy.')
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(path)) as destination:
                original.backup(destination)
    store = Store(path)
    try:
        store.conn.executescript('''
            CREATE TABLE dev_performance_marker (value TEXT NOT NULL);
            INSERT INTO dev_performance_marker VALUES ('sanitary-pos-performance-v1');
            CREATE TABLE dev_generated_products (
                product_id INTEGER PRIMARY KEY, code TEXT NOT NULL, marker TEXT NOT NULL);
        ''')
    finally:
        store.conn.close()
    return path


def assert_development(path):
    try:
        with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as conn:
            marker = conn.execute('SELECT value FROM dev_performance_marker').fetchone()
            if not marker or marker[0] != 'sanitary-pos-performance-v1': raise ValueError()
    except (sqlite3.Error, ValueError):
        raise UserError('This is not a marked development copy. Live databases cannot be seeded.') from None


def launch_test_pos(path):
    path = Path(path).resolve()
    assert_development(path)
    if not path.is_file():
        raise UserError('Create test products before launching the POS.')
    return subprocess.Popen([sys.executable, str(ROOT / 'app.py'), '--data-dir', str(path), '--performance-test-db'])


def generate(path, count, progress=lambda value: None):
    assert_development(path)
    if count not in COUNTS: raise UserError('Choose 100, 500, 1000, 1500 or 5000 products.')
    store = Store(path)
    rng = random.Random(1500)
    run = uuid.uuid4().hex[:12].upper()
    try:
        for index in range(count):
            name, prefix, category, low, high = CATALOG[index % len(CATALOG)]
            variant = rng.choice(SIZES if category in ('Pipes','Fittings','Valves') else ('Small','Medium','Large','Chrome','White'))
            units = ('Meter','Feet','Roll') if category == 'Pipes' else ('Piece','Box','Pair') if category in ('Fittings','Accessories') else ('Piece','Set')
            purchase = rng.randint(low, high)
            marker = 'DEVELOPMENT TEST DATA ' + run
            code = f'TEST-{prefix}-{run}-{index + 1:05d}'
            product_id = store.save_product(dict(name=f'[TEST] {name} {variant}', code=code,
                category=category, brand=rng.choice(BRANDS), size_variant=variant, unit=rng.choice(units),
                purchase=str(purchase), selling=str(purchase + max(10, purchase * rng.randint(15,45) // 100)),
                stock=str(rng.randint(0,500)), description=marker))
            with store.conn:
                store.conn.execute('INSERT INTO dev_generated_products VALUES (?,?,?)', (product_id,code,marker))
            if index % 50 == 0: progress(index + 1)
        progress(count)
    finally:
        store.conn.close()


def delete_generated(path):
    assert_development(path)
    store = Store(path)
    deleted = skipped = 0
    try:
        draft_ids = {p['id'] for p in store.load_draft().get('cart', [])}
        with store.conn:
            for row in store.conn.execute('''SELECT p.id FROM products p JOIN dev_generated_products d
                    ON p.id=d.product_id AND p.code=d.code AND p.description=d.marker''').fetchall():
                pid = row['id']
                if pid in draft_ids or store.conn.execute('SELECT 1 FROM sale_items WHERE product_id=?', (pid,)).fetchone() or store.conn.execute('SELECT 1 FROM return_items WHERE product_id=?', (pid,)).fetchone():
                    skipped += 1
                    continue
                store.conn.execute('DELETE FROM product_images WHERE product_id=?', (pid,))
                store.conn.execute('DELETE FROM stock_movements WHERE product_id=?', (pid,))
                store.conn.execute('DELETE FROM products WHERE id=?', (pid,))
                store.conn.execute('DELETE FROM dev_generated_products WHERE product_id=?', (pid,))
                deleted += 1
        return dict(deleted=deleted, skipped_in_bills=skipped)
    finally:
        store.conn.close()


def benchmark(path):
    from sanitary_pos.ui import App
    assert_development(path)
    store = Store(path)
    results = {}
    def measure(label, action, repetitions=5):
        samples = []
        for _ in range(repetitions):
            start = time.perf_counter()
            action()
            samples.append(round((time.perf_counter()-start)*1000, 3))
        results[label] = dict(mean_ms=round(sum(samples)/len(samples),3), max_ms=max(samples))
    sample = store.conn.execute('SELECT p.* FROM products p JOIN dev_generated_products d ON d.product_id=p.id WHERE p.stock_milli>0 LIMIT 1').fetchone()
    # Keep the benchmark deterministic and offline; it must measure POS UI work,
    # not the production update-check worker.
    store.save_settings(store.settings() | {'update_auto_check': 'Off'})
    results['product_count'] = len(store.products())
    measure('database_all_products', store.products)
    for label, query in [('name','PVC Pipe'),('sku',sample['code']),('category','Fittings'),('brand',BRANDS[0]),('size','1/2 inch')]:
        measure('database_search_' + label, lambda q=query: store.products(q))
    measure('exact_qr_sku_lookup', lambda: store.exact(sample['qr']))
    # Exercise real UI methods on the isolated copy without bypassing licensing
    # or permission checks in the shipped app; no shop accounts are modified.
    store.save_settings(store.settings() | {'update_auto_check': 'Off'})
    window = App(store)
    previous_draft = store.load_draft()
    try:
        window.update()
        def settle():
            window.update()
            while getattr(window, '_table_jobs', {}):
                time.sleep(0.002); window.update()
        measure('products_page_first_batch', lambda: window.refresh_products())
        measure('stock_page_first_batch', lambda: window.refresh_inventory())
        measure('products_page_refresh', lambda: (window.show_page('Products'),window.refresh_products(), settle()))
        measure('stock_page_refresh', lambda: (window.show_page('Stock'),window.refresh_inventory(), settle()))
        measure('sales_refresh', lambda: (window.show_page('Sales'),window.refresh_sales(), window.update()))
        window.show_page('Products'); window.update()
        measure('product_scrolling', lambda: (window.product_tree.yview_moveto(1),window.update(),window.product_tree.yview_moveto(0),window.update()))
        window.show_page('Billing'); window.update()
        for label, query in [('name','PVC Pipe'),('sku',sample['code']),('category','Fittings'),('brand',BRANDS[0]),('size','1/2 inch')]:
            measure('billing_search_' + label, lambda q=query: (window.search.set(q),window.update()))
        window.new_bill()
        measure('add_to_bill', lambda: (window.add_product(sample['id']),window.update()), 1)
        measure('billing_refresh', lambda: (window.refresh_cart(),window.update()))
        values = dict(sample)
        values.update(purchase=str(sample['purchase_paisa']/100), selling=str(sample['selling_paisa']/100), stock=str(sample['stock_milli']/1000))
        measure('edit_generated_product', lambda: store.save_product(values, sample['id']), 1)
    finally:
        window.close()
        restore = Store(path)
        restore.save_draft(previous_draft)
        restore.conn.close()
    return results


def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import threading
    import queue
    root = tk.Tk()
    root.title('Developer Tools — Performance Test Data')
    root.geometry('700x480')
    pane = ttk.Frame(root, padding=24); pane.pack(fill='both', expand=True)
    ttk.Label(pane, text='Performance Test Data', font=('Segoe UI',20,'bold')).pack(anchor='w')
    ttk.Label(pane, text='Development only. Works on a separate test copy; never select this database in the customer POS.', wraplength=630).pack(anchor='w', pady=12)
    database = tk.StringVar(value=str(WORK / 'interactive.sqlite3'))
    ttk.Entry(pane,textvariable=database,state='readonly').pack(fill='x')
    status = tk.StringVar(value='Ready. Create a blank test database or copy an existing shop.')
    controls = []
    def copy_source():
        source = filedialog.askopenfilename(title='Choose source database (read-only copy)',filetypes=[('SQLite','*.sqlite3 *.db')])
        if source:
            target = WORK / (uuid.uuid4().hex + '.sqlite3')
            prepare(target,source)
            database.set(str(target))
            status.set('Development copy ready.')
    controls.append(ttk.Button(pane,text='Copy existing database for testing',command=copy_source)); controls[-1].pack(fill='x',pady=10)
    count = tk.IntVar(value=1500)
    options = ttk.Frame(pane); options.pack(fill='x')
    for number in COUNTS:
        ttk.Radiobutton(options,text=str(number),value=number,variable=count).pack(side='left',padx=8)
    messages = queue.Queue()
    def run(deleting=False):
        target, number = Path(database.get()), count.get()
        if deleting and not messagebox.askyesno('Delete test products?', 'Delete only tracked generator products? Products referenced by bills will be kept.'): return
        for button in controls: button.configure(state='disabled')
        status.set('Working…')
        def worker():
            try:
                prepare(target)
                result = delete_generated(target) if deleting else generate(target,number,lambda n: messages.put(('progress', f'Created {n} / {number}')))
                messages.put(('done', str(result) if deleting else f'{number} test products created.'))
            except Exception as error: messages.put(('done', str(error)))
        threading.Thread(target=worker,daemon=True).start()
    for title, action in [('Generate Test Products',lambda:run()), ('Delete Test Products',lambda:run(True))]:
        controls.append(ttk.Button(pane,text=title,command=action)); controls[-1].pack(fill='x',pady=8)
    def launch_pos():
        target = Path(database.get()).resolve()
        launch_test_pos(target)
        status.set('Test POS launched with the development database.')
    controls.append(ttk.Button(pane,text='Launch POS With Test Database',command=launch_pos)); controls[-1].pack(fill='x',pady=8)
    ttk.Label(pane,textvariable=status,wraplength=630).pack(anchor='w',pady=12)
    def poll():
        while not messages.empty():
            kind,text = messages.get(); status.set(text)
            if kind == 'done':
                for button in controls: button.configure(state='normal')
        root.after(100,poll)
    poll(); root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark',action='store_true')
    args = parser.parse_args()
    if args.benchmark:
        report = {}
        for count in (1500,5000):
            path = WORK / f'benchmark-{count}-{uuid.uuid4().hex[:8]}.sqlite3'
            prepare(path)
            start = time.perf_counter(); generate(path,count)
            report[str(count)] = benchmark(path)
            report[str(count)]['generation_and_benchmark_seconds'] = round(time.perf_counter()-start,2)
            print(json.dumps(report[str(count)]),flush=True)
        WORK.mkdir(exist_ok=True)
        (WORK / 'performance-report.json').write_text(json.dumps(report,indent=2))
    else:
        gui()
