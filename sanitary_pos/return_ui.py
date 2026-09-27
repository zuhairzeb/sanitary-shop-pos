"""Return/refund screens using the existing POS widgets and Store rules."""
import json
import uuid
import tkinter as tk
from tkinter import ttk, messagebox

from .db import UserError, money, quantity
from .printing import preview

RETURN_REASONS = ('Customer Return', 'Damaged / Defective', 'Wrong Product', 'Other')
REFUND_METHODS = ('Cash', 'Other / Original Method')


def return_text(store, return_id):
    row, items = store.return_record(return_id)
    shop = json.loads(row['shop_json'])
    lines = [shop.get('shop_name', 'Sanitary Shop'), shop.get('phone', ''),
             'RETURN RECEIPT / REFUND SLIP', row['return_number'], f'Original Bill #{row["sale_id"]:06d}',
             row['created_at'], '-' * 32]
    for item in items:
        title = item['name'] + (f' ({item["size_variant"]})' if item['size_variant'] else '')
        stock = 'To stock' if item['returned_to_stock'] else 'Damaged / not stocked'
        lines += [title, f'Qty Returned: {quantity(item["quantity_milli"])} {item["unit"]}',
                  f'Refund: Rs. {money(item["refund_paisa"])}  {stock}']
    lines += ['-' * 32, f'Total Refund: Rs. {money(row["total_paisa"])}',
              f'Refund Method: {row["refund_method"]}', f'Reason: {row["reason"]}',
              f'Processed by: {row["processed_by"]}', shop.get('footer', 'Thank you')]
    return '\n'.join(line for line in lines if line)


