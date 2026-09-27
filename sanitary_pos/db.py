"""Local storage and business rules. All money is paisa; quantities are thousandths."""
import json
import os
from contextlib import closing
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


class UserError(ValueError):
    pass


def scaled(value, scale=100, label="Amount", positive=False):
    try:
        number = Decimal(str(value).strip())
        result = number * scale
        if not number.is_finite() or result != result.to_integral_value():
            raise ValueError()
        if result < 0 or result > 10**12 or (positive and result == 0):
            raise ValueError()
        return int(result)
    except (InvalidOperation, ValueError, OverflowError):
        places = 2 if scale == 100 else 3
        raise UserError(f"{label}: enter {'a positive' if positive else 'a non-negative'} number with up to {places} decimal places.") from None


def money(paisa):
    return f"{paisa / 100:,.2f}"


def quantity(milli):
    return f"{milli / 1000:.3f}".rstrip('0').rstrip('.')


def line_total(price, qty):
    return int((Decimal(price) * qty / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


DEFAULTS = {'shop_logo': '', 'shop_name': 'Sanitary Shop', 'phone': '', 'address': '', 'ntn': '', 'footer': 'Thank you! Please visit again', 'paper': '80mm', 'printer': '', 'copies': '1', 'auto_print': 'Off', 'camera': 'Default Camera', 'low_stock': '5', 'last_backup': '', 'tax_enabled': 'Off', 'gst_rate': '18', 'tax_label': 'GST', 'update_auto_check': 'On', 'update_last_check': ''}
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL COLLATE NOCASE UNIQUE,
 qr TEXT NOT NULL COLLATE NOCASE UNIQUE, name TEXT NOT NULL, category TEXT NOT NULL,
 brand TEXT NOT NULL, size_variant TEXT NOT NULL DEFAULT '', purchase_paisa INTEGER NOT NULL CHECK(purchase_paisa>=0),
 selling_paisa INTEGER NOT NULL CHECK(selling_paisa>=0), stock_milli INTEGER NOT NULL CHECK(stock_milli>=0),
 unit TEXT NOT NULL, description TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS product_images (product_id INTEGER PRIMARY KEY REFERENCES products(id), image BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS sales (
 id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
 subtotal_paisa INTEGER NOT NULL CHECK(subtotal_paisa>=0), discount_paisa INTEGER NOT NULL CHECK(discount_paisa>=0),
 total_paisa INTEGER NOT NULL CHECK(total_paisa>=0), paid_paisa INTEGER NOT NULL CHECK(paid_paisa>=0), change_paisa INTEGER NOT NULL DEFAULT 0, taxable_paisa INTEGER NOT NULL DEFAULT 0, gst_rate_bps INTEGER NOT NULL DEFAULT 0, gst_paisa INTEGER NOT NULL DEFAULT 0, shop_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)));
CREATE TABLE IF NOT EXISTS sale_items (
 id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id),
 product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL, size_variant TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, unit TEXT NOT NULL,
 quantity_milli INTEGER NOT NULL CHECK(quantity_milli>0), price_paisa INTEGER NOT NULL CHECK(price_paisa>=0),
 total_paisa INTEGER NOT NULL CHECK(total_paisa>=0));
