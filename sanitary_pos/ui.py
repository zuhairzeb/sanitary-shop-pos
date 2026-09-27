import logging
import base64
import os
import subprocess
import sys
import threading
import webbrowser
import cv2
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import uuid
from decimal import Decimal, ROUND_HALF_UP

from datetime import date, datetime
from .db import UserError, scaled, money, quantity, line_total
from .printing import preview, receipt_text, receipt_number
from .version import APP_VERSION
from .security import PERMISSIONS
from .version import APP_VERSION
from . import updater


UNIT_LABELS = {
    'Piece': 'pcs',
    'Box': 'boxes',
    'Set': 'sets',
    'Meter': 'm',
    'Feet': 'ft',
    'Roll': 'rolls',
    'Pair': 'pairs',
}


def unit_display(unit, milli=0):
    unit = (unit or 'Piece').strip() or 'Piece'
    suffix = UNIT_LABELS.get(unit, unit.lower())
    return f"{quantity(milli)} {suffix}"


def human_datetime(value):
    return datetime.fromisoformat(value).strftime('%d %b %Y, %I:%M %p')


def installed_printers():
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', 'Get-Printer | Select-Object -ExpandProperty Name'], capture_output=True, text=True, timeout=3, creationflags=0x08000000)
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return names or ['Default printer']
    except (OSError, subprocess.SubprocessError):
        return ['Default printer']


from .return_ui import ReturnActions