class ReturnActions:
    def print_return(self, return_id):
        self.require('sales.view_returns')
        row, _ = self.store.return_record(return_id)
        settings = self.store.settings() | {'shop_logo': json.loads(row['shop_json']).get('shop_logo', '')}
        preview(self, 'Return receipt / Refund slip', return_text(self.store, return_id), settings=settings)

    def reprint_return(self):
        self.require('sales.view_returns')
        sale_id = self.selected(self.sale_tree)
        rows = self.store.conn.execute('SELECT id FROM sale_returns WHERE sale_id=? ORDER BY id DESC', (sale_id,)).fetchall()
        if not rows:
            raise UserError('This bill has no returns.')
        self.print_return(rows[0]['id'])

    def open_sale(self, sale_id):
        self.require('sales.view')
        sale, _ = self.store.sale(sale_id)
        if not sale: raise UserError('Bill not found.')
        dialog = tk.Toplevel(self); dialog.title(f'Bill #{sale_id:06d}'); dialog.geometry('760x520'); dialog.transient(self)
        pane = ttk.Frame(dialog, padding=22); pane.pack(fill='both', expand=True)
        status = self.store.sale_return_status(sale_id)
        ttk.Label(pane, text=f'Bill #{sale_id:06d}', font=('Segoe UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(pane, text=f'Status: {status}  ·  Original total: Rs. {money(sale["total_paisa"])}').pack(anchor='w', pady=(3, 12))
        tree = self.table(pane, [('name','Product',260),('sold','Original Qty',105),('returned','Returned Qty',110),('net','Net Qty',105),('price','Original Price',120)], 9)
        for item in self.store.returnable_items(sale_id):
            returned = item['returned_milli']
            tree.insert('', 'end', values=(item['name'], quantity(item['quantity_milli']), quantity(returned), quantity(item['quantity_milli']-returned), money(item['price_paisa'])))
        controls = ttk.Frame(pane); controls.pack(fill='x', pady=(12, 0))
        self.button(controls, 'Print bill', lambda: self.open_receipt(sale_id), True)
        if self.store.allowed('sales.return') and status != 'FULLY RETURNED':
            self.button(controls, 'Return Product', lambda: (dialog.destroy(), self.return_dialog(sale_id)))

    def return_dialog(self, sale_id=None):
        self.require('sales.return')
        sale_id = sale_id or self.selected(self.sale_tree)
        if not self.store.sale(sale_id)[0]: raise UserError('Bill not found.')
        dialog = tk.Toplevel(self); dialog.title(f'Return Products — Bill #{sale_id:06d}'); dialog.geometry('820x610'); dialog.transient(self); dialog.grab_set()
        pane = ttk.Frame(dialog, padding=22); pane.pack(fill='both', expand=True)
        ttk.Label(pane, text=f'Return Products — Bill #{sale_id:06d}', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(pane, text='Refund uses original price, original order discount and original GST.').pack(anchor='w', pady=(3, 12))
        rows = ttk.Frame(pane); rows.pack(fill='x')
        for column, label in enumerate(('Product', 'Purchased', 'Already Returned', 'Return Qty', 'Return to Stock')):
            ttk.Label(rows, text=label, font=('Segoe UI', 9, 'bold')).grid(row=0, column=column, sticky='w', padx=5, pady=4)
        entries = []
        for index, item in enumerate(self.store.returnable_items(sale_id), 1):
            left = item['quantity_milli'] - item['returned_milli']
            value, to_stock = tk.StringVar(value='0'), tk.BooleanVar(value=True)
            ttk.Label(rows, text=item['name'] + (f' · {item["size_variant"]}' if item['size_variant'] else '')).grid(row=index, column=0, sticky='w', padx=5, pady=4)
            ttk.Label(rows, text=quantity(item['quantity_milli'])).grid(row=index, column=1, sticky='w', padx=5)
            ttk.Label(rows, text=quantity(item['returned_milli'])).grid(row=index, column=2, sticky='w', padx=5)
            ttk.Spinbox(rows, from_=0, to=quantity(left), increment=1, textvariable=value, width=10).grid(row=index, column=3, sticky='w', padx=5)
            ttk.Checkbutton(rows, variable=to_stock).grid(row=index, column=4, sticky='w', padx=5)
            entries.append((item, value, to_stock))
        options = ttk.Frame(pane); options.pack(fill='x', pady=14)
        reason, method = tk.StringVar(value=RETURN_REASONS[0]), tk.StringVar(value=REFUND_METHODS[0])
        ttk.Label(options, text='Reason').grid(row=0, column=0, sticky='w')
        ttk.Combobox(options, textvariable=reason, values=RETURN_REASONS, state='readonly', width=25).grid(row=1, column=0, sticky='w', padx=(0, 20))
        ttk.Label(options, text='Refund Method').grid(row=0, column=1, sticky='w')
        ttk.Combobox(options, textvariable=method, values=REFUND_METHODS, state='readonly', width=25).grid(row=1, column=1, sticky='w')
        other_reason = tk.StringVar()
        ttk.Label(options, text='Other reason (optional)').grid(row=0, column=2, sticky='w')
        ttk.Entry(options, textvariable=other_reason, width=25).grid(row=1, column=2, sticky='w')
        def apply_damaged_disposition(*_):
            if reason.get() == 'Damaged / Defective':
                for _, _, stock in entries:
                    stock.set(False)
        reason.trace_add('write', apply_damaged_disposition)
        summary = tk.StringVar(value='Choose quantities to see the refund amount.')
        ttk.Label(pane, textvariable=summary, font=('Segoe UI', 11, 'bold'), wraplength=730).pack(anchor='w', pady=8)
        token = str(uuid.uuid4())
        def data():
            return {item['id']: {'quantity': value.get(), 'to_stock': stock.get()} for item, value, stock in entries if value.get().strip() not in ('', '0', '0.0', '0.00', '0.000')}
        def show_summary():
            _, quoted, total = self.store.return_quote(sale_id, data())
            summary.set('RETURN SUMMARY · ' + ' | '.join(f"{q['item']['name']}: {quantity(q['quantity_milli'])}" for q in quoted) + f' · Refund Amount: Rs. {money(total)}')
        def confirm():
            _, quoted, total = self.store.return_quote(sale_id, data())
            details = '\n'.join(f"{q['item']['name']} — {quantity(q['quantity_milli'])} — Rs. {money(q['refund_paisa'])}" for q in quoted)
            if not messagebox.askyesno('Confirm Return & Refund', f'{details}\n\nRefund Amount: Rs. {money(total)}\nMethod: {method.get()}\nReason: {reason.get()}\n\nProcess this return?', parent=dialog): return
            confirm_button.configure(state='disabled')
            try:
                selected_reason = other_reason.get().strip() if reason.get() == 'Other' and other_reason.get().strip() else reason.get()
                return_id = self.store.return_sale(sale_id, data(), token, selected_reason, method.get())
            except Exception:
                confirm_button.configure(state='normal')
                raise
            dialog.destroy(); self.refresh_all(); self.print_return(return_id)
        controls = ttk.Frame(pane); controls.pack(fill='x', pady=(10, 0))
        self.button(controls, 'Show Return Summary', show_summary)
        ttk.Button(controls, text='Cancel', command=dialog.destroy).pack(side='left', padx=8)
        confirm_button = self.button(controls, 'Confirm Return & Refund', confirm, True)

    def open_returns(self):
        self.require('sales.view_returns')
        dialog = tk.Toplevel(self); dialog.title('Returns'); dialog.geometry('920x560')
        pane = ttk.Frame(dialog, padding=20); pane.pack(fill='both', expand=True)
        ttk.Label(pane, text='Returns', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        tree = self.table(pane, [('number','Return #',115),('date','Date',155),('bill','Original Bill',115),('customer','Customer',160),('items','Items',180),('refund','Refund',110),('by','Processed By',120)], 10)
        customer = getattr(self, 'customer_filter', tk.StringVar()).get().strip()
        for row in self.store.returns(self.bill_filter.get().strip(), self.date_filter.get().strip(), customer):
            name = json.loads(row['shop_json']).get('customer_name', '')
            items = self.store.conn.execute('SELECT name,quantity_milli FROM return_items WHERE return_id=?', (row['id'],)).fetchall()
            text = ', '.join(f"{i['name']} × {quantity(i['quantity_milli'])}" for i in items)
            tree.insert('', 'end', iid=str(row['id']), values=(row['return_number'], row['created_at'], f"#{row['sale_id']:06d}", name, text, money(row['total_paisa']), row['processed_by']))
        controls = ttk.Frame(pane); controls.pack(fill='x', pady=10)
        self.button(controls, 'Open / Print Return Receipt', lambda: self.print_return(self.selected(tree)), True)