CREATE TABLE IF NOT EXISTS stock_movements (
 id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 delta_milli INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS draft (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pos_users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, role TEXT NOT NULL CHECK(role IN ('OWNER','MANAGER','CASHIER')),
 pin_salt BLOB NOT NULL, pin_hash BLOB NOT NULL, security_question TEXT NOT NULL DEFAULT '', security_answer_salt BLOB NOT NULL DEFAULT X'', security_answer_hash BLOB NOT NULL DEFAULT X'', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS role_permissions (role TEXT NOT NULL, permission TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), PRIMARY KEY(role, permission));
CREATE TABLE IF NOT EXISTS user_permissions (user_id INTEGER NOT NULL REFERENCES pos_users(id) ON DELETE CASCADE, permission TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), PRIMARY KEY(user_id, permission));
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_id INTEGER REFERENCES pos_users(id), user_name TEXT NOT NULL, action TEXT NOT NULL, reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sales_date ON sales(created_at);
CREATE INDEX IF NOT EXISTS items_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS audit_log_date ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS products_active_name ON products(active, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS products_active_code ON products(active, code COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS products_active_category ON products(active, category COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS products_active_brand ON products(active, brand COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS products_active_size ON products(active, size_variant COLLATE NOCASE);
"""


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA journal_mode=WAL')
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8):
            raise UserError('This data needs a newer version of the software.')
        self.conn.executescript(SCHEMA)
        migration_backup = self._migration_backup() if version and version < 8 else None
        try:
            if version < 2:
                self._migrate_v2()
            if version < 3:
                self._migrate_v3()
            if version < 4:
                self._migrate_v4()
            if version < 5:
                self._migrate_v5()
            if version < 6:
                self._migrate_v6()
            if version < 7:
                self._migrate_v7()
            if version < 8:
                self._migrate_v8()
        except Exception as error:
            if migration_backup:
                with closing(sqlite3.connect(migration_backup)) as source:
                    source.backup(self.conn)
            raise UserError('The shop database could not be upgraded. Your data was restored from a safety copy.') from error
        self.current_user = None
        self._settings_cache = None  # invalidated by save_settings()


    def _migration_backup(self):
        destination = self.path.parent / f'before-migration-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
        with closing(sqlite3.connect(destination)) as target:
            self.conn.backup(target)
        return destination

    def _migrate_v2(self):
        with self.conn:
            additions = {
                'products': [('size_variant', "TEXT NOT NULL DEFAULT ''")],
                'sales': [('change_paisa', 'INTEGER NOT NULL DEFAULT 0'), ('taxable_paisa', 'INTEGER NOT NULL DEFAULT 0'), ('gst_rate_bps', 'INTEGER NOT NULL DEFAULT 0'), ('gst_paisa', 'INTEGER NOT NULL DEFAULT 0')],
                'sale_items': [('size_variant', "TEXT NOT NULL DEFAULT ''")],
            }
            for table, fields in additions.items():
                existing = {row[1] for row in self.conn.execute(f'PRAGMA table_info({table})')}
                for name, definition in fields:
                    if name not in existing:
                        self.conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            self.conn.execute('PRAGMA user_version=2')

    def _migrate_v3(self):
        from .security import ROLE_DEFAULTS, PERMISSIONS
        with self.conn:
            self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS pos_users (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, role TEXT NOT NULL CHECK(role IN ('OWNER','MANAGER','CASHIER')), pin_salt BLOB NOT NULL, pin_hash BLOB NOT NULL, security_question TEXT NOT NULL DEFAULT '', security_answer_salt BLOB NOT NULL DEFAULT X'', security_answer_hash BLOB NOT NULL DEFAULT X'', active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS role_permissions (role TEXT NOT NULL, permission TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), PRIMARY KEY(role, permission));
            CREATE TABLE IF NOT EXISTS user_permissions (user_id INTEGER NOT NULL REFERENCES pos_users(id) ON DELETE CASCADE, permission TEXT NOT NULL, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), PRIMARY KEY(user_id, permission));
            CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, user_id INTEGER REFERENCES pos_users(id), user_name TEXT NOT NULL, action TEXT NOT NULL, reference TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS security_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS audit_log_date ON audit_log(created_at);
            ''')
            for role, allowed in ROLE_DEFAULTS.items():
                for permission in PERMISSIONS:
                    self.conn.execute('INSERT OR IGNORE INTO role_permissions(role,permission,allowed) VALUES(?,?,?)', (role, permission, int(permission in allowed)))
            self.conn.execute('PRAGMA user_version=3')

    def _migrate_v4(self):
        with self.conn:
            existing = {row[1] for row in self.conn.execute('PRAGMA table_info(pos_users)')}
            for name, definition in (
                ('security_question', "TEXT NOT NULL DEFAULT ''"),
                ('security_answer_salt', "BLOB NOT NULL DEFAULT X''"),
                ('security_answer_hash', "BLOB NOT NULL DEFAULT X''"),
            ):
                if name not in existing:
                    self.conn.execute(f'ALTER TABLE pos_users ADD COLUMN {name} {definition}')
            self.conn.execute('PRAGMA user_version=4')

    def _migrate_v5(self):
        from .security import PERMISSIONS, ROLE_DEFAULTS
        with self.conn:
            for role, allowed in ROLE_DEFAULTS.items():
                for permission in PERMISSIONS:
                    self.conn.execute('INSERT OR IGNORE INTO role_permissions(role,permission,allowed) VALUES(?,?,?)', (role, permission, int(permission in allowed)))
            self.conn.execute('PRAGMA user_version=5')

    def security_state(self):
        return dict(self.conn.execute('SELECT key,value FROM security_state').fetchall())

    def _migrate_v6(self):
        with self.conn:
            self.conn.execute('CREATE TABLE IF NOT EXISTS sale_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, sale_id INTEGER NOT NULL, created_at TEXT NOT NULL, total_paisa INTEGER NOT NULL CHECK(total_paisa>=0), shop_json TEXT NOT NULL)')
            self.conn.execute('CREATE TABLE IF NOT EXISTS return_items (id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES sale_returns(id), sale_item_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL, unit TEXT NOT NULL, quantity_milli INTEGER NOT NULL CHECK(quantity_milli>0), refund_paisa INTEGER NOT NULL CHECK(refund_paisa>=0))')
            self.conn.execute('CREATE INDEX IF NOT EXISTS return_item_source ON return_items(sale_item_id)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS return_bill ON sale_returns(sale_id)')
            self.conn.execute('PRAGMA user_version=6')

    def _migrate_v7(self):
        """Add complete, immutable return/refund details without changing sales."""
        from .security import PERMISSIONS, ROLE_DEFAULTS
        with self.conn:
            return_columns = {row[1] for row in self.conn.execute('PRAGMA table_info(sale_returns)')}
            for name, definition in (
                ('return_number', "TEXT NOT NULL DEFAULT ''"),
                ('refund_method', "TEXT NOT NULL DEFAULT 'Cash'"),
                ('reason', "TEXT NOT NULL DEFAULT 'Customer Return'"),
                ('processed_by', "TEXT NOT NULL DEFAULT ''"),
                ('status', "TEXT NOT NULL DEFAULT 'Completed'"),
            ):
                if name not in return_columns:
                    self.conn.execute(f'ALTER TABLE sale_returns ADD COLUMN {name} {definition}')
            item_columns = {row[1] for row in self.conn.execute('PRAGMA table_info(return_items)')}
            for name, definition in (
                ('size_variant', "TEXT NOT NULL DEFAULT ''"),
                ('original_unit_price_paisa', 'INTEGER NOT NULL DEFAULT 0'),
                ('returned_to_stock', 'INTEGER NOT NULL DEFAULT 1 CHECK(returned_to_stock IN (0,1))'),
            ):
                if name not in item_columns:
                    self.conn.execute(f'ALTER TABLE return_items ADD COLUMN {name} {definition}')
            self.conn.execute("UPDATE sale_returns SET return_number=printf('RET-%06d',id) WHERE return_number=''" )
            self.conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS return_number_unique ON sale_returns(return_number)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS return_date ON sale_returns(created_at)')
            for role, allowed in ROLE_DEFAULTS.items():
                for permission in PERMISSIONS:
                    self.conn.execute('INSERT OR IGNORE INTO role_permissions(role,permission,allowed) VALUES(?,?,?)', (role, permission, int(permission in allowed)))
            self.conn.execute('PRAGMA user_version=7')

    def _migrate_v8(self):
        """Keep cleared sales as audit records while hiding them from normal reports."""
        with self.conn:
            columns = {row[1] for row in self.conn.execute('PRAGMA table_info(sales)')}
            if 'archived' not in columns:
                self.conn.execute('ALTER TABLE sales ADD COLUMN archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))')
            self.conn.execute('CREATE INDEX IF NOT EXISTS sales_active_date ON sales(archived,created_at)')
            self.conn.execute('PRAGMA user_version=8')

    def returnable_items(self, sale_id):
        return self.conn.execute('''SELECT i.*, coalesce(r.returned,0) AS returned_milli FROM sale_items i
            LEFT JOIN (SELECT sale_item_id,sum(quantity_milli) returned FROM return_items ri JOIN sale_returns sr ON sr.id=ri.return_id WHERE sr.sale_id=? GROUP BY sale_item_id) r
            ON r.sale_item_id=i.id WHERE i.sale_id=? ORDER BY i.id''', (sale_id,sale_id)).fetchall()

    def return_quote(self, sale_id, quantities):
        """Read-only quote using original price, discount, GST and prior returns."""
        sale, _ = self.sale(sale_id)
        if not sale: raise UserError('This bill no longer exists.')
        requested = {int(key): scaled((value.get('quantity') if isinstance(value,dict) else value),1000,'Return quantity') for key,value in quantities.items()}
        items = self.returnable_items(sale_id)
        refundable_total = min(sale['total_paisa'], max(0, sale['paid_paisa']))
        cumulative = total = 0
        quoted = []
        for item in items:
            line_value = int((Decimal(cumulative + item['total_paisa']) * refundable_total / sale['subtotal_paisa']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) - int((Decimal(cumulative) * refundable_total / sale['subtotal_paisa']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if sale['subtotal_paisa'] else 0
            cumulative += item['total_paisa']
            qty = requested.get(item['id'],0)
            left = item['quantity_milli'] - item['returned_milli']
            if qty > left: raise UserError('Return quantity exceeds the quantity remaining on this bill.')
            if qty:
                refund = int((Decimal(line_value)*(item['returned_milli']+qty)/item['quantity_milli']).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) - int((Decimal(line_value)*item['returned_milli']/item['quantity_milli']).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                total += refund
                quoted.append({'item':item,'quantity_milli':qty,'refund_paisa':refund,'available_milli':left})
        if not quoted: raise UserError('Enter at least one return quantity.')
        return sale, quoted, total

    def return_sale(self, sale_id, quantities, token, reason='Customer Return', refund_method='Cash'):
        if not self.current_user or not self.allowed('sales.return'):
            raise UserError('You do not have permission to return sales. Ask the Owner.')
        reason = str(reason).strip()
        refund_method = str(refund_method).strip()
        if not reason or len(reason) > 160 or refund_method not in ('Cash', 'Other / Original Method'):
            raise UserError('Choose a refund method and enter a short return reason.')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            existing = self.conn.execute('SELECT id,sale_id FROM sale_returns WHERE token=?', (token,)).fetchone()
            if existing:
                if existing['sale_id'] != sale_id: raise UserError('Return reference does not match this bill.')
                return existing['id']
            sale, _ = self.sale(sale_id)
            if not sale: raise UserError('This bill no longer exists.')
            items = self.returnable_items(sale_id)
            requested = {}
            for key, value in quantities.items():
                detail = value if isinstance(value, dict) else {'quantity': value, 'to_stock': True}
                requested[int(key)] = (scaled(detail.get('quantity', '0'),1000,'Return quantity'), bool(detail.get('to_stock', True)))
            if not set(requested) <= {item['id'] for item in items}:
                raise UserError('A selected product is not on this bill.')
            prepared, cumulative, total = [], 0, 0
            # The original order-level discount and GST are allocated by each
            # line's original subtotal. The allocated total is capped at the
            # amount actually collected on the old bill.
            refundable_total = min(sale['total_paisa'], max(0, sale['paid_paisa']))
            def allocate(value):
                return int((Decimal(value) * refundable_total / sale['subtotal_paisa']).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if sale['subtotal_paisa'] else 0
            for item in items:
                net = allocate(cumulative + item['total_paisa']) - allocate(cumulative)
                cumulative += item['total_paisa']
                qty, to_stock = requested.get(item['id'], (0, True))
                if qty > item['quantity_milli'] - item['returned_milli']:
                    raise UserError('Return quantity exceeds the quantity remaining on this bill.')
                if not qty: continue
                stock = self.conn.execute('SELECT stock_milli FROM products WHERE id=?',(item['product_id'],)).fetchone()
                if not stock or (to_stock and stock[0] + qty > 10**12): raise UserError('Stock cannot be restored for this product.')
                def part(q):
                    return int((Decimal(net)*q/item['quantity_milli']).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
                refund = part(item['returned_milli']+qty) - part(item['returned_milli'])
                prepared.append((item,qty,refund,to_stock)); total += refund
            if not prepared: raise UserError('Enter at least one return quantity.')
            actor = self.current_user
            now = datetime.now().isoformat(timespec='seconds')
            return_id = self.conn.execute('INSERT INTO sale_returns(token,sale_id,created_at,total_paisa,shop_json,return_number,refund_method,reason,processed_by,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (token,sale_id,now,total,sale['shop_json'],'',refund_method,reason,actor['name'],'Completed')).lastrowid
            self.conn.execute("UPDATE sale_returns SET return_number=printf('RET-%06d',id) WHERE id=?", (return_id,))
            for item,qty,refund,to_stock in prepared:
                self.conn.execute('INSERT INTO return_items(return_id,sale_item_id,product_id,name,unit,quantity_milli,refund_paisa,size_variant,original_unit_price_paisa,returned_to_stock) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (return_id,item['id'],item['product_id'],item['name'],item['unit'],qty,refund,item['size_variant'],item['price_paisa'],int(to_stock)))
                if to_stock:
                    self.conn.execute('UPDATE products SET stock_milli=stock_milli+? WHERE id=?',(qty,item['product_id']))
                    self._movement(item['product_id'],qty,f'Return: Bill #{sale_id:06d}')
            self.conn.execute('INSERT INTO audit_log(created_at,user_id,user_name,action,reference) VALUES(?,?,?,?,?)',
                (now,actor['id'],actor['name'],'Processed return',f'RET-{return_id:06d}; Bill #{sale_id:06d}; Rs. {money(total)}; {reason}; stock restored: ' + ('yes' if any(x[3] for x in prepared) else 'no')))
            return return_id

    def update_security_state(self, **values):
        with self.conn:
            self.conn.executemany('INSERT OR REPLACE INTO security_state(key,value) VALUES(?,?)', values.items())

    def license_state(self):
        state = self.security_state()
        if not state.get('installation_salt'):
            state['installation_salt'] = os.urandom(24).hex()
            self.update_security_state(installation_salt=state['installation_salt'])
        return state

    def update_license_state(self, **values):
        self.license_state()
        self.update_security_state(**values)

    def device_id(self):
        from .device import device_id
        return device_id(self.license_state()['installation_salt'])

    def users(self, include_inactive=False):
        where = '' if include_inactive else ' WHERE active=1'
        return self.conn.execute('SELECT id,name,role,security_question,active,created_at,updated_at FROM pos_users' + where + ' ORDER BY name COLLATE NOCASE').fetchall()

    def user(self, user_id):
        row = self.conn.execute('SELECT id,name,role,security_question,active,created_at,updated_at FROM pos_users WHERE id=?', (user_id,)).fetchone()
        if not row:
            raise UserError('User not found.')
        return row

    def has_owner(self):
        return bool(self.conn.execute("SELECT 1 FROM pos_users WHERE role='OWNER' AND active=1").fetchone())

    def create_user(self, name, role, pin, security_question='', security_answer=''):
        from .security import hash_answer, hash_pin, timestamp
        name = str(name).strip()
        if not name or len(name) > 80:
            raise UserError('Enter a user name up to 80 characters.')
        if role not in ('OWNER', 'MANAGER', 'CASHIER'):
            raise UserError('Choose a valid role.')
        security_question = str(security_question).strip()
        answer_salt, answer_hash = hash_answer(security_answer)
        if not security_question:
            raise UserError('Enter a security question.')
        salt, digest = hash_pin(pin)
        now = timestamp()
        try:
            with self.conn:
                user_id = self.conn.execute('INSERT INTO pos_users(name,role,pin_salt,pin_hash,security_question,security_answer_salt,security_answer_hash,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,1,?,?)', (name, role, salt, digest, security_question, answer_salt, answer_hash, now, now)).lastrowid
            self.audit('Created user', f'{name} ({role})')
            return user_id
        except sqlite3.IntegrityError:
            raise UserError('That user name already exists.') from None

    def reset_pin_with_answer(self, user_id, answer, new_pin):
        from .security import answer_matches, hash_pin, timestamp
        row = self.conn.execute('SELECT * FROM pos_users WHERE id=? AND active=1', (user_id,)).fetchone()
        if row is None or not row['security_question'] or not answer_matches(answer, row['security_answer_salt'], row['security_answer_hash']):
            raise UserError('Security answer is incorrect.')
        salt, digest = hash_pin(new_pin)
        with self.conn:
            self.conn.execute('UPDATE pos_users SET pin_salt=?,pin_hash=?,updated_at=? WHERE id=?', (salt, digest, timestamp(), user_id))
        self.audit('Reset PIN with security answer', row['name'])

    def reset_pin(self, user_id, pin):
        if not self.current_user or self.current_user['role'] != 'OWNER':
            raise UserError('Only the Owner can reset user PINs.')
        from .security import hash_pin, timestamp
        salt, digest = hash_pin(pin)
        with self.conn:
            self.conn.execute('UPDATE pos_users SET pin_salt=?,pin_hash=?,updated_at=? WHERE id=?', (salt, digest, timestamp(), user_id))
        self.audit('Reset user PIN', self.user(user_id)['name'])

    def set_security_question(self, user_id, question, answer):
        if not self.current_user or self.current_user['role'] != 'OWNER':
            raise UserError('Only the Owner can change security questions.')
        from .security import hash_answer, timestamp
        question = str(question).strip()
        if not question:
            raise UserError('Choose a security question.')
        salt, digest = hash_answer(answer)
        person = self.user(user_id)
        with self.conn:
            self.conn.execute('UPDATE pos_users SET security_question=?,security_answer_salt=?,security_answer_hash=?,updated_at=? WHERE id=?',
                              (question, salt, digest, timestamp(), user_id))
        self.audit('Set security question', person['name'])

    def remove_user(self, user_id):
        if not self.current_user or self.current_user['role'] != 'OWNER':
            raise UserError('Only the Owner can remove users.')
        person = self.user(user_id)
        if not person['active']:
            raise UserError('That user has already been removed.')
        if self.current_user['id'] == user_id:
            raise UserError('You cannot remove the user currently logged in.')
        if person['role'] == 'OWNER' and self.conn.execute("SELECT COUNT(*) FROM pos_users WHERE role='OWNER' AND active=1").fetchone()[0] <= 1:
            raise UserError('The last active Owner cannot be removed.')
        from .security import timestamp
        with self.conn:
            self.conn.execute('UPDATE pos_users SET active=0,updated_at=? WHERE id=?', (timestamp(), user_id))
        self.audit('Removed user', person['name'])

    def change_own_pin(self, old_pin, new_pin):
        from .security import hash_pin, pin_matches, timestamp
        if not self.current_user:
            raise UserError('Please log in first.')
        row = self.conn.execute('SELECT * FROM pos_users WHERE id=?', (self.current_user['id'],)).fetchone()
        if not pin_matches(old_pin, row['pin_salt'], row['pin_hash']):
            raise UserError('Current PIN is incorrect.')
        salt, digest = hash_pin(new_pin)
        with self.conn:
            self.conn.execute('UPDATE pos_users SET pin_salt=?,pin_hash=?,updated_at=? WHERE id=?', (salt, digest, timestamp(), row['id']))
        self.audit('Changed own PIN', row['name'])

    def authenticate(self, user_id, pin):
        from .security import pin_matches
        row = self.conn.execute('SELECT * FROM pos_users WHERE id=? AND active=1', (user_id,)).fetchone()
        if row is None or not pin_matches(pin, row['pin_salt'], row['pin_hash']):
            raise UserError('Incorrect user or PIN.')
        self.current_user = dict(row)
        self.audit('Logged in', row['name'])
        return self.current_user

    def verify_owner_pin(self, pin):
        from .security import pin_matches
        row = self.conn.execute("SELECT * FROM pos_users WHERE role='OWNER' AND active=1 ORDER BY id LIMIT 1").fetchone()
        return bool(row and pin_matches(pin, row['pin_salt'], row['pin_hash']))

    def logout(self):
        self.current_user = None

    def permissions_for(self, user_id):
        user = self.user(user_id)
        permissions = {row['permission']: bool(row['allowed']) for row in self.conn.execute('SELECT permission,allowed FROM role_permissions WHERE role=?', (user['role'],))}
        permissions.update({row['permission']: bool(row['allowed']) for row in self.conn.execute('SELECT permission,allowed FROM user_permissions WHERE user_id=?', (user_id,))})
        return permissions

    def allowed(self, permission):
        return bool(self.current_user and self.permissions_for(self.current_user['id']).get(permission, False))

    def require(self, permission):
        if self.current_user is not None and not self.allowed(permission):
            raise UserError('You do not have permission for this action. Ask the Owner.')

    def set_role_permissions(self, role, values):
        from .security import PERMISSIONS
        if role not in ('MANAGER', 'CASHIER'):
            raise UserError('Owner permissions cannot be restricted.')
        with self.conn:
            for permission in PERMISSIONS:
                self.conn.execute('INSERT OR REPLACE INTO role_permissions(role,permission,allowed) VALUES(?,?,?)', (role, permission, int(bool(values.get(permission)))))
        self.audit('Changed role permissions', role)

    def audit(self, action, reference=''):
        from .security import timestamp
        actor = self.current_user or {}
        with self.conn:
            self.conn.execute('INSERT INTO audit_log(created_at,user_id,user_name,action,reference) VALUES(?,?,?,?,?)', (timestamp(), actor.get('id'), actor.get('name', 'System'), str(action)[:120], str(reference)[:500]))

    def audit_history(self, limit=500):
        return self.conn.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)).fetchall()

    def settings(self):
        if self._settings_cache is None:
            self._settings_cache = DEFAULTS | dict(self.conn.execute('SELECT key,value FROM settings').fetchall())
        return self._settings_cache

    def save_settings(self, values):
        self.require('settings.edit')
        if not values['shop_name'].strip():
            raise UserError('Enter the shop name.')
        scaled(values['low_stock'], 1000, 'Low stock limit')
        if values['paper'] not in ('58mm', '80mm', 'A4'):
            raise UserError('Choose a paper size.')
        try:
            copies = int(values.get('copies', '1'))
        except ValueError:
            raise UserError('Copies must be a whole number from 1 to 100.') from None
        if not 1 <= copies <= 100:
            raise UserError('Copies must be a whole number from 1 to 100.')
        if values.get('auto_print', 'Off') not in ('On', 'Off'):
            raise UserError('Choose whether to auto print after sale.')
        if values.get('tax_enabled', 'Off') not in ('On', 'Off'):
            raise UserError('Choose whether GST is enabled.')
        scaled(values.get('gst_rate', '18'), 100, 'GST rate')
        if not values.get('tax_label', 'GST').strip():
            raise UserError('Enter a tax label.')
        if not values.get('camera', 'Default Camera').strip():
            raise UserError('Choose a camera.')
        with self.conn:
            self.conn.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', values.items())
        self._settings_cache = None  # invalidate cache after save

    def stock_summary(self, low_stock_milli=5000):
        """Return (total_products, low_stock_count, out_of_stock_count) in a single query."""
        row = self.conn.execute(
            'SELECT COUNT(*), SUM(CASE WHEN stock_milli=0 THEN 1 ELSE 0 END), '
            'SUM(CASE WHEN stock_milli>0 AND stock_milli<=? THEN 1 ELSE 0 END) '
            'FROM products WHERE active=1',
            (low_stock_milli,)
        ).fetchone()
        return row[0] or 0, row[2] or 0, row[1] or 0  # total, low, out


    def products(self, query=''):
        # instr treats %, _ and scanner symbols literally, unlike LIKE.
                terms = query.strip().split()
                clauses, args = [], []
                for term in terms or ['']:
                        clauses.append('''(instr(lower(name),lower(?))>0 OR instr(lower(code),lower(?))>0 OR
                            instr(lower(category),lower(?))>0 OR instr(lower(brand),lower(?))>0 OR
                            instr(lower(size_variant),lower(?))>0 OR instr(lower(qr),lower(?))>0)''')
                        args.extend([term] * 6)
                return self.conn.execute('SELECT * FROM products WHERE active=1 AND ' + ' AND '.join(clauses) + ' ORDER BY name COLLATE NOCASE', args).fetchall()

    def product(self, product_id):
        row = self.conn.execute('SELECT * FROM products WHERE id=? AND active=1', (product_id,)).fetchone()
        if row is None:
            raise UserError('This product is no longer available. Remove it from the bill.')
        return row

    def exact(self, text):
        return self.conn.execute('SELECT * FROM products WHERE active=1 AND (code=? COLLATE NOCASE OR qr=? COLLATE NOCASE)', (text.strip(), text.strip())).fetchone()

    def save_product(self, values, product_id=None):
        self.require('products.edit' if product_id else 'products.add')
        data = {key: str(values.get(key, '')).strip() for key in ('name','code','qr','category','brand','size_variant','unit','description')}
        if not data['name'] or not data['code'] or not data['unit']:
            raise UserError('Enter a product name, code and unit.')
        data['qr'] = data['qr'] or data['code']
        if max(map(len, data.values())) > 1000 or len(data['qr'].encode('utf-8')) > 500:
            raise UserError('The product text or QR value is too long.')
        data['purchase_paisa'] = scaled(values['purchase'], label='Purchase price')
        data['selling_paisa'] = scaled(values['selling'], label='Selling price')
        data['stock_milli'] = scaled(values['stock'], 1000, 'Stock')
        try:
            with self.conn:
                self.conn.execute('BEGIN IMMEDIATE')
                conflict = self.conn.execute('SELECT id FROM products WHERE (code IN (?,?) COLLATE NOCASE OR qr IN (?,?) COLLATE NOCASE) AND id != ?', (data['code'], data['qr'], data['code'], data['qr'], product_id or -1)).fetchone()
                if conflict:
                    raise UserError('That code or QR value already belongs to another product. Choose a different value.')
                old_stock = self.product(product_id)['stock_milli'] if product_id else 0
                if product_id:
                    old = self.product(product_id)
                    if old['selling_paisa'] != data['selling_paisa']:
                        self.require('products.change_price')
                    self.conn.execute('UPDATE products SET ' + ','.join(f'{key}=?' for key in data) + ' WHERE id=?', [*data.values(), product_id])
                else:
                    product_id = self.conn.execute('INSERT INTO products (' + ','.join(data) + ') VALUES (' + ','.join('?' for _ in data) + ')', list(data.values())).lastrowid
                if values.get('image') is not None:
                    image = values['image']
                    if len(image) > 5 * 1024 * 1024:
                        raise UserError('Choose an image smaller than 5 MB.')
                    self.conn.execute('INSERT OR REPLACE INTO product_images VALUES (?,?)', (product_id, image))
                self._movement(product_id, data['stock_milli'] - old_stock, 'Product stock edited' if old_stock else 'Opening stock')
            self.audit('Changed product' if product_id else 'Created product', data['name'])
            return product_id
        except sqlite3.IntegrityError:
            raise UserError('That product code or QR value is already in use.') from None

    def _movement(self, product_id, delta, reason):
        if delta:
            self.conn.execute('INSERT INTO stock_movements(product_id,delta_milli,reason,created_at) VALUES(?,?,?,?)', (product_id, delta, reason, datetime.now().isoformat(timespec='seconds')))

    def archive(self, product_id):
        self.require('products.delete')
        product = self.product(product_id)
        with self.conn:
            self.conn.execute('UPDATE products SET active=0 WHERE id=?', (product_id,))
        self.audit('Deleted product', product['name'])

    def archive_all_products(self):
        """Hide every active product without changing past bills or stock records."""
        self.require('products.delete')
        count = self.conn.execute('SELECT count(*) FROM products WHERE active=1').fetchone()[0]
        if not count:
            raise UserError('There are no active products to delete.')
        with self.conn:
            self.conn.execute('UPDATE products SET active=0 WHERE active=1')
        self.audit('Deleted all products', f'{count} product(s); previous bills kept')
        return count

    def adjust_stock(self, product_id, amount, increase, reason):
        self.require('stock.increase' if increase else 'stock.decrease')
        change = scaled(amount, 1000, 'Stock change', positive=True) * (1 if increase else -1)
        if not reason.strip():
            raise UserError('Enter a short reason for the stock change.')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            current = self.product(product_id)['stock_milli']
            if current + change < 0 or current + change > 10**12:
                raise UserError('Stock cannot go below zero or above the allowed limit.')
            self.conn.execute('UPDATE products SET stock_milli=stock_milli+? WHERE id=?', (change, product_id))
            self._movement(product_id, change, reason.strip())
        self.audit('Increased stock' if increase else 'Decreased stock', f'{self.product(product_id)["name"]} {"+" if increase else "-"}{amount}')

    def save_draft(self, payload):
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO draft VALUES(1,?)', (json.dumps(payload),))

    def load_draft(self):
        row = self.conn.execute('SELECT payload FROM draft WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {'cart': [], 'discount': '0', 'discount_mode': 'cash', 'paid': '', 'customer_name': '', 'customer_phone': '', 'token': str(uuid.uuid4())}

    def complete_sale(self, cart, discount, paid, token, customer_name='', customer_phone='', discount_mode='cash'):
        self.require('billing.create')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            previous = self.conn.execute('SELECT id FROM sales WHERE token=?', (token,)).fetchone()
            if previous:
                return previous[0]
            if not cart:
                raise UserError('Add at least one product to the bill.')
            lines, seen = [], set()
            for item in cart:
                product = self.product(item['id'])
                qty, price = item['qty'], item['price']
                if type(qty) is not int or qty <= 0 or qty > 10**12 or type(price) is not int or price < 0 or price > 10**12:
                    raise UserError('Check the product quantity and price.')
                if product['id'] in seen:
                    raise UserError('A product appears twice. Please rebuild this bill.')
                seen.add(product['id'])
                if qty > product['stock_milli']:
                    raise UserError(f"Only {quantity(product['stock_milli'])} {product['unit']} of {product['name']} available.")
                lines.append((product, qty, price, line_total(price, qty)))
            subtotal = sum(line[3] for line in lines)
            if discount_mode == 'cash':
                disc = scaled(discount, label='Discount')
            elif discount_mode == 'percent':
                percent = scaled(discount, label='Discount percentage')
                if percent > 10000:
                    raise UserError('Discount percentage cannot be more than 100%.')
                disc = int((Decimal(subtotal) * percent / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            else:
                raise UserError('Choose a valid discount type.')
            if disc > subtotal:
                raise UserError('Discount cannot be more than the bill subtotal.')
            taxable = subtotal - disc
            settings = self.settings()
            tax_enabled = settings.get('tax_enabled', 'Off') == 'On'
            gst_rate_bps = scaled(settings.get('gst_rate', '18'), 100, 'GST rate') if tax_enabled else 0
            gst = int((Decimal(taxable) * gst_rate_bps / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            total = taxable + gst
            payment = total if str(paid).strip() == '' else scaled(paid, label='Cash received')
            change = payment - total
            snapshot = settings | {'customer_name': str(customer_name).strip(), 'customer_phone': str(customer_phone).strip()}
            sale_id = self.conn.execute('INSERT INTO sales(token,created_at,subtotal_paisa,discount_paisa,total_paisa,paid_paisa,change_paisa,taxable_paisa,gst_rate_bps,gst_paisa,shop_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (token, datetime.now().isoformat(timespec='seconds'), subtotal, disc, total, payment, change, taxable, gst_rate_bps, gst, json.dumps(snapshot))).lastrowid
            for p, qty, price, amount in lines:
                self.conn.execute('INSERT INTO sale_items(sale_id,product_id,name,size_variant,code,unit,quantity_milli,price_paisa,total_paisa) VALUES(?,?,?,?,?,?,?,?,?)', (sale_id, p['id'], p['name'], p['size_variant'], p['code'], p['unit'], qty, price, amount))
                self.conn.execute('UPDATE products SET stock_milli=stock_milli-? WHERE id=?', (qty, p['id']))
                self._movement(p['id'], -qty, f'Sale #{sale_id:06d}')
            self.conn.execute('DELETE FROM draft')
            self.audit('Created bill', f'Bill #{sale_id:06d} Rs. {money(total)}')
            return sale_id

    def sales(self, bill='', date='', customer=''):
        return self.conn.execute('''SELECT * FROM sales WHERE archived=0 AND (?='' OR id=?) AND (?='' OR substr(created_at,1,10)=?)
            AND (?='' OR instr(lower(shop_json),lower(?))>0) ORDER BY id DESC''',
            (bill, bill.lstrip('#').lstrip('0') or '0', date, date, customer, customer)).fetchall()

    def sale_return_status(self, sale_id):
        row = self.conn.execute('''SELECT (SELECT coalesce(sum(quantity_milli),0) FROM sale_items WHERE sale_id=?) AS sold,
            (SELECT coalesce(sum(ri.quantity_milli),0) FROM return_items ri JOIN sale_returns sr ON sr.id=ri.return_id WHERE sr.sale_id=?) AS returned''', (sale_id,sale_id)).fetchone()
        if not row['returned']: return 'COMPLETED'
        return 'FULLY RETURNED' if row['returned'] >= row['sold'] else 'PARTIALLY RETURNED'

    def returns(self, bill='', date='', customer=''):
        return self.conn.execute('''SELECT r.*, s.shop_json FROM sale_returns r JOIN sales s ON s.id=r.sale_id
            WHERE s.archived=0 AND (?='' OR r.sale_id=?) AND (?='' OR substr(r.created_at,1,10)=?)
            AND (?='' OR instr(lower(s.shop_json),lower(?))>0) ORDER BY r.id DESC''',
            (bill, bill.lstrip('#').lstrip('0') or '0', date, date, customer, customer)).fetchall()

    def return_record(self, return_id):
        row = self.conn.execute('SELECT * FROM sale_returns WHERE id=?', (return_id,)).fetchone()
        if not row: raise UserError('Return not found.')
        return row, self.conn.execute('SELECT * FROM return_items WHERE return_id=? ORDER BY id', (return_id,)).fetchall()

    def sales_totals(self, date=''):
        gross = self.conn.execute("SELECT coalesce(sum(total_paisa),0) FROM sales WHERE archived=0 AND (?='' OR substr(created_at,1,10)=?)", (date,date)).fetchone()[0]
        refunds = self.conn.execute("SELECT coalesce(sum(r.total_paisa),0) FROM sale_returns r JOIN sales s ON s.id=r.sale_id WHERE s.archived=0 AND r.status='Completed' AND (?='' OR substr(r.created_at,1,10)=?)", (date,date)).fetchone()[0]
        return gross, refunds, gross-refunds

    def today_total(self):
        return self.conn.execute('SELECT coalesce(sum(total_paisa),0) FROM sales WHERE archived=0 AND substr(created_at,1,10)=?', (datetime.now().date().isoformat(),)).fetchone()[0]

    def sale(self, sale_id):
        return (self.conn.execute('SELECT * FROM sales WHERE id=?', (sale_id,)).fetchone(), self.conn.execute('SELECT * FROM sale_items WHERE sale_id=? ORDER BY id', (sale_id,)).fetchall())

    def next_sale_number(self):
        row = self.conn.execute("SELECT seq FROM sqlite_sequence WHERE name='sales'").fetchone()
        return (row[0] if row else 0) + 1

    def delete_sales(self, sale_ids=None):
        self.require('sales.cancel')
        ids = [r['id'] for r in self.sales()] if sale_ids is None else list(dict.fromkeys(sale_ids))
        if not ids:
            raise UserError('Select at least one bill.')
        safety = self.path.parent / f'before-delete-sales-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
        self.backup(safety)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            for sale_id in ids:
                if not self.conn.execute('SELECT 1 FROM sales WHERE id=?', (sale_id,)).fetchone():
                    raise UserError('A selected bill no longer exists. Refresh Sales and try again.')
                if self.conn.execute('SELECT 1 FROM sale_returns WHERE sale_id=?', (sale_id,)).fetchone():
                    self.conn.execute('UPDATE sales SET archived=1 WHERE id=?', (sale_id,))
                else:
                    self.conn.execute('DELETE FROM sale_items WHERE sale_id=?', (sale_id,))
                    self.conn.execute('DELETE FROM sales WHERE id=?', (sale_id,))
        self.audit('Cleared sales history', f'{len(ids)} bill(s); stock unchanged; returned bills archived')
        return safety

    def backup(self, destination):
        self.require('backup.create')
        destination = Path(destination).resolve()
        if destination == self.path:
            raise UserError('Choose a different file from the current shop data.')
        with closing(sqlite3.connect(destination)) as target:
            self.conn.backup(target)

    @staticmethod
    def validate_backup(source):
        path = Path(source).resolve()
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as check:
                backup_version = check.execute('PRAGMA user_version').fetchone()[0]
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or backup_version not in (1, 2, 3, 4, 5, 6, 7, 8):
                    raise ValueError()
                expected = {'products': {'id','code','qr','name','category','brand','purchase_paisa','selling_paisa','stock_milli','unit','description','active'}, 'sales': {'id','token','created_at','subtotal_paisa','discount_paisa','total_paisa','paid_paisa','shop_json'}, 'sale_items': {'id','sale_id','product_id','name','code','unit','quantity_milli','price_paisa','total_paisa'}, 'stock_movements': {'id','product_id','delta_milli','reason','created_at'}, 'settings': {'key','value'}, 'draft': {'id','payload'}}
                if backup_version == 2:
                    expected['products'] |= {'size_variant'}
                    expected['sales'] |= {'change_paisa','taxable_paisa','gst_rate_bps','gst_paisa'}
                    expected['sale_items'] |= {'size_variant'}
                if backup_version in (3, 4, 5, 6, 7, 8):
                    expected['products'] |= {'size_variant'}
                    expected['sales'] |= {'change_paisa','taxable_paisa','gst_rate_bps','gst_paisa'}
                    expected['sale_items'] |= {'size_variant'}
                    expected |= {
                        'pos_users': {'id','name','role','pin_salt','pin_hash','active','created_at','updated_at'} | ({'security_question','security_answer_salt','security_answer_hash'} if backup_version >= 4 else set()),
                        'role_permissions': {'role','permission','allowed'},
                        'user_permissions': {'user_id','permission','allowed'},
                        'audit_log': {'id','created_at','user_id','user_name','action','reference'},
                        'security_state': {'key','value'},
                    }
                if backup_version >= 6:
                    expected['sale_returns'] = {'id','token','sale_id','created_at','total_paisa','shop_json'}
                    expected['return_items'] = {'id','return_id','sale_item_id','product_id','name','unit','quantity_milli','refund_paisa'}
                if backup_version >= 7:
                    expected['sale_returns'] |= {'return_number','refund_method','reason','processed_by','status'}
                    expected['return_items'] |= {'size_variant','original_unit_price_paisa','returned_to_stock'}
                if backup_version >= 8:
                    expected['sales'] |= {'archived'}
                for table, columns in expected.items():
                    if {r[1] for r in check.execute(f'PRAGMA table_info({table})')} != columns:
                        raise ValueError()
                if check.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError()
                if check.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
                    raise ValueError()
                for row in check.execute('SELECT shop_json FROM sales UNION ALL SELECT payload FROM draft'):
                    if not isinstance(json.loads(row[0]), dict):
                        raise ValueError()
        except (sqlite3.Error, ValueError, OSError):
            raise UserError('This is not a valid shop backup. Choose a backup made by this software.') from None

    def restore(self, source):
        self.require('backup.restore')
        source = Path(source).resolve()
        if source == self.path:
            raise UserError('Choose a backup file, not the current shop data.')
        self.validate_backup(source)
        safety = self.path.parent / f'before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
        self.backup(safety)
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as backup:
            backup.backup(self.conn)
        self.conn.executescript(SCHEMA)
        self._migrate_v2()
        self._migrate_v3()
        self._migrate_v4()
        self._migrate_v5()
        self._migrate_v6()
        self._migrate_v7()
        self._migrate_v8()
        self.audit('Restored backup', str(source.name))
        return safety