class App(ReturnActions, tk.Tk):
    def __init__(self, store, development_mode=False):
        super().__init__()
        self.store = store
        self.development_mode = development_mode
        self._closed = False
        self.camera_window = None
        self.title('Sanitary Shop · Billing & Stock' + (' · TEST DATABASE — DEVELOPMENT MODE' if development_mode else ''))
        self.geometry('1180x780')
        self.minsize(980, 680)
        self.configure(bg='#f6f8f7')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 11), background='#f6f8f7', foreground='#1f2937')
        style.configure('TButton', padding=(14, 7), background='#ffffff', foreground='#263238', bordercolor='#cbd5d1', lightcolor='#ffffff', darkcolor='#cbd5d1', borderwidth=1, font=('Segoe UI', 11, 'bold'))
        style.map('TButton', background=[('active', '#e3f4ec'), ('pressed', '#cbe8d9'), ('disabled', '#d6e0db')], foreground=[('disabled', '#34443d')])
        style.configure('Accent.TButton', background='#087a55', foreground='white', bordercolor='#087a55', lightcolor='#087a55', darkcolor='#087a55', padding=(18, 9))
        style.map('Accent.TButton', background=[('disabled', '#b9cec3'), ('pressed', '#066847'), ('active', '#16a36f')], foreground=[('disabled', '#33443d'), ('!disabled', 'white')])
        style.configure('Danger.TButton', background='#ffe1d8', foreground='#7f2e1d', bordercolor='#d99b88', lightcolor='#fffaf8', darkcolor='#d99b88')
        style.map('Danger.TButton', background=[('disabled', '#e4c6bc'), ('active', '#ffcfc1'), ('pressed', '#f3b9a7')], foreground=[('disabled', '#5f3329')])
        style.configure('Scanner.TButton', padding=(10, 8), background='#eef8f3', foreground='#087a55', bordercolor='#b9dfcd')
        style.map('Scanner.TButton', background=[('active', '#dcefe6'), ('pressed', '#c7e5d6')])
        style.configure('TEntry', padding=9, fieldbackground='#ffffff', foreground='#1f2937', bordercolor='#cbd5d1', lightcolor='#ffffff', darkcolor='#cbd5d1')
        style.map('TEntry', bordercolor=[('focus', '#087a55')], lightcolor=[('focus', '#087a55')])
        style.configure('TLabelframe', background='#ffffff', bordercolor='#e4e9e7', borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background='#ffffff', foreground='#475467', font=('Segoe UI', 10, 'bold'))
        style.configure('Card.TFrame', background='#ffffff')
        style.configure('Card.TLabel', background='#ffffff', foreground='#1f2937')
        style.configure('Muted.TLabel', foreground='#475467', background='#ffffff', font=('Segoe UI', 10))
        style.configure('TotalCard.TFrame', background='#eef8f3')
        style.configure('TotalCaption.TLabel', background='#eef8f3', foreground='#087a55', font=('Segoe UI', 10, 'bold'))
        style.configure('Total.TLabel', background='#eef8f3', foreground='#087a55', font=('Segoe UI', 30, 'bold'))
        style.configure('Treeview', rowheight=40, background='#ffffff', fieldbackground='#ffffff', borderwidth=0, foreground='#1f2937')
        style.map('Treeview', background=[('selected', '#d9f1e5')], foreground=[('selected', '#066847')])
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), foreground='#344054', background='#e8eeeb', padding=(10, 10), relief='flat')
        self.sidebar = tk.Frame(self, bg='#0b3d32', width=232)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg='#0b3d32')
        brand.pack(fill='x', padx=20, pady=(26, 30))
        self.brand_mark = tk.Label(brand, text='SS', bg='#0b3d32', fg='#63d49d', font=('Segoe UI', 16, 'bold'))
        self.brand_mark.pack(anchor='w')
        self.brand_name_label = tk.Label(brand, text=store.settings()['shop_name'], bg='#0b3d32', fg='white', font=('Segoe UI', 16, 'bold'))
        self.brand_name_label.pack(anchor='w', pady=(8, 0))
        tk.Label(brand, text='Build Better Spaces', bg='#0b3d32', fg='#a8c7bb', font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 0))
        self.nav_buttons = {}
        self.nav_icons = {}
        for name, icon in (('Billing', 'cart'), ('Products', 'box'), ('Stock', 'warehouse'), ('Sales', 'chart'), ('Backup', 'database'), ('Settings', 'gear')):
            self.nav_buttons[name] = self.nav_button(name, icon)
        sidebar_footer = tk.Frame(self.sidebar, bg='#0b3d32')
        sidebar_footer.pack(side='bottom', fill='x', padx=20, pady=24)
        self.sidebar_shop_label = tk.Label(sidebar_footer, text=store.settings()['shop_name'], bg='#0b3d32', fg='#d4e5de', font=('Segoe UI', 10, 'bold'))
        self.sidebar_shop_label.pack(anchor='w')
        tk.Label(sidebar_footer, text=f'Version {APP_VERSION}', bg='#0b3d32', fg='#82a99b', font=('Segoe UI', 9)).pack(anchor='w', pady=(3, 12))
        tk.Label(sidebar_footer, text='Simple. Fast. Reliable.', bg='#0b3d32', fg='#63d49d', font=('Segoe UI', 9)).pack(anchor='w')
        self.main = tk.Frame(self, bg='#f6f8f7')
        self.main.pack(side='left', fill='both', expand=True)
        header = tk.Frame(self.main, bg='#f6f8f7')
        header.pack(fill='x', padx=30, pady=(14, 4))
        header_left = tk.Frame(header, bg='#f6f8f7')
        header_left.pack(side='left')
        self.page_kicker = tk.Label(header_left, text='WELCOME', bg='#f6f8f7', fg='#087a55', font=('Segoe UI', 9, 'bold'))
        self.page_kicker.pack(anchor='w')
        self.page_title = tk.Label(header_left, text='Billing', bg='#f6f8f7', fg='#14213d', font=('Segoe UI', 22, 'bold'))
        self.page_title.pack(anchor='w', pady=(2, 0))
        self.page_subtitle = tk.Label(header_left, text='Create a new bill, scan products or search by name or code', bg='#f6f8f7', fg='#667085', font=('Segoe UI', 10))
        self.page_subtitle.pack(anchor='w', pady=(2, 0))
        header_right = tk.Frame(header, bg='#f6f8f7')
        header_right.pack(side='right', anchor='n')
        shop_name = store.settings()['shop_name']
        self.header_shop = tk.Label(header_right, text=shop_name, bg='#f6f8f7', fg='#14213d', font=('Segoe UI', 10, 'bold'))
        self.header_shop.pack(anchor='e')
        self.shop_label = self.header_shop
        self.header_status = tk.Label(header_right, text='TEST DATABASE — DEVELOPMENT MODE' if development_mode else '●  Offline  ·  Your data stays on this computer', bg='#fff1c7' if development_mode else '#eef8f3', fg='#8a5a00' if development_mode else '#087a55', padx=10, pady=6, font=('Segoe UI', 9, 'bold'))
        self.header_status.pack(anchor='e', pady=(8, 0))
        self.header_clock = tk.Label(header_right, bg='#f6f8f7', fg='#667085', font=('Segoe UI', 9))
        self.header_clock.pack(anchor='e', pady=(5, 0))
        self.header_user = tk.Label(header_right, text='', bg='#f6f8f7', fg='#475467', font=('Segoe UI', 9))
        self.header_user.pack(anchor='e', pady=(4, 0))
        ttk.Button(sidebar_footer, text='Switch User', command=self.switch_user).pack(fill='x', pady=(12, 4))
        ttk.Button(sidebar_footer, text='Change my PIN', command=self.change_my_pin).pack(fill='x')
        self.update_clock()
        self.frames = {}
        for name in ('Billing', 'Products', 'Stock', 'Sales', 'Backup', 'Settings'):
            frame = ttk.Frame(self.main, padding=(30, 4, 30, 10))
            frame.pack_forget()
            self.frames[name] = frame
        self.status = tk.StringVar(value='Ready. Scan or search to start a bill.')
        self.toast = tk.Label(self.main, text='', bg='#ffffff', fg='#087a55', padx=14, pady=9, relief='solid', bd=1, highlightthickness=0, font=('Segoe UI', 10, 'bold'))
        self.toast_job = None
        self.status.trace_add('write', lambda *_: self.show_toast(self.status.get()))
        self.draft = store.load_draft()
        self.cart = self.draft['cart']
        self._inventory_dirty = False
        self._products_dirty = False
        self.build_billing()
        self.build_products()
        self.build_inventory()
        self.build_sales()
        self.build_settings()
        self.bind('<F2>', self.focus_scan)
        self.bind('<F4>', self.focus_qr)
        self.bind('<F8>', lambda event: self.complete(False))
        self.bind('<F9>', lambda event: self.complete(True))
        self.bind('<KeyPress-plus>', lambda event: self.change_selected_quantity(1000))
        self.bind('<KeyPress-equal>', lambda event: self.change_selected_quantity(1000))
        self.bind('<KeyPress-minus>', lambda event: self.change_selected_quantity(-1000))
        self.bind('<Delete>', lambda event: self.remove_selected_item())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.show_page('Billing')
        self.refresh_all()
        self.refresh_user_header()
        self.update_check_job = self.after(1200, self.background_update_check)

    def report_callback_exception(self, exc, value, tb):
        if isinstance(value, UserError):
            message = str(value)
            lower = message.lower()
            # Only apply specific overrides for generic/confusing internal messages.
            # Do NOT convert specific field errors (discount, cash, stock) to a vague popup.
            if 'not found' in lower:
                message = 'Product not found.'
            elif 'printer' in lower:
                message = 'Printer is not available.'
            elif 'backup' in lower or ('database' in lower and 'product' not in lower):
                message = 'Backup could not be completed.'
            # All other UserError messages (including quantity, discount, cash, stock errors)
            # are shown as-is because they already contain the specific field name.
            messagebox.showwarning('Please check', message, parent=self)
        else:
            logging.error('Application action failed', exc_info=(exc, value, tb))
            messagebox.showerror('Could not finish', 'Could not finish this action. Your saved bills are safe. Please try again.', parent=self)

    def update_clock(self):
        self.header_clock.configure(text=datetime.now().strftime('%d %b %Y  ·  %I:%M %p'))
        self.clock_job = self.after(30000, self.update_clock)

    def show_toast(self, message):
        if not message or message.startswith('Ready.'):
            return
        if self.toast_job is not None:
            self.after_cancel(self.toast_job)
        self.toast.configure(text=f'✓  {message.lstrip("✓ ")}')
        self.toast.place(relx=1, rely=1, anchor='se', x=-24, y=-20)
        self.toast_job = self.after(2200, self.toast.place_forget)

    def update_search_hint(self):
        if not self.search.get().strip():
            self.search_hint.place(x=11, y=10)

    def toggle_customer_details(self):
        self.customer_open = not self.customer_open
        if self.customer_open:
            self.customer_toggle.configure(text='Customer details (optional)  ▲')
            self.customer_fields.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        else:
            self.customer_toggle.configure(text='Customer details (optional)  ▼')
            self.customer_fields.grid_forget()

    def nav_button(self, name, icon):
        image = self.make_nav_icon(icon)
        self.nav_icons[name] = image
        button = tk.Button(self.sidebar, text=name, image=image, compound='left', anchor='w', command=lambda: self.show_page(name), relief='flat', bd=0, highlightthickness=0, padx=18, pady=10, bg='#0b3d32', fg='#d4e5de', activebackground='#145b49', activeforeground='white', font=('Segoe UI', 10, 'bold'), cursor='hand2')
        button.pack(fill='x', padx=12, pady=2)
        return button

    def make_nav_icon(self, kind):
        image = tk.PhotoImage(width=20, height=20)
        color = '#b8d8cb'
        def pixel(x, y):
            image.put(color, to=(x, y, x + 1, y + 1))
        def line(x1, y1, x2, y2):
            steps = max(abs(x2 - x1), abs(y2 - y1))
            for step in range(steps + 1):
                x = round(x1 + (x2 - x1) * step / max(steps, 1))
                y = round(y1 + (y2 - y1) * step / max(steps, 1))
                pixel(x, y)
        if kind == 'cart':
            line(2, 4, 5, 4); line(5, 4, 7, 14); line(7, 14, 17, 14); line(8, 8, 17, 8); line(8, 8, 7, 12); line(8, 8, 17, 8); line(17, 8, 15, 12); line(15, 12, 7, 12)
            for x in (9, 15):
                image.put(color, to=(x, 17, x + 2, 19))
        elif kind == 'box':
            line(3, 6, 10, 2); line(10, 2, 17, 6); line(3, 6, 10, 10); line(10, 10, 17, 6); line(3, 6, 3, 16); line(3, 16, 17, 16); line(17, 6, 17, 16); line(10, 10, 10, 19)
        elif kind == 'warehouse':
            line(2, 8, 10, 3); line(10, 3, 18, 8); line(3, 8, 3, 17); line(17, 8, 17, 17); line(3, 17, 17, 17); line(6, 10, 6, 17); line(10, 10, 10, 17); line(14, 10, 14, 17)
        elif kind == 'chart':
            line(3, 17, 3, 4); line(3, 17, 18, 17); line(6, 14, 6, 11); line(10, 14, 10, 7); line(14, 14, 14, 4); line(17, 14, 17, 9)
        elif kind == 'database':
            line(4, 5, 4, 15); line(16, 5, 16, 15); line(4, 5, 16, 5); line(4, 10, 16, 10); line(4, 15, 16, 15); line(4, 5, 10, 2); line(10, 2, 16, 5)
        else:
            for start, end in ((4, 16), (7, 13), (9, 11)):
                line(start, 10, end, 10); line(10, start, 10, end)
            line(5, 5, 15, 15); line(15, 5, 5, 15)
        return image

    def show_page(self, name):
        page_permission = {'Products': 'products.view', 'Stock': 'stock.view', 'Sales': 'sales.view', 'Backup': 'backup.create', 'Settings': 'settings.view'}.get(name)
        if page_permission:
            self.store.require(page_permission)
        self.current_page = name
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill='both', expand=True)
        for page_name, button in self.nav_buttons.items():
            active = page_name == name
            button.configure(bg='#087a55' if active else '#0b3d32', fg='white' if active else '#d4e5de')
        subtitles = {
            'Billing': ('WELCOME', 'Billing', 'Create a new bill, scan products or search by name or code'),
            'Products': ('CATALOG', 'Products', 'Manage products, prices and QR labels'),
            'Stock': ('INVENTORY', 'Stock', 'Track and update your inventory'),
            'Sales': ('HISTORY', 'Sales', 'Review bills and sales history'),
            'Backup': ('DATA SAFETY', 'Backup & Restore', 'Protect your shop data'),
            'Settings': ('PREFERENCES', 'Settings', 'Shop, printer and application preferences'),
        }
        kicker, title, subtitle = subtitles[name]
        self.page_kicker.configure(text=kicker)
        self.page_title.configure(text=title)
        self.page_subtitle.configure(text=subtitle)
        if name == 'Billing':
            self.refresh_search()
            self.search_entry.focus_set()
        elif name == 'Products':
            if getattr(self, '_products_dirty', False):
                self._products_dirty = False
                self.refresh_products()
        elif name == 'Sales':
            self.refresh_sales()
        elif name == 'Stock':
            self.refresh_inventory()
            self._inventory_dirty = False

    def button(self, frame, title, command, accent=False):
        destructive = title.lower() in ('remove', 'delete product')
        button_style = 'Accent.TButton' if accent else 'Danger.TButton' if destructive else 'TButton'
        button = ttk.Button(frame, text=title, command=command, style=button_style)
        button.pack(side='left', padx=(0, 8), pady=4)
        return button

    def refresh_user_header(self):
        user = self.store.current_user or {}
        self.header_user.configure(text=f"{user.get('name', 'Offline')} · {user.get('role', '')}")
        requirements = {'Products': 'products.view', 'Stock': 'stock.view', 'Sales': 'sales.view', 'Backup': 'backup.create', 'Settings': 'settings.view'}
        for name, button in self.nav_buttons.items():
            if name in requirements:
                button.configure(state='normal' if self.store.allowed(requirements[name]) else 'disabled')

    def switch_user(self):
        if not messagebox.askyesno('Switch User', 'Save the current bill draft and return to login?', parent=self):
            return
        self.persist()
        self.store.audit('Switched user', 'Returned to login')
        self.store.logout()
        self.switch_requested = True
        self.close()

    def change_my_pin(self):
        old = simpledialog.askstring('Change my PIN', 'Current PIN', show='•', parent=self)
        if old is None: return
        new = simpledialog.askstring('Change my PIN', 'New PIN (4–6 digits)', show='•', parent=self)
        if new is None: return
        confirm = simpledialog.askstring('Change my PIN', 'Confirm new PIN', show='•', parent=self)
        if confirm is None: return
        if new != confirm: raise UserError('PIN confirmation does not match.')
        self.store.change_own_pin(old, new)
        messagebox.showinfo('PIN changed', 'Your PIN has been changed.', parent=self)

    def require(self, permission):
        self.store.require(permission)

    def owner_approval(self, title, message):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        result = {'approved': False}
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Owner approval required', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=message, wraplength=360).pack(anchor='w', pady=(6, 16))
        pin = tk.StringVar()
        ttk.Label(frame, text='Owner PIN').pack(anchor='w')
        entry = ttk.Entry(frame, textvariable=pin, show='•')
        entry.pack(fill='x', pady=(4, 14))
        def approve():
            if not self.store.verify_owner_pin(pin.get()):
                raise UserError('Owner PIN is incorrect.')
            result['approved'] = True
            dialog.destroy()
        ttk.Button(frame, text='Approve', command=approve, style='Accent.TButton').pack(side='left')
        ttk.Button(frame, text='Cancel', command=dialog.destroy).pack(side='left', padx=8)
        entry.focus_set()
        self.wait_window(dialog)
        return result['approved']

    def table(self, parent, columns, height=8):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True, pady=8)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='browse', height=height)
        for key, label, width in columns:
            tree.heading(key, text=label, anchor='center')
            tree.column(key, width=width, minwidth=60, anchor='center')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        tree.tag_configure('low', foreground='#8a5a00', background='#fff1c7')
        tree.tag_configure('out', foreground='#a7462d', background='#fbe5dc')
        return tree

    def selected(self, tree):
        selection = tree.selection()
        if not selection:
            raise UserError('Select a product or bill first.')
        if len(selection) != 1:
            raise UserError('Select just one product or bill for this action.')
        return int(selection[0])

    def focus_scan(self, event=None):
        self.show_page('Billing')
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, 'end')
        return 'break'

    def focus_qr(self, event=None):
        self.show_page('Billing')
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, 'end')
        return 'break'

    def build_billing(self):
        frame = self.frames['Billing']
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0, minsize=300)
        frame.rowconfigure(1, weight=1)
        heading = ttk.Frame(frame)
        heading.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        self.item_count = ttk.Label(heading, text='0 items', style='Muted.TLabel')
        self.item_count.pack(side='left', pady=(4, 0))
        self.bill_number_label = ttk.Label(heading, text='Bill #------', foreground='#65736f')
        self.bill_number_label.pack(side='right')
        left = ttk.Frame(frame)
        left.grid(row=1, column=0, sticky='nsew', padx=(0, 16))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        search_card = ttk.LabelFrame(left, text='  FIND PRODUCTS  ', padding=12)
        search_card.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        scanner = ttk.Frame(search_card, style='Card.TFrame')
        scanner.pack(fill='x')
        self.scanner_panel = scanner
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(scanner, textvariable=self.search, font=('Segoe UI', 14))
        self.search_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.search_entry.bind('<Return>', self.enter_product)
        self.search_hint = tk.Label(scanner, text='Search product by name, code, category or brand...', bg='#ffffff', fg='#98a2b3', font=('Segoe UI', 12), cursor='xterm')
        self.search_hint.place(x=11, y=10)
        self.search_hint.bind('<Button-1>', lambda *_: self.search_entry.focus_set())
        self.search_entry.bind('<FocusIn>', lambda *_: self.search_hint.place_forget())
        self.search_entry.bind('<FocusOut>', lambda *_: self.update_search_hint())
        ttk.Button(scanner, text='▣  Scan QR', command=self.open_camera_scanner, style='Accent.TButton').pack(side='right')
        self.qr_status = tk.StringVar(value='Type to search  ·  USB scanner ready  ·  F2 to search')
        self.qr_status_label = ttk.Label(search_card, textvariable=self.qr_status, style='Muted.TLabel')
        self.qr_status_label.pack(anchor='w', pady=(8, 0))
        self.qr_input = None
        self.results = self.table(search_card, [('name','Product',170),('size','Size',80),('code','Code',80),('price','Price',80),('stock','Stock',70),('add','',45)], 3)
        self.results_frame = self.results.master
        self.results_frame.pack_forget()
        self.results.bind('<ButtonRelease-1>', self.click_result)
        self.results.bind('<Return>', lambda e: self.add_product(self.selected(self.results)))
        self.search.trace_add('write', lambda *_: self.refresh_search())
        bill = ttk.LabelFrame(left, text='  ITEMS IN THIS BILL  ', padding=8)
        bill.grid(row=1, column=0, sticky='nsew')
        self.cart_tree = self.table(bill, [('name','Product',170),('size','Size',80),('qty','Qty',55),('unit','Unit',60),('price','Price',80),('total','Total',90)], 5)
        self.cart_tree.bind('<<TreeviewSelect>>', lambda *_: self.update_quantity_display())
        controls = ttk.Frame(left)
        controls.grid(row=2, column=0, sticky='ew', pady=(10, 0))
        self.minus_button = ttk.Button(controls, text='−', width=2, command=lambda: self.change_qty(-1000))
        self.minus_button.pack(side='left')
        self.quantity_display = ttk.Label(controls, text='—', width=4, anchor='center', font=('Segoe UI', 13, 'bold'))
        self.quantity_display.pack(side='left', padx=4)
        self.plus_button = ttk.Button(controls, text='+', width=2, command=lambda: self.change_qty(1000))
        self.plus_button.pack(side='left', padx=(0, 8))
        self.set_quantity_button = self.button(controls, 'Set quantity', self.set_qty)
        self.remove_quantity_button = self.button(controls, 'Remove', self.remove_item)
        checkout = ttk.LabelFrame(frame, text='  PAYMENT  ', padding=(12, 5))
        checkout.grid(row=1, column=1, sticky='nsew')
        checkout.columnconfigure(0, weight=1)
        checkout.rowconfigure(9, weight=1)
        ttk.Label(checkout, text='Bill #', style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        self.payment_bill_number = ttk.Label(checkout, textvariable=tk.StringVar(value=''), style='Card.TLabel')
        self.payment_bill_number.grid(row=0, column=0, sticky='e')
        total_card = ttk.Frame(checkout, style='TotalCard.TFrame', padding=(14, 12))
        total_card.grid(row=1, column=0, sticky='ew', pady=(6, 10))
        ttk.Label(total_card, text='GRAND TOTAL', style='TotalCaption.TLabel').pack(anchor='w')
        self.total_label = ttk.Label(total_card, text='Rs. 0.00', style='Total.TLabel')
        self.total_label.pack(anchor='w', pady=(3, 0))
        subtotal = ttk.Frame(checkout, style='Card.TFrame')
        subtotal.grid(row=2, column=0, sticky='ew', pady=(0, 6))
        ttk.Label(subtotal, text='Subtotal', style='Card.TLabel').pack(side='left')
        self.subtotal_label = ttk.Label(subtotal, text='Rs. 0.00', style='Card.TLabel')
        self.subtotal_label.pack(side='right')
        self.gst_row = ttk.Frame(checkout, style='Card.TFrame')
        self.gst_row.grid(row=3, column=0, sticky='ew', pady=(0, 5))
        self.gst_caption = ttk.Label(self.gst_row, text='GST', style='Card.TLabel')
        self.gst_caption.pack(side='left')
        self.gst_label = ttk.Label(self.gst_row, text='Rs. 0.00', style='Card.TLabel')
        self.gst_label.pack(side='right')
        self.discount = tk.StringVar(value=self.draft['discount'])
        self.discount_mode = tk.StringVar(value=self.draft.get('discount_mode', 'cash'))
        self.discount_type_label = tk.StringVar(value='Cash (Rs.)' if self.discount_mode.get() == 'cash' else 'Percentage (%)')
        self.paid = tk.StringVar(value=self.draft['paid'])
        payment_inputs = ttk.Frame(checkout, style='Card.TFrame')
        payment_inputs.grid(row=4, column=0, sticky='ew')
        payment_inputs.columnconfigure(0, weight=1)
        payment_inputs.columnconfigure(1, weight=1)
        ttk.Label(payment_inputs, text='Discount type', style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        discount_types = ttk.Combobox(payment_inputs, textvariable=self.discount_type_label, values=('Cash (Rs.)', 'Percentage (%)'), state='readonly')
        discount_types.grid(row=1, column=0, sticky='ew', padx=(0, 8), pady=(5, 0))
        ttk.Label(payment_inputs, text='Discount', style='Muted.TLabel').grid(row=0, column=1, sticky='w')
        ttk.Entry(payment_inputs, textvariable=self.discount, width=10).grid(row=1, column=1, sticky='ew', padx=(0, 8), pady=(5, 0))
        ttk.Label(payment_inputs, text='Cash Received (Rs.)', style='Muted.TLabel').grid(row=0, column=2, sticky='w')
        ttk.Entry(payment_inputs, textvariable=self.paid, width=10).grid(row=1, column=2, sticky='ew', pady=(5, 0))
        payment_inputs.columnconfigure(2, weight=1)
        discount_types.bind('<<ComboboxSelected>>', self.discount_type_changed)
        ttk.Label(checkout, text='Leave cash blank for full payment', style='Muted.TLabel').grid(row=5, column=0, sticky='w', pady=(4, 6))
        self.balance_label = ttk.Label(checkout, text='Change Returned: Rs. 0.00', style='Card.TLabel', wraplength=265)
        self.balance_label.grid(row=6, column=0, sticky='w', pady=(0, 8))
        ttk.Separator(checkout).grid(row=7, column=0, sticky='ew', pady=(0, 6))
        customer = ttk.Frame(checkout, style='Card.TFrame')
        customer.grid(row=8, column=0, sticky='ew')
        customer.columnconfigure(0, weight=1)
        self.customer_name = tk.StringVar(value=self.draft.get('customer_name', ''))
        self.customer_phone = tk.StringVar(value=self.draft.get('customer_phone', ''))
        self.customer_open = False
        self.customer_toggle = ttk.Button(customer, text='Customer details (optional)  ▼', command=self.toggle_customer_details)
        self.customer_toggle.grid(row=0, column=0, sticky='ew')
        self.customer_fields = ttk.Frame(customer, style='Card.TFrame')
        self.customer_fields.columnconfigure(0, weight=1)
        for row, label, variable in ((0, 'Customer name', self.customer_name), (2, 'Phone number', self.customer_phone)):
            ttk.Label(self.customer_fields, text=label, style='Muted.TLabel').grid(row=row, column=0, sticky='w', pady=(8, 2))
            ttk.Entry(self.customer_fields, textvariable=variable).grid(row=row + 1, column=0, sticky='ew')
        self.customer_name.trace_add('write', lambda *_: self.persist())
        self.customer_phone.trace_add('write', lambda *_: self.persist())
        self.discount.trace_add('write', self.amount_changed)
        self.paid.trace_add('write', self.amount_changed)
        self.complete_button = ttk.Button(checkout, text='Save & print bill   F9', style='Accent.TButton', command=lambda: self.complete(True))
        self.complete_button.grid(row=11, column=0, sticky='ew', pady=(6, 4))
        actions = ttk.Frame(checkout, style='Card.TFrame')
        actions.grid(row=12, column=0, sticky='ew')
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.save_only_button = ttk.Button(actions, text='Save only', command=lambda: self.complete(False))
        self.save_only_button.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        ttk.Button(actions, text='New bill', command=self.clear_bill).grid(row=0, column=1, sticky='ew')

    def refresh_search(self):
        self.results.delete(*self.results.get_children())
        query = self.search.get().strip()
        if not query:
            self.results_frame.pack_forget()
            return
        self.results_frame.pack(fill='x', pady=(6, 0))
        rows = self.store.products(query)
        for p in rows[:60]:
            stock_text = 'Out of stock' if p['stock_milli'] == 0 else unit_display(p['unit'], p['stock_milli'])
            self.results.insert('', 'end', iid=str(p['id']), values=(p['name'], p['size_variant'] or '—', p['code'], money(p['selling_paisa']), stock_text, 'Add'), tags=('out',) if not p['stock_milli'] else ())
        if not rows:
            self.status.set('No matching products. Try another name or code.')

    def show_developer_scanner_input(self):
        if self.qr_input is None:
            scanner = self.scanner_panel
            self.qr_input = ttk.Entry(scanner, font=('Segoe UI', 13), width=23)
            self.qr_input.bind('<Return>', self.scan_product_code)
            self.qr_input.bind('<KP_Enter>', self.scan_product_code)
            self.qr_input.bind('<FocusIn>', lambda *_: self.qr_status.set('Type to search  ·  USB scanner ready  ·  F2 to search'))
            self.qr_input.pack(fill='x', pady=(4, 0))

    def hide_developer_scanner_input(self):
        if self.qr_input is not None:
            self.qr_input.pack_forget()

    def open_camera_scanner(self):
        if self.camera_window is not None and self.camera_window.winfo_exists():
            self.camera_window.lift()
            return
        camera_setting = self.store.settings().get('camera', 'Default Camera')
        camera_index = int(camera_setting.rsplit(' ', 1)[-1]) if camera_setting.startswith('Camera ') else 0
        capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            messagebox.showwarning('Camera unavailable', 'No camera found. You can search for the product manually.', parent=self)
            return
        detector = cv2.QRCodeDetector()
        self.camera_capture = capture
        dialog = tk.Toplevel(self)
        self.camera_window = dialog
        dialog.title('SCAN PRODUCT QR')
        dialog.geometry('700x570')
        dialog.transient(self)
        dialog.resizable(False, False)
        ttk.Label(dialog, text='SCAN PRODUCT QR', font=('Segoe UI', 18, 'bold')).pack(pady=(16, 4))
        ttk.Label(dialog, text='Point the QR code at the laptop camera').pack(pady=(0, 10))
        preview = tk.Label(dialog, bg='black')
        preview.pack(padx=18, fill='both', expand=True)
        feedback = tk.StringVar(value='Camera ready')
        ttk.Label(dialog, textvariable=feedback, foreground='#a7462d', font=('Segoe UI', 12, 'bold')).pack(pady=8)
        state = {'locked': False, 'closed': False}

        def close_camera():
            if state['closed']:
                return
            state['closed'] = True
            capture.release()
            self.camera_capture = None
            self.camera_window = None
            dialog.destroy()

        def read_frame():
            if state['closed']:
                return
            ok, frame = capture.read()
            if not ok:
                feedback.set('Camera could not be opened.')
                dialog.after(100, read_frame)
                return
            frame = cv2.flip(frame, 1)
            data, _, _ = detector.detectAndDecode(frame)
            height, width = frame.shape[:2]
            cv2.rectangle(frame, (width // 2 - 140, height // 2 - 140), (width // 2 + 140, height // 2 + 140), (255, 255, 255), 2)
            cv2.putText(frame, 'QR HERE', (width // 2 - 48, height // 2 + 170), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            success, encoded = cv2.imencode('.png', frame)
            if success:
                image = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()))
                preview.configure(image=image)
                preview.image = image
            if data and not state['locked']:
                state['locked'] = True
                product = self.store.exact(data.strip())
                if product is None:
                    state['locked'] = False
                    feedback.set('✕ Product not found')
                    dialog.after(900, lambda: feedback.set('Camera ready'))
                else:
                    self.scan_qr(data.strip())
                    close_camera()
            if not state['closed']:
                dialog.after(30, read_frame)

        ttk.Button(dialog, text='Cancel', command=close_camera).pack(pady=(0, 14))
        dialog.protocol('WM_DELETE_WINDOW', close_camera)
        read_frame()

    def scan_qr_prompt(self):
        self.show_page('Billing')
        self.search_entry.focus_set()
        text = simpledialog.askstring('Scan QR code', 'Enter or paste the QR/product code scanned at the register:', parent=self)
        if text is not None:
            self.scan_qr(text)

    def scan_qr(self, value):
        text = str(value or '').strip()
        if not text:
            return
        self.show_page('Billing')
        self._process_scan(text)

    def _process_scan(self, text):
        if getattr(self, 'qr_reset_job', None) is not None:
            self.after_cancel(self.qr_reset_job)
        product = self.store.exact(text)
        if product is None:
            self.status.set('Product not found')
            if self.qr_input is not None:
                self.qr_input.focus_set()
            self.qr_status.set('✕ Product not found')
            self.qr_reset_job = self.after(1400, lambda: self.qr_status.set('Type to search  ·  USB scanner ready  ·  F2 to search'))
            return {'ok': False, 'message': '✕ Product not found'}
        self.add_product(product['id'])
        if self.qr_input is not None:
            self.qr_input.delete(0, 'end')
            self.qr_input.focus_set()
        self.qr_status.set(f'✓ {product["name"]} added')
        self.qr_reset_job = self.after(1400, lambda: self.qr_status.set('Type to search  ·  USB scanner ready  ·  F2 to search'))
        return {'ok': True, 'message': f'✓ {product["name"]} added\nReady for next product...'}

    def scan_product_code(self, event=None):
        if self.qr_input is None:
            return 'break'
        text = self.qr_input.get().strip()
        self.qr_input.delete(0, 'end')
        if not text:
            self.qr_status.set('Type to search  ·  USB scanner ready  ·  F2 to search')
            return 'break'
        self._process_scan(text)
        return 'break'

    def enter_product(self, event=None):
        text = self.search.get().strip()
        if not text:
            return 'break'
        product = self.store.exact(text)
        matches = self.store.products(text) if product is None else []
        if product is not None:
            self.add_product(product['id'])
        elif len(matches) == 1:
            self.add_product(matches[0]['id'])
        else:
            self.status.set('Choose a matching product below.' if matches else 'Product not found. Check the code or add it in Products.')
        return 'break'

    def click_result(self, event):
        item = self.results.identify_row(event.y)
        if item and self.results.identify_region(event.x, event.y) in ('cell','tree'):
            self.add_product(int(item))

    def add_product(self, product_id):
        self.require('billing.create')
        p = self.store.product(product_id)
        existing = next((i for i in self.cart if i['id'] == product_id), None)
        qty = (existing['qty'] if existing else 0) + 1000
        if qty > p['stock_milli']:
            if not existing and 0 < p['stock_milli'] < 1000:
                qty = p['stock_milli']
            else:
                raise UserError(f"Only {quantity(p['stock_milli'])} {p['unit']} available.")
        if existing:
            existing['qty'] = qty
        else:
            self.cart.append({'id':product_id,'name':p['name'],'size_variant':p['size_variant'],'unit':p['unit'],'price':p['selling_paisa'],'qty':qty})
        self.search.set('')
        self.refresh_cart()
        self.persist()
        self.cart_tree.selection_set(str(product_id))
        self.status.set(f"✓ {p['name']} added")
        self.search_entry.focus_set()

    def cart_item(self):
        product_id = self.selected(self.cart_tree)
        return next(i for i in self.cart if i['id'] == product_id)

    def update_quantity_display(self):
        try:
            self.quantity_display.configure(text=quantity(self.cart_item()['qty']))
            state = 'normal'
        except UserError:
            self.quantity_display.configure(text='—')
            state = 'disabled'
        for control in (self.minus_button, self.plus_button, self.set_quantity_button, self.remove_quantity_button):
            control.configure(state=state)

    def change_selected_quantity(self, delta):
        try:
            item = self.cart_item()
            self.apply_qty(item, item['qty'] + delta)
        except UserError:
            raise
        except Exception:
            return 'break'

    def change_qty(self, delta):
        item = self.cart_item()
        self.apply_qty(item, item['qty'] + delta)

    def set_qty(self):
        item = self.cart_item()
        value = simpledialog.askstring('Quantity', f"Quantity of {item['name']} ({item['unit']}):", initialvalue=quantity(item['qty']), parent=self)
        if value is not None:
            self.apply_qty(item, scaled(value, 1000, 'Quantity', positive=True))

    def remove_selected_item(self):
        try:
            item = self.cart_item()
            self.cart.remove(item)
            self.refresh_cart()
            self.persist()
        except Exception:
            return 'break'

    def apply_qty(self, item, qty):
        if qty <= 0:
            raise UserError('Use Remove item to remove this product.')
        if qty > self.store.product(item['id'])['stock_milli']:
            raise UserError('Not enough stock for this quantity.')
        item['qty'] = qty
        self.refresh_cart()
        self.cart_tree.selection_set(str(item['id']))
        self.persist()

    def remove_item(self):
        item = self.cart_item()
        self.cart.remove(item)
        self.refresh_cart()
        self.persist()

    def clear_bill(self):
        if self.cart and not messagebox.askyesno('Clear bill?', 'Remove all items from this unfinished bill?', parent=self):
            return
        self.new_bill()
        self.persist()

    def new_bill(self):
        self.cart = []
        self.draft['token'] = str(uuid.uuid4())
        self.discount.set('0')
        self.discount_mode.set('cash')
        self.discount_type_label.set('Cash (Rs.)')
        self.paid.set('')
        self.customer_name.set('')
        self.customer_phone.set('')
        self.refresh_cart()

    def persist(self):
        self.store.save_draft({'cart':self.cart,'discount':self.discount.get(),'discount_mode':self.discount_mode.get(),'paid':self.paid.get(),'customer_name':self.customer_name.get(),'customer_phone':self.customer_phone.get(),'token':self.draft['token']})

    def amount_changed(self, *_):
        self.refresh_totals()
        self.persist()

    def discount_type_changed(self, _=None):
        self.discount_mode.set('percent' if self.discount_type_label.get() == 'Percentage (%)' else 'cash')
        self.amount_changed()

    def refresh_cart(self):
        self.cart_tree.delete(*self.cart_tree.get_children())
        for i in self.cart:
            self.cart_tree.insert('', 'end', iid=str(i['id']), values=(i['name'],i.get('size_variant') or '—',quantity(i['qty']),i['unit'],money(i['price']),money(line_total(i['price'],i['qty']))))
        self.refresh_totals()
        self.update_quantity_display()
        self.item_count.configure(text=f'{len(self.cart)} item' + ('' if len(self.cart) == 1 else 's'))
        has_selection = bool(self.cart_tree.selection())
        state = 'normal' if has_selection else 'disabled'
        for control in (self.minus_button, self.plus_button, self.set_quantity_button, self.remove_quantity_button):
            control.configure(state=state)

    def refresh_totals(self):
        subtotal = sum(line_total(i['price'],i['qty']) for i in self.cart)
        try:
            if self.discount_mode.get() == 'cash':
                discount = scaled(self.discount.get(), label='Discount')
            elif self.discount_mode.get() == 'percent':
                percent = scaled(self.discount.get(), label='Discount percentage')
                if percent > 10000:
                    raise UserError('Discount percentage cannot be more than 100%.')
                discount = int((Decimal(subtotal) * percent / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            else:
                raise UserError('Choose a valid discount type.')
            if discount > subtotal:
                raise UserError('Discount cannot exceed the subtotal.')
            total = subtotal - discount
            paid = scaled(self.paid.get(), label='Amount paid') if self.paid.get().strip() else total
            self.subtotal_label.configure(text=f'Rs. {money(subtotal)}')
            settings = self.store.settings()
            tax_enabled = settings.get('tax_enabled', 'Off') == 'On'
            taxable = subtotal - discount
            gst = int((Decimal(taxable) * scaled(settings.get('gst_rate', '18'), 100, 'GST rate') / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if tax_enabled else 0
            shown_total = taxable + gst
            self.gst_row.grid() if tax_enabled else self.gst_row.grid_remove()
            self.gst_caption.configure(text=f"{settings.get('tax_label', 'GST')} ({settings.get('gst_rate', '18')}%)")
            self.gst_label.configure(text=f'Rs. {money(gst)}')
            self.total_label.configure(text=f'Rs. {money(shown_total)}')
            self.balance_label.configure(text=f"{'Balance Due' if paid < shown_total else 'Change Returned'}: Rs. {money(abs(shown_total - paid))}")
            state = 'normal' if self.cart else 'disabled'
            self.complete_button.configure(state=state)
            self.save_only_button.configure(state=state)
        except UserError as error:
            self.subtotal_label.configure(text=f'Rs. {money(subtotal)}')
            self.total_label.configure(text=f'Rs. {money(subtotal)}')
            self.balance_label.configure(text=str(error))
            self.complete_button.configure(state='disabled')
            self.save_only_button.configure(state='disabled')

    def complete(self, print_receipt=True):
        # Guard: prevent double-submit if the user clicks again while saving
        if getattr(self, '_completing', False):
            return
        self._completing = True
        self.complete_button.configure(state='disabled')
        self.save_only_button.configure(state='disabled')
        try:
            self._do_complete(print_receipt)
        finally:
            self._completing = False
            # Buttons are re-enabled by refresh_totals() at the end of _do_complete,
            # or re-enabled here on exception so the user can try again.
            if getattr(self, '_completing_failed', False):
                self._completing_failed = False
                self.refresh_totals()

    def _do_complete(self, print_receipt=True):
        self.require('billing.create')
        if self.store.current_user and self.discount.get().strip() not in ('', '0', '0.0', '0.00') and not self.store.allowed('billing.discount'):
            if not self.owner_approval('Discount approval', 'This user cannot give a discount without the Owner PIN.'):
                raise UserError('Owner approval is required for this discount.')

        # ── DEV TIMING ────────────────────────────────────────────────
        _t0 = self._dev_time() if self.development_mode else None

        try:
            sale_id = self.store.complete_sale(
                self.cart, self.discount.get(), self.paid.get(),
                self.draft['token'], self.customer_name.get(),
                self.customer_phone.get(), self.discount_mode.get()
            )
        except Exception:
            self._completing_failed = True
            raise

        _t1 = self._dev_time() if self.development_mode else None
        if self.development_mode and _t0 is not None:
            logging.warning('[DEV] complete_sale DB write: %.1f ms', (_t1 - _t0) * 1000)

        # ── SALE IS NOW PERMANENTLY SAVED ─────────────────────────────
        # Do NOT call refresh_inventory() here — it takes ~170ms for 5000 products
        # and is only needed if the user switches to Stock page. Mark dirty instead.
        self._inventory_dirty = True
        self._products_dirty = True

        self.new_bill()
        self.refresh_cart()
        self.refresh_sales()
        next_id = self.store.next_sale_number()
        self.bill_number_label.configure(text=f'Bill #{next_id:06d}')
        self.payment_bill_number.configure(text=f'Bill #{next_id:06d}')
        self.status.set(f'Bill #{sale_id:06d} saved. Stock updated.')
        self.search_entry.focus_set()

        _t2 = self._dev_time() if self.development_mode else None
        if self.development_mode and _t1 is not None:
            logging.warning('[DEV] refresh after save: %.1f ms', (_t2 - _t1) * 1000)

        # ── PRINTING (always after DB is committed) ────────────────────
        should_print = print_receipt or self.store.settings().get('auto_print') == 'On'
        if should_print:
            self._open_receipt_after_save(sale_id, auto_print=not print_receipt)

        _t3 = self._dev_time() if self.development_mode else None
        if self.development_mode and _t2 is not None:
            logging.warning('[DEV] open_receipt: %.1f ms', (_t3 - _t2) * 1000)

    def _open_receipt_after_save(self, sale_id, auto_print=False):
        """Open the receipt preview. If printing fails the bill is still saved — show Reprint option."""
        if not self.store.allowed('billing.reprint') and not self.store.allowed('sales.reprint'):
            # User cannot reprint — just skip; the bill is saved in Sales History
            return
        try:
            settings = self.store.settings()
            import json
            sale, _ = self.store.sale(sale_id)
            settings = dict(settings)
            settings['shop_logo'] = json.loads(sale['shop_json']).get('shop_logo', '')

            _t0 = self._dev_time() if self.development_mode else None
            text = receipt_text(self.store, sale_id)
            _t1 = self._dev_time() if self.development_mode else None
            if self.development_mode and _t0 is not None:
                logging.warning('[DEV] receipt_text generation: %.1f ms  (%d chars)', (_t1 - _t0) * 1000, len(text))

            win = preview(self, f'Bill {receipt_number(sale_id)}', text, settings=settings, auto_print=auto_print)

            # Patch finish_print in the preview window to show a "saved but not printed" message
            # that includes the bill number and a Reprint button.
            if win is not None:
                original_finish = win._finish_print if hasattr(win, '_finish_print') else None
                def _patched_finish(success, error=None, _sale_id=sale_id, _win=win):
                    if not _win.winfo_exists():
                        return
                    if not success:
                        # Bill is already saved — show helpful message with Reprint option
                        self._show_print_failed_dialog(_sale_id)
                # Attach so preview can call it; but preview already has its own finish_print.
                # We instead monitor via the status label approach already in preview().
                # The existing printing.py already shows an error dialog — we enhance here
                # by additionally offering Reprint from Sales History.

        except Exception:
            logging.error('Failed to open receipt for Bill #%06d', sale_id, exc_info=True)

    def _show_print_failed_dialog(self, sale_id):
        """Show a dialog when printing fails after a successful save."""
        import tkinter as tk
        dialog = tk.Toplevel(self)
        dialog.title('Bill saved — Print failed')
        dialog.transient(self)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f'Bill #{sale_id:06d} was saved successfully,\nbut the receipt could not be printed.',
                  font=('Segoe UI', 12), justify='center').pack(pady=(0, 16))
        ttk.Label(frame, text='You can reprint from Sales History at any time.',
                  style='Muted.TLabel', justify='center').pack(pady=(0, 20))
        btn_row = ttk.Frame(frame)
        btn_row.pack()
        ttk.Button(btn_row, text='Reprint', style='Accent.TButton',
                   command=lambda: (dialog.destroy(), self.open_receipt(sale_id))).pack(side='left', padx=(0, 8))
        ttk.Button(btn_row, text='Close', command=dialog.destroy).pack(side='left')
        dialog.grab_set()

    def _dev_time(self):
        import time
        return time.perf_counter()

    def open_receipt(self, sale_id, auto_print=False):

        if not self.store.allowed('billing.reprint') and not self.store.allowed('sales.reprint'):
            self.require('billing.reprint')
        settings = self.store.settings()
        import json
        sale, _ = self.store.sale(sale_id)
        settings['shop_logo'] = json.loads(sale['shop_json']).get('shop_logo', '')
        preview(self, f'Bill {receipt_number(sale_id)}', receipt_text(self.store, sale_id), settings=settings, auto_print=auto_print)

    def generate_qr_value(self, code):
        value = str(code or '').strip()
        return value.upper() if value else ''

    def build_products(self):
        frame = self.frames['Products']
        ttk.Label(frame,text='Products',font=('Segoe UI',19,'bold')).pack(anchor='w')
        self.product_search = tk.StringVar()
        ttk.Entry(frame,textvariable=self.product_search).pack(fill='x',pady=8)
        self.product_search.trace_add('write',lambda *_:self.refresh_products())
        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        self.button(controls,'+ Add product',lambda:self.product_dialog(),True)
        self.button(controls,'Edit product',lambda:self.product_dialog(self.selected(self.product_tree)))
        self.button(controls,'Delete product',self.delete_product)
        self.button(controls,'Delete all products',self.delete_all_products)
        self.button(controls,'View QR',self.view_label)
        self.button(controls,'Print QR',self.print_label)
        self.product_tree = self.table(frame,[('name','Product',210),('size','Size',100),('code','Code',100),('category','Category',120),('brand','Brand',110),('unit','Unit',80),('price','Selling Price',110),('stock','Stock',90)])
        self.product_tree.configure(selectmode='extended')
        batch = ttk.Frame(frame)
        batch.pack(fill='x')
        self.button(batch, 'Select all products', self.select_all_products)
        self.button(batch, 'Download selected QR labels', self.download_labels, True)
        self.product_tree.bind('<Double-1>',lambda e:self.product_dialog(self.selected(self.product_tree)))
        ttk.Label(frame,text='QR values are generated from each product code/SKU so they stay stable and offline.').pack(anchor='w')

    def select_all_products(self):
        self.product_search.set('')
        self.refresh_products(immediate=True)
        self.product_tree.selection_set(self.product_tree.get_children())

    def download_labels(self):
        self.require('products.print_qr')
        from .labels import export_labels
        selected = self.product_tree.selection()
        if not selected:
            raise UserError('Select products first, or click Select all products.')
        copies = simpledialog.askinteger('QR labels', 'Copies of each selected product:', initialvalue=1, minvalue=1, maxvalue=100, parent=self)
        if copies is None:
            return
        path = filedialog.asksaveasfilename(parent=self, title='Save QR labels (20 x 20 mm + product code)', defaultextension='.pdf', initialfile='product-qr-labels.pdf', filetypes=[('PDF labels', '*.pdf')])
        if path:
            count = export_labels([self.store.product(int(key)) for key in selected], path, copies)
            messagebox.showinfo('QR labels saved', f'{count} labels saved. Print on A4 paper at Actual size / 100%. Each QR square is 20 x 20 mm, with its product code below.', parent=self)

    def render_rows(self, table, rows, immediate=False):
        jobs = getattr(self, '_table_jobs', {})
        self._table_jobs = jobs
        old = jobs.pop(table, None)
        if old: self.after_cancel(old)
        table.delete(*table.get_children())
        iterator = iter(rows)
        def batch():
            jobs.pop(table, None)
            for _ in range(len(rows) if immediate else 100):
                row = next(iterator, None)
                if row is None: return
                table.insert('', 'end', **row)
            if not immediate:
                jobs[table] = self.after(1, batch)
        batch()

    def refresh_products(self, immediate=False):
        rows = [dict(iid=str(p['id']),values=(p['name'],p['size_variant'] or '—',p['code'],p['category'],p['brand'],p['unit'],money(p['selling_paisa']),quantity(p['stock_milli']))) for p in self.store.products(self.product_search.get())]
        self.render_rows(self.product_tree,rows,immediate)

    def product_dialog(self, product_id=None):
        self.require('products.edit' if product_id else 'products.add')
        p = self.store.product(product_id) if product_id else None
        dialog = tk.Toplevel(self)
        dialog.title('Edit product' if p else 'Add product')
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog,padding=22)
        frame.pack(fill='both',expand=True)
        fields = [('name','Product name *'),('code','Product code / SKU *'),('qr','QR value (blank = product code)'),('category','Category'),('brand','Brand'),('size_variant','Size / Variant (optional)'),('purchase','Purchase price (Rs.) *'),('selling','Selling price (Rs.) *'),('stock','Available quantity *'),('unit','Unit *'),('description','Description (optional)')]
        variables = {}
        for row,(key,label) in enumerate(fields):
            value = (str(p[{'purchase':'purchase_paisa','selling':'selling_paisa'}[key]]/100) if key in ('purchase','selling') else quantity(p['stock_milli']) if key=='stock' else p[key]) if p else {'purchase':'0','selling':'0','stock':'0','unit':'Piece'}.get(key,'')
            variables[key] = tk.StringVar(value=value)
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5,padx=(0,18))
            entry = ttk.Combobox(frame,textvariable=variables[key],values=('Piece','Box','Set','Meter','Pack','Pair'),width=34) if key=='unit' else ttk.Entry(frame,textvariable=variables[key],width=37)
            entry.grid(row=row,column=1,sticky='ew',pady=5)
            if row==0:
                entry.focus_set()
        def sync_qr_from_code(*_):
            if not variables['qr'].get().strip():
                variables['qr'].set(self.generate_qr_value(variables['code'].get()))
        variables['code'].trace_add('write', sync_qr_from_code)
        chosen_image = [None]
        image_label = ttk.Label(frame, text='Optional photo: PNG or GIF, up to 5 MB')
        image_label.grid(row=len(fields), column=1, sticky='w')
        def show_image(data):
            photo = tk.PhotoImage(data=base64.b64encode(data))
            factor = max(1, (max(photo.width(), photo.height()) + 119) // 120)
            photo = photo.subsample(factor)
            image_label.configure(image=photo, text='')
            image_label.image = photo
        if p:
            saved_image = self.store.conn.execute('SELECT image FROM product_images WHERE product_id=?', (product_id,)).fetchone()
            if saved_image:
                show_image(saved_image[0])
        def choose_image():
            path = filedialog.askopenfilename(parent=dialog, title='Choose product photo', filetypes=[('Product photo', '*.png *.gif')])
            if path:
                if Path(path).stat().st_size > 5 * 1024 * 1024:
                    raise UserError('Choose a photo smaller than 5 MB.')
                data = Path(path).read_bytes()
                try:
                    show_image(data)
                except tk.TclError:
                    raise UserError('Choose a valid PNG or GIF photo.') from None
                chosen_image[0] = data
        ttk.Button(frame, text='Choose photo', command=choose_image).grid(row=len(fields), column=0, pady=8)
        def save():
            variables['qr'].set(self.generate_qr_value(variables['qr'].get() or variables['code'].get()))
            self.store.save_product({k:v.get() for k,v in variables.items()} | {'image': chosen_image[0]},product_id)
            dialog.destroy()
            self.refresh_all()
            self.status.set('Product saved.')
        ttk.Button(frame,text='Save product',command=save,style='Accent.TButton').grid(row=len(fields)+1,column=1,sticky='ew',pady=(15,0))
        ttk.Button(frame,text='Cancel',command=dialog.destroy).grid(row=len(fields)+1,column=0,sticky='w',pady=(15,0))

    def delete_product(self):
        self.require('products.delete')
        product_id = self.selected(self.product_tree)
        if any(i['id']==product_id for i in self.cart):
            raise UserError('Remove this product from the unfinished bill before deleting it.')
        if messagebox.askyesno('Delete product?', 'Remove this product from the product list? Previous bills will be kept.',parent=self):
            self.store.archive(product_id)
            self.refresh_all()
            self.status.set('Product deleted. Previous bills are unchanged.')

    def delete_all_products(self):
        self.require('products.delete')
        if self.cart:
            raise UserError('Clear or save the unfinished bill before deleting all products.')
        if not messagebox.askyesno(
            'Delete all products?',
            'Remove every product from the product list? Previous bills, returns and stock records will be kept. This cannot be undone from the product screen.',
            parent=self,
        ):
            return
        count = self.store.archive_all_products()
        self.refresh_all()
        self.status.set(f'{count} products deleted. Previous bills are unchanged.')

    def view_label(self):
        self.require('products.print_qr')
        product = self.store.product(self.selected(self.product_tree))
        preview(self, 'Product QR label', product['code'], product['qr'])

    def generate_selected_qr(self):
        self.require('products.edit')
        product = self.store.product(self.selected(self.product_tree))
        updated = self.generate_qr_value(product['code'])
        self.store.save_product(product | {'qr': updated, 'code': product['code'], 'name': product['name'], 'category': product['category'], 'brand': product['brand'], 'purchase': str(product['purchase_paisa'] / 100), 'selling': str(product['selling_paisa'] / 100), 'stock': str(product['stock_milli'] / 1000), 'unit': product['unit'], 'description': product['description']}, product['id'])
        self.refresh_all()
        self.status.set(f'QR generated for {product["name"]}.')

    def print_label(self):
        self.require('products.print_qr')
        product = self.store.product(self.selected(self.product_tree))
        preview(self, 'Product QR labels', product['code'], product['qr'])

    def build_inventory(self):
        frame = self.frames['Stock']
        ttk.Label(frame,text='Stock',font=('Segoe UI',19,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Amber = low stock     Red = out of stock').pack(anchor='w',pady=8)
        summary = ttk.Frame(frame)
        summary.pack(fill='x', pady=(0, 12))
        self.stock_summary = {}
        for key, title in (('products', 'Total Products'), ('low', 'Low Stock'), ('out', 'Out of Stock')):
            card = ttk.LabelFrame(summary, text=title, padding=(14, 8))
            card.pack(side='left', fill='x', expand=True, padx=(0, 10))
            value = ttk.Label(card, text='0', font=('Segoe UI', 18, 'bold'))
            value.pack(anchor='w')
            self.stock_summary[key] = value
        self.stock_filter = tk.StringVar(value='all')
        filters = ttk.Frame(frame)
        filters.pack(fill='x', pady=6)
        for label, value in (('All Products','all'),('Low Stock','low'),('Out of Stock','out')):
            ttk.Radiobutton(filters,text=label,variable=self.stock_filter,value=value,command=self.refresh_inventory).pack(side='left',padx=(0,16))
        self.stock_search = tk.StringVar()
        ttk.Entry(frame,textvariable=self.stock_search).pack(fill='x')
        self.stock_search.trace_add('write',lambda *_:self.refresh_inventory())
        controls=ttk.Frame(frame)
        controls.pack(fill='x')
        self.button(controls,'Increase stock',lambda:self.stock_dialog(True),True)
        self.button(controls,'Decrease stock',lambda:self.stock_dialog(False))
        self.stock_tree=self.table(frame,[('name','Product',240),('code','Code',100),('category','Category',120),('price','Price (Rs.)',110),('stock','Current stock',120),('unit','Unit',80),('state','Stock status',120)])

    def refresh_inventory(self):
        self.stock_tree.delete(*self.stock_tree.get_children())
        limit = scaled(self.store.settings()['low_stock'], 1000)
        rows = self.store.products(self.stock_search.get())
        total, low, out = self.store.stock_summary(limit)
        self.stock_summary['products'].configure(text=str(total))
        self.stock_summary['low'].configure(text=str(low))
        self.stock_summary['out'].configure(text=str(out))
        rendered = []
        for p in rows:
            if self.stock_filter.get() == 'low' and not 0 < p['stock_milli'] <= limit: continue
            if self.stock_filter.get() == 'out' and p['stock_milli'] != 0: continue
            state = 'Out of stock' if p['stock_milli'] == 0 else 'Low stock' if p['stock_milli'] <= limit else 'Available'
            rendered.append(dict(iid=str(p['id']), values=(p['name'], p['code'], p['category'], money(p['selling_paisa']), quantity(p['stock_milli']), p['unit'], state), tags=('out',) if p['stock_milli'] == 0 else ('low',) if p['stock_milli'] <= limit else ()))
        self.render_rows(self.stock_tree,rendered)


    def stock_dialog(self, increase):
        self.require('stock.increase' if increase else 'stock.decrease')
        product_id=self.selected(self.stock_tree)
        p=self.store.product(product_id)
        current = p['stock_milli']
        amount=simpledialog.askstring('Stock change',f"Product: {p['name']}\nCurrent stock: {quantity(current)} {p['unit']}\nQuantity to {'add' if increase else 'remove'}:",parent=self)
        if amount is None:
            return
        change = scaled(amount,1000,'Stock change',positive=True)
        new_stock = current + change if increase else current - change
        if not increase and new_stock < 0:
            raise UserError('Quantity to remove cannot exceed current stock.')
        if not increase and (change >= current or change * 2 >= current):
            if not messagebox.askyesno('Confirm stock reduction', f'Product: {p["name"]}\nCurrent stock: {quantity(current)}\nNew stock: {quantity(new_stock)}\n\nRemove this quantity?', parent=self):
                return
        reason=simpledialog.askstring('Reason','Reason (for example: new delivery, damaged or correction):',parent=self)
        if reason is not None:
            self.store.adjust_stock(product_id,amount,increase,reason)
            self.refresh_all()
            self.status.set('Stock updated.')

    def build_sales(self):
        frame=self.frames['Sales']
        self.today=ttk.Label(frame,font=('Segoe UI',22,'bold'),foreground='#176b67')
        self.today.pack(anchor='w',pady=(0,18))
        self.today_bills=ttk.Label(frame,font=('Segoe UI',12,'bold'),foreground='#59636e')
        self.today_bills.pack(anchor='w',pady=(0,10))
        filters=ttk.Frame(frame)
        filters.pack(fill='x')
        self.bill_filter,self.date_filter,self.customer_filter=tk.StringVar(),tk.StringVar(),tk.StringVar()
        for label,var in (('Bill number',self.bill_filter),('Date (YYYY-MM-DD)',self.date_filter),('Customer / Phone',self.customer_filter)):
            ttk.Label(filters,text=label).pack(side='left',padx=(0,8))
            ttk.Entry(filters,textvariable=var,width=17).pack(side='left',padx=(0,12))
        self.button(filters,'Search',self.refresh_sales)
        self.button(filters,'Show all',self.clear_sales_filters)
        self.sale_tree=self.table(frame,[('code','Bill number',140),('date','Date & time',220),('total','Total (Rs.)',140),('paid','Paid (Rs.)',140),('balance','Balance due (Rs.)',150)])
        self.sale_tree.configure(selectmode='extended')
        self.sale_tree.bind('<Double-1>',lambda e:self.open_sale(self.selected(self.sale_tree)))
        controls=ttk.Frame(frame)
        controls.pack(fill='x')
        self.button(controls,'Open / View bill',lambda:self.open_sale(self.selected(self.sale_tree)),True)
        self.button(controls, 'Clear selected sales', self.delete_selected_sales)
        self.button(controls, 'Clear all sales', lambda: self.delete_selected_sales(True))
        returns = ttk.Frame(frame); returns.pack(fill='x')
        self.button(returns, 'Return items / bill', self.return_dialog)
        self.button(returns, 'Reprint return slip', self.reprint_return)
        self.button(returns, 'View Returns', self.open_returns)

    def delete_selected_sales(self, clear_all=False):
        self.require('sales.cancel')
        ids = None if clear_all else [int(key) for key in self.sale_tree.selection()]
        if not clear_all and not ids:
            raise UserError('Select the bills you want to delete.')
        description = 'ALL visible sales' if clear_all else f'{len(ids)} selected bill(s)'
        if not messagebox.askyesno('Clear sales history?', f'Clear {description} from this sales screen? Sales totals will reset and stock will stay the same. Returned bills are archived for audit history. A safety backup will be saved first.', parent=self):
            return
        safety = self.store.delete_sales(ids)
        self.refresh_all()
        self.status.set(f'Sales history cleared. Stock unchanged. Backup: {safety.name}')

    def clear_sales_filters(self):
        self.bill_filter.set('')
        self.date_filter.set('')
        self.customer_filter.set('')
        self.refresh_sales()

    def refresh_sales(self):
        day=self.date_filter.get().strip()
        if day:
            try:
                if date.fromisoformat(day).isoformat()!=day:
                    raise ValueError()
            except ValueError:
                raise UserError('Enter a date like 2026-09-15.') from None
        bill=self.bill_filter.get().strip()
        if bill and not bill.lstrip('#').isdigit():
            raise UserError('Enter a bill number, such as 000001.')
        gross, refunds, net = self.store.sales_totals(day)
        scope = date.fromisoformat(day).strftime('%d %b %Y') if day else 'All sales'
        self.today.configure(text=f"{scope}  ·  Gross: Rs. {money(gross)}  ·  Returns: Rs. {money(refunds)}  ·  Net: Rs. {money(net)}")
        today_count = self.store.conn.execute("SELECT count(*) FROM sales WHERE archived=0 AND substr(created_at,1,10)=?", (date.today().isoformat(),)).fetchone()[0]
        self.today_bills.configure(text=f"Today's bills: {today_count}")
        self.sale_tree.delete(*self.sale_tree.get_children())
        for sale in self.store.sales(bill,day,self.customer_filter.get().strip()):
            status = self.store.sale_return_status(sale['id'])
            self.sale_tree.insert('','end',iid=str(sale['id']),values=(f"#{sale['id']:06d} · {status}",human_datetime(sale['created_at']),money(sale['total_paisa']),money(sale['paid_paisa']),money(max(0,sale['total_paisa']-sale['paid_paisa']))))

    def build_settings(self):
        frame=self.frames['Settings']
        ttk.Label(frame,text='Shop settings',font=('Segoe UI',19,'bold')).pack(anchor='w',pady=(0,16))
        logo_row = ttk.Frame(frame)
        logo_row.pack(fill='x', pady=(0, 12))
        self.logo_preview = ttk.Label(logo_row, text='No shop logo')
        self.logo_preview.pack(side='left', padx=(0, 16))
        self.button(logo_row, 'Add / change shop logo', self.choose_shop_logo)
        self.button(logo_row, 'Remove logo', lambda: self.set_shop_logo(''))
        self.refresh_shop_logo()
        form=ttk.Frame(frame)
        form.pack(anchor='w',fill='x')
        self.setting_vars={}
        for row,(key,label) in enumerate((('shop_name','Shop Name'),('address','Address'),('phone','Phone Number'),('ntn','NTN / Tax Number'),('footer','Receipt Footer'),('printer','Printer'),('paper','Receipt Paper'),('copies','Number of Copies'),('auto_print','Auto Print After Sale'),('camera','Camera'),('low_stock','Low Stock Warning'),('tax_enabled','Enable GST'),('gst_rate','GST Rate (%)'),('tax_label','Tax Label'))):
            section = row // 7
            row = row % 7
            var=tk.StringVar(value=self.store.settings()[key])
            self.setting_vars[key]=var
            ttk.Label(form,text=label).grid(row=row,column=section*2,sticky='w',pady=5,padx=(12,10))
            if key == 'paper':
                widget=ttk.Combobox(form,textvariable=var,values=('58mm','80mm'),state='readonly',width=20)
            elif key == 'auto_print':
                widget=ttk.Combobox(form,textvariable=var,values=('On','Off'),state='readonly',width=20)
            elif key == 'tax_enabled':
                widget=ttk.Combobox(form,textvariable=var,values=('On','Off'),state='readonly',width=20)
            elif key == 'camera':
                widget=ttk.Combobox(form,textvariable=var,values=('Default Camera','Camera 0','Camera 1','Camera 2'),state='readonly',width=20)
            elif key == 'printer':
                widget=ttk.Combobox(form,textvariable=var,values=installed_printers(),state='readonly',width=20)
            elif key == 'copies':
                widget=ttk.Spinbox(form,textvariable=var,from_=1,to=100,width=20)
            else:
                widget=ttk.Entry(form,textvariable=var,width=23)
            widget.grid(row=row,column=section*2+1,sticky='ew',pady=5)
        controls=ttk.Frame(frame)
        controls.pack(fill='x',pady=12)
        self.button(controls,'Save settings',self.save_settings,True)
        self.button(controls,'Update application',self.update_application)
        self.button(controls,'Software Update',self.open_software_update)
        self.button(controls,'Test print',self.test_print)
        if self.development_mode:
            self.button(controls,'⚡ Print Stress Test',self.print_stress_test)
        self.button(controls,'Users & Privileges',self.open_users)
        self.button(controls,'About & License',self.open_license_info)
        self.button(controls,'Audit history',self.open_audit_history)
        self.settings_status = tk.StringVar(value='')
        ttk.Label(frame, textvariable=self.settings_status, foreground='#176b67').pack(anchor='w')
        update_box = ttk.LabelFrame(frame, text='Software Update', padding=12)
        update_box.pack(fill='x', pady=(8, 0))
        ttk.Label(update_box, text=f'Current version: {APP_VERSION}').pack(side='left')
        ttk.Label(update_box, text='Updates are optional and do not affect offline POS operation.').pack(side='left', padx=20)
        self.update_status = tk.StringVar(value='Not checked')
        ttk.Label(update_box, textvariable=self.update_status, foreground='#176b67').pack(side='left', padx=12)
        self.button(update_box, 'Check for Updates', self.open_software_update)
        auto_check = tk.BooleanVar(value=self.store.settings().get('update_auto_check', 'On') == 'On')
        auto_toggle = ttk.Checkbutton(update_box, text='Automatically check daily', variable=auto_check,
                          command=lambda: self.save_update_preference(auto_check))
        auto_toggle.pack(side='right')
        auto_toggle.configure(state='normal' if self.store.allowed('settings.edit') else 'disabled')
        frame = self.frames['Backup']
        ttk.Label(frame,text='Backup your shop data',font=('Segoe UI',19,'bold')).pack(anchor='w')
        self.backup_status = tk.StringVar(value='Last Backup: Never')
        ttk.Label(frame,textvariable=self.backup_status,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(4,14))
        backup=ttk.Frame(frame)
        backup.pack(fill='x')
        self.button(backup,'Backup Data',self.backup,True)
        self.button(backup,'Restore Data',self.restore)
        ttk.Label(frame,text='Save backups to a USB drive regularly. Restoring replaces your current shop data.',wraplength=850).pack(anchor='w',pady=18)
        self.backup_status.set(f"Last Backup: {self.store.settings().get('last_backup') or 'Never'}")

    def open_users(self):
        self.require('users.manage')
        dialog = tk.Toplevel(self); dialog.title('Users & Privileges'); dialog.geometry('760x560')
        frame = ttk.Frame(dialog, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Users & Privileges', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        tree = self.table(frame, [('name','User',230),('role','Role',140),('created','Created',220)], 6)
        def refresh():
            tree.delete(*tree.get_children())
            for user in self.store.users():
                tree.insert('', 'end', iid=str(user['id']), values=(user['name'], user['role'], human_datetime(user['created_at'])))
        refresh()
        controls = ttk.Frame(frame); controls.pack(fill='x')
        def add():
            box = tk.Toplevel(dialog); box.title('Add user')
            pane = ttk.Frame(box, padding=20); pane.pack(fill='both', expand=True)
            name, role, pin = tk.StringVar(), tk.StringVar(value='CASHIER'), tk.StringVar()
            from .security import SECURITY_QUESTIONS
            question, answer = tk.StringVar(value=SECURITY_QUESTIONS[0]), tk.StringVar()
            for label, variable, kind in (('Name',name,'entry'),('Role',role,'role'),('PIN',pin,'pin'),('Security question',question,'entry'),('Security answer',answer,'pin')):
                ttk.Label(pane, text=label).pack(anchor='w', pady=(6,2))
                (ttk.Combobox(pane,textvariable=variable,values=SECURITY_QUESTIONS,state='readonly') if label=='Security question' else ttk.Combobox(pane,textvariable=variable,values=('MANAGER','CASHIER'),state='readonly') if kind=='role' else ttk.Entry(pane,textvariable=variable,show='•' if kind=='pin' else '')).pack(fill='x')
            def save():
                self.store.create_user(name.get(), role.get(), pin.get(), question.get(), answer.get()); box.destroy(); refresh()
            ttk.Button(pane,text='Add user',command=save,style='Accent.TButton').pack(fill='x',pady=(15,0))
        def reset_pin():
            user_id=self.selected(tree); pin=simpledialog.askstring('Reset PIN','New 4 to 6 digit PIN:',parent=dialog,show='•')
            if pin is not None: self.store.reset_pin(user_id,pin); messagebox.showinfo('PIN reset','The user PIN was changed.',parent=dialog)
        def set_security_question():
            user_id = self.selected(tree)
            person = self.store.user(user_id)
            box = tk.Toplevel(dialog); box.title('Set security question')
            pane = ttk.Frame(box, padding=20); pane.pack(fill='both', expand=True)
            ttk.Label(pane, text=f'Security question for {person["name"]}', font=('Segoe UI', 14, 'bold')).pack(anchor='w')
            from .security import SECURITY_QUESTIONS
            question, answer = tk.StringVar(value=SECURITY_QUESTIONS[0]), tk.StringVar()
            ttk.Label(pane, text='Security question').pack(anchor='w', pady=(14, 3))
            ttk.Combobox(pane, textvariable=question, values=SECURITY_QUESTIONS, state='readonly').pack(fill='x')
            ttk.Label(pane, text='Security answer').pack(anchor='w', pady=(12, 3))
            ttk.Entry(pane, textvariable=answer, show='•').pack(fill='x')
            def save_question():
                self.store.set_security_question(user_id, question.get(), answer.get())
                box.destroy()
                messagebox.showinfo('Security question saved', f'Security question saved for {person["name"]}.', parent=dialog)
            ttk.Button(pane, text='Save security question', command=save_question, style='Accent.TButton').pack(fill='x', pady=(16, 0))
        def remove():
            user_id=self.selected(tree)
            person=self.store.user(user_id)
            if not messagebox.askyesno('Remove user', f"Remove {person['name']} from POS login?", parent=dialog):
                return
            self.store.remove_user(user_id)
            refresh()
            messagebox.showinfo('User removed', f"{person['name']} can no longer sign in.", parent=dialog)
        def roles():
            role=simpledialog.askstring('Permissions','Enter MANAGER or CASHIER:',initialvalue='CASHIER',parent=dialog)
            if role not in ('MANAGER','CASHIER'): return
            box=tk.Toplevel(dialog); box.title(f'{role.title()} permissions')
            pane=ttk.Frame(box,padding=20); pane.pack(fill='both',expand=True)
            ttk.Label(pane,text=f'{role.title()} permissions',font=('Segoe UI',16,'bold')).pack(anchor='w')
            current={row['permission']:bool(row['allowed']) for row in self.store.conn.execute('SELECT permission,allowed FROM role_permissions WHERE role=?',(role,))}
            values={permission:tk.BooleanVar(value=current.get(permission,False)) for permission in PERMISSIONS}
            for permission in PERMISSIONS:
                ttk.Checkbutton(pane,text=permission.replace('.',' · ').title(),variable=values[permission]).pack(anchor='w',pady=1)
            ttk.Button(pane,text='Save permissions',command=lambda:(self.store.set_role_permissions(role,{key:value.get() for key,value in values.items()}),box.destroy()),style='Accent.TButton').pack(fill='x',pady=(12,0))
        self.button(controls,'Add user',add,True); self.button(controls,'Reset selected PIN',reset_pin); self.button(controls,'Set security question',set_security_question); self.button(controls,'Remove selected user',remove); self.button(controls,'Set Manager/Cashier permissions',roles)

    def open_audit_history(self):
        self.require('users.view')
        dialog=tk.Toplevel(self); dialog.title('Audit history'); dialog.geometry('850x530')
        frame=ttk.Frame(dialog,padding=20); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Audit history',font=('Segoe UI',18,'bold')).pack(anchor='w')
        tree=self.table(frame,[('date','Date & time',190),('user','User',150),('action','Action',220),('reference','Reference',260)],12)
        for row in self.store.audit_history(): tree.insert('', 'end', values=(human_datetime(row['created_at']),row['user_name'],row['action'],row['reference']))

    def save_update_preference(self, value):
        self.store.save_settings(self.store.settings() | {'update_auto_check': 'On' if value.get() else 'Off'})

    def background_update_check(self):
        if self._closed:
            return
        state = self.store.security_state()
        settings = self.store.settings()
        if settings.get('update_auto_check', 'On') == 'On' and updater.check_due(state.get('update_last_check'), int(__import__('time').time())):
            threading.Thread(target=self._check_updates_worker, args=(False,), daemon=True).start()

    def open_software_update(self):
        dialog = tk.Toplevel(self)
        dialog.title('Software Update')
        dialog.geometry('560x390')
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Software Update', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=f'Current version: {APP_VERSION}').pack(anchor='w', pady=(5, 12))
        status = tk.StringVar(value='Check for a newer version when you are ready.')
        ttk.Label(frame, textvariable=status, wraplength=500).pack(anchor='w')
        notes = tk.Text(frame, height=7, width=58, state='disabled', relief='flat', background='#f6f8f7')
        notes.pack(fill='both', expand=True, pady=16)
        progress = ttk.Progressbar(frame, maximum=100, mode='determinate')
        progress.pack(fill='x', pady=(0, 12))
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions, text='Later', command=dialog.destroy).pack(side='left')
        check = ttk.Button(actions, text='Check for Updates')
        check.pack(side='right')
        update = ttk.Button(actions, text='Update Now', state='disabled')
        update.pack(side='right', padx=8)
        result = {'manifest': None}

        def show_notes(items):
            notes.configure(state='normal')
            notes.delete('1.0', 'end')
            notes.insert('end', "What's new\n\n" + '\n'.join(f'• {item}' for item in items))
            notes.configure(state='disabled')

        def checked(manifest, error):
            if not dialog.winfo_exists():
                return
            check.configure(state='normal')
            if error:
                status.set(str(error))
                return
            result['manifest'] = manifest
            if not updater.newer_version(manifest['latest_version']):
                status.set('Up to date')
                return
            status.set(f"Version {manifest['latest_version']} is available.")
            show_notes(manifest['release_notes'])
            update.configure(state='normal' if self.store.allowed('software.update') else 'disabled')

        def do_check():
            check.configure(state='disabled')
            status.set('Checking for updates...')
            threading.Thread(target=self._check_updates_worker, args=(True, checked), daemon=True).start()

        def do_update():
            update.configure(state='disabled')
            check.configure(state='disabled')
            status.set('Downloading update...')
            threading.Thread(target=self._download_update_worker, args=(result['manifest'], dialog, status, progress), daemon=True).start()

        check.configure(command=do_check)
        update.configure(command=do_update)
        if not updater.UPDATE_MANIFEST_URL:
            status.set('Online updates are not configured. Install the latest Sanitary Shop POS setup file manually.')
            check.configure(state='disabled')
        else:
            do_check()

    def _check_updates_worker(self, manual, callback=None):
        try:
            manifest = updater.fetch_manifest()
            error = None
        except UserError as error:
            manifest = None
        except Exception as error:
            manifest = None
        if getattr(self, '_closed', False):
            return
        try:
            self.after(0, lambda: self.store.update_security_state(update_last_check=str(int(__import__('time').time())) if manifest else self.store.security_state().get('update_last_check', '')))
            if callback:
                self.after(0, callback, manifest, error)
            elif manifest and updater.newer_version(manifest['latest_version']):
                self.after(0, lambda: self.update_status.set(f"Version {manifest['latest_version']} is available."))
        except Exception:
            pass

    def _download_update_worker(self, manifest, dialog, status, progress):
        def report(value):
            if value is not None:
                self.after(0, progress.configure, {'value': value})
        try:
            package = updater.download_verified(manifest, progress=report)
            updater.verify_windows_signature(package)
            updater.update_backup(self.store)
            env = os.environ | {'SANITARY_POS_UPDATE_PID': str(os.getpid()), 'SANITARY_POS_UPDATE_SETUP': str(package)}
            subprocess.Popen(['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-Command',
                              'Wait-Process -Id ([int]$env:SANITARY_POS_UPDATE_PID) -ErrorAction SilentlyContinue; Start-Process -FilePath $env:SANITARY_POS_UPDATE_SETUP'],
                             env=env, creationflags=0x08000000)
            self.after(0, self.close)
        except UserError as error:
            self.after(0, status.set, str(error))
        except OSError:
            self.after(0, status.set, 'The update could not be installed. Your current version is still available.')

    def open_license_info(self):
        self.require('license.view')
        from .licensing import license_status
        status=license_status(self.store,self.store.path.parent/'license.json'); payload=status.get('payload',{})
        dialog=tk.Toplevel(self); dialog.title('About & License')
        frame=ttk.Frame(dialog,padding=24); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Sanitary Shop POS',font=('Segoe UI',19,'bold')).pack(anchor='w')
        ttk.Label(frame,text=f'Version {APP_VERSION}').pack(anchor='w',pady=(2,16))
        rows=[('Status','Trial' if status['kind']=='trial' else ('Active' if status['valid'] else 'Not active')),('Licensed to',payload.get('licensed_to','—')),('License',payload.get('license_type','Trial' if status['kind']=='trial' else '—').title()),('License ID',payload.get('license_id','—')),('Device','This PC')]
        for label,value in rows:
            line=ttk.Frame(frame); line.pack(fill='x',pady=3); ttk.Label(line,text=label,width=16).pack(side='left'); ttk.Label(line,text=value,font=('Segoe UI',10,'bold')).pack(side='left')
        ttk.Label(frame,text=f'Device ID: {self.store.device_id()}',foreground='#475467').pack(anchor='w',pady=(16,0))
        ttk.Label(frame, text='© 2026 Sociapi. All rights reserved.', foreground='#475467').pack(anchor='w', pady=(16, 0))
        credits = ttk.Frame(frame); credits.pack(fill='x', pady=(8, 0))
        ttk.Label(credits, text='Built by Zuhair', foreground='#475467').pack(side='left', padx=(0, 10))
        ttk.Button(credits, text='Sociapi website', command=lambda: webbrowser.open_new_tab('https://sociapis.vercel.app/')).pack(side='left', padx=(0, 8))
        ttk.Button(credits, text='Zuhair portfolio', command=lambda: webbrowser.open_new_tab('https://xuhair.netlify.app/')).pack(side='left')
        ttk.Label(frame, text='© 2026 Muhammad Zuhair Zeb. All rights reserved.', foreground='#475467').pack(anchor='w', pady=(16, 0))

    def choose_shop_logo(self):
        from .logos import encode_logo
        path = filedialog.askopenfilename(parent=self, title='Choose shop logo', filetypes=[('Logo image', '*.png *.jpg *.jpeg *.gif')])
        if path:
            self.set_shop_logo(encode_logo(path))

    def set_shop_logo(self, value):
        self.store.save_settings(self.store.settings() | {'shop_logo': value})
        self.refresh_shop_logo()
        self.status.set('Shop logo saved. It is included on new receipts and in backups.')

    def refresh_shop_logo(self):
        from PIL import Image, ImageTk
        from io import BytesIO
        value = self.store.settings().get('shop_logo', '')
        self.shop_logo_image = None
        if value:
            image = Image.open(BytesIO(base64.b64decode(value)))
            image.thumbnail((72, 48))
            self.shop_logo_image = ImageTk.PhotoImage(image)
        self.logo_preview.configure(image=self.shop_logo_image or '', text='' if value else 'No shop logo')
        self.shop_label.configure(image=self.shop_logo_image or '', compound='left')
        self.brand_mark.configure(image=self.shop_logo_image or '', text='' if value else 'SS', compound='center')

    def update_application(self):
        self.require('software.update')
        base_dir = Path(__file__).resolve().parent.parent
        candidates = []
        if getattr(sys, 'frozen', False):
            candidates.append(Path(sys.executable).resolve().parent / 'Uninstall.exe')
        candidates.extend((base_dir / 'dist' / 'SanitaryShopPOS-Setup.exe', base_dir / 'SanitaryShopPOS-Setup.exe'))
        setup = next((path for path in candidates if path.is_file()), None)
        if setup is None:
            raise UserError('Update setup was not found. Build the latest installer first.')
        if not messagebox.askyesno('Update application', 'The POS will close and the update setup will open. Continue?', parent=self):
            return
        # Do not launch setup until this process has released its executable
        # and DLLs. Launching setup first races Windows file locking during an
        # in-app update and produces an access-denied message.
        env = os.environ | {
            'SANITARY_POS_UPDATE_PID': str(os.getpid()),
            'SANITARY_POS_UPDATE_SETUP': str(setup),
        }
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-WindowStyle', 'Hidden', '-Command',
             'Start-Sleep -Milliseconds 400; Wait-Process -Id ([int]$env:SANITARY_POS_UPDATE_PID) '
             '-ErrorAction SilentlyContinue; Start-Process -FilePath $env:SANITARY_POS_UPDATE_SETUP'],
            env=env,
            creationflags=0x08000000,
        )
        self.close()

    def save_settings(self):
        self.require('settings.edit')
        if self.setting_vars['tax_enabled'].get() == 'On':
            self.require('settings.tax')
        self.store.save_settings({key:var.get().strip() for key,var in self.setting_vars.items()})
        self.shop_label.configure(text=self.store.settings()['shop_name'])
        self.brand_name_label.configure(text=self.store.settings()['shop_name'])
        self.sidebar_shop_label.configure(text=self.store.settings()['shop_name'])
        self.refresh_inventory()
        self.refresh_totals()
        self.settings_status.set('Settings saved successfully.')
        self.status.set('Settings saved successfully.')

    def test_print(self):
        self.require('settings.view')
        settings = self.store.settings()
        sample = 'Test receipt'.center(32 if settings['paper'] == '58mm' else 44) + '\n' + ('=' * (32 if settings['paper'] == '58mm' else 44)) + '\nPrinter setup is working.\nThank you!'
        preview(self, 'Test print', sample, settings=settings)

    def print_stress_test(self):
        """Developer-only stress test dialog to verify receipt generation with 10, 25, 50, 100, 200 items."""
        if not self.development_mode:
            return
        dialog = tk.Toplevel(self)
        dialog.title('Developer Print Stress Test')
        dialog.geometry('400x320')
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Print Stress Test', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        ttk.Label(frame, text='Generate preview with dummy line items:').pack(anchor='w', pady=(0, 15))

        def run_test(count):
            settings = self.store.settings()
            width = 32 if settings.get('paper', '80mm') == '58mm' else 44
            divider = '=' * width
            dash = '-' * width
            lines = [
                settings.get('shop_name', 'Sanitary Shop').center(width),
                divider,
                f'STRESS TEST RECEIPT ({count} ITEMS)',
                datetime.now().strftime('%d %b %Y • %I:%M %p'),
                dash,
                f"{'Item':<{width - 24 if width > 32 else width - 21}} {'Qty':>5 if width > 32 else 4} {'Rate':>8 if width > 32 else 7} {'Amount':>8 if width > 32 else 7}",
                dash,
            ]
            total = 0
            for i in range(1, count + 1):
                name = f'Stress Test Product Item #{i:03d} Long Name Variant Extra'
                rate = 15000 + (i * 250)
                amount = rate * 2
                total += amount
                # Wrap item name
                import textwrap
                from .printing import _columns, _row, receipt_money
                item_width, qty_width, rate_width, amount_width = _columns(width)
                columns = _row('', '2', receipt_money(rate), receipt_money(amount), width)[item_width:]
                chunks = textwrap.wrap(name, width=item_width, break_long_words=True, break_on_hyphens=False) or ['']
                for chunk in chunks[:-1]:
                    lines.append(f'{chunk:<{item_width}}' + ' ' * (width - item_width))
                lines.append(f'{chunks[-1]:<{item_width}}{columns}')
            lines.extend([
                dash,
                f"{'Subtotal:':<{width - 12}}{total/100:,.2f}",
                f"{'Discount:':<{width - 12}}0.00",
                dash,
                f"{'TOTAL:':<{width - 12}}{total/100:,.2f}",
                f"{'Cash Received:':<{width - 12}}{total/100:,.2f}",
                f"{'Change Returned:':<{width - 12}}0.00",
                divider,
                'Thank you for testing!'.center(width)
            ])
            text = '\n'.join(lines)
            preview(self, f'Stress Test Preview ({count} items)', text, settings=settings)

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill='both', expand=True)
        for count in (10, 25, 50, 100, 200):
            ttk.Button(btn_box, text=f'{count} Items Test Receipt', command=lambda c=count: run_test(c)).pack(fill='x', pady=3)


    def backup(self):
        self.require('backup.create')
        path=filedialog.asksaveasfilename(parent=self,title='Save backup to a folder or USB drive',defaultextension='.sqlite3',initialfile=f'shop-backup-{date.today()}.sqlite3',filetypes=[('Shop backup','*.sqlite3')])
        if path:
            self.persist()
            self.store.backup(path)
            saved_at = datetime.now().strftime('%d %b %Y, %I:%M %p')
            self.store.save_settings(self.store.settings() | {'last_backup': saved_at})
            self.backup_status.set(f'Last Backup: {saved_at}')
            self.status.set('Backup completed successfully.')
            messagebox.showinfo('Backup completed','Backup completed successfully.',parent=self)

    def restore(self):
        self.require('backup.restore')
        if not self.owner_approval('Restore backup', 'Restoring replaces current shop data. Enter the Owner PIN to continue.'):
            raise UserError('Owner approval is required to restore a backup.')
        path=filedialog.askopenfilename(parent=self,title='Choose shop backup',filetypes=[('Shop backup','*.sqlite3')])
        if not path:
            return
        self.store.validate_backup(path)
        if not messagebox.askyesno('Restore backup?', 'Restoring a backup will replace your current shop data. A safety copy will be kept. Continue?',parent=self):
            return
        safety=self.store.restore(path)
        restored=self.store.load_draft()
        self.draft=restored
        self.cart=restored['cart']
        self.discount.set(restored['discount'])
        self.discount_mode.set(restored.get('discount_mode', 'cash'))
        self.discount_type_label.set('Percentage (%)' if self.discount_mode.get() == 'percent' else 'Cash (Rs.)')
        self.paid.set(restored['paid'])
        self.customer_name.set(restored.get('customer_name', ''))
        self.customer_phone.set(restored.get('customer_phone', ''))
        for key,var in self.setting_vars.items():
            var.set(self.store.settings()[key])
        self.shop_label.configure(text=self.store.settings()['shop_name'])
        self.brand_name_label.configure(text=self.store.settings()['shop_name'])
        self.sidebar_shop_label.configure(text=self.store.settings()['shop_name'])
        self.refresh_shop_logo()
        self.clear_sales_filters()
        self.refresh_all()
        self.backup_status.set(f"Last Backup: {self.store.settings().get('last_backup') or 'Never'}")
        self.status.set('Backup restored successfully.')

    def tab_changed(self,event=None):
        self.show_page(getattr(self, 'current_page', 'Billing'))

    def refresh_all(self):
        next_id = self.store.next_sale_number()
        self.bill_number_label.configure(text=f'Bill #{next_id:06d}')
        self.payment_bill_number.configure(text=f'Bill #{next_id:06d}')
        self.refresh_search()
        self.refresh_cart()
        self.refresh_products()
        self.refresh_inventory()
        self.refresh_sales()

    def close(self):
        self._closed = True
        for job in getattr(self, '_table_jobs', {}).values():
            self.after_cancel(job)
        self._table_jobs = {}
        if getattr(self, 'update_check_job', None) is not None:
            self.after_cancel(self.update_check_job)
            self.update_check_job = None
        self.persist()
        if self.toast_job is not None:
            self.after_cancel(self.toast_job)
            self.toast_job = None
        if getattr(self, 'clock_job', None) is not None:
            self.after_cancel(self.clock_job)
        if getattr(self, 'qr_reset_job', None) is not None:
            self.after_cancel(self.qr_reset_job)
        if self.camera_window is not None and self.camera_window.winfo_exists():
            self.camera_window.destroy()
        if getattr(self, 'camera_capture', None) is not None:
            self.camera_capture.release()
            self.camera_capture = None
        self.store.conn.close()
        self.destroy()
