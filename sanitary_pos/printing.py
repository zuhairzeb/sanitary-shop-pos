"""Native preview and Windows printing, without a browser or online service."""
import json
import base64
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import textwrap
from .db import money, quantity


def receipt_number(sale_id):
    return f'INV-{sale_id:06d}'


def receipt_money(paisa):
    value = paisa / 100
    return f'{value:,.2f}'.rstrip('0').rstrip('.')


def printer_text(value):
    return str(value or '').encode('ascii', 'replace').decode('ascii')


def _line(label, value, width):
    return f'{label:<{width - len(value)}}{value}'


def _columns(width):
    if width <= 32:
        return width - 21, 4, 7, 7
    return width - 24, 5, 8, 8


def _row(item, qty, rate, amount, width):
    item_width, qty_width, rate_width, amount_width = _columns(width)
    return f'{item:<{item_width}} {qty:>{qty_width}} {rate:>{rate_width}} {amount:>{amount_width}}'


def _item_lines(item, width):
    name_width = _columns(width)[0]
    columns = _row('', quantity(item['quantity_milli']), receipt_money(item['price_paisa']), receipt_money(item['total_paisa']), width)[name_width:]
    label = printer_text(' / '.join(part for part in (str(item['name']).strip(), str(item['size_variant'] or '').strip()) if part))
    chunks = textwrap.wrap(label, width=name_width, break_long_words=True, break_on_hyphens=False) or ['']
    return [*(f'{chunk:<{name_width}}' + ' ' * (width - name_width) for chunk in chunks[:-1]), f'{chunks[-1]:<{name_width}}{columns}']


def receipt_text(store, sale_id, paper=None, customer_name='', customer_phone=''):
    sale, items = store.sale(sale_id)
    shop = json.loads(sale['shop_json'])
    customer_name = customer_name or shop.get('customer_name', '')
    customer_phone = customer_phone or shop.get('customer_phone', '')
    width = 32 if (paper or shop.get('paper', '80mm')) == '58mm' else 44
    divider = '=' * width
    dash = '-' * width
    created = datetime.fromisoformat(sale['created_at']).strftime('%d %b %Y • %I:%M %p')
    lines = [printer_text(shop['shop_name']).center(width)]
    if shop.get('address'):
        lines.extend(printer_text(line).center(width) for line in str(shop['address']).splitlines() if line.strip())
    if shop.get('phone'):
        lines.append(printer_text(shop['phone']).center(width))
    if shop.get('ntn'):
        lines.append(printer_text(f'NTN: {shop["ntn"]}').center(width))
    created_date = datetime.fromisoformat(sale['created_at']).strftime('%d %b %Y')
    created_time = datetime.fromisoformat(sale['created_at']).strftime('%I:%M %p')
    created = f'{created_date}{" " * max(1, width - len(created_date) - len(created_time))}{created_time}'
    lines.extend([divider, f'Bill #{sale_id:06d}', created, dash])
    if customer_name or customer_phone:
        if customer_name:
            lines.append(printer_text(f'Customer: {customer_name}'))
        if customer_phone:
            lines.append(printer_text(f'Phone: {customer_phone}'))
        lines.append(dash)
    lines.append(_row('Item', 'Qty', 'Rate', 'Amount', width))
    lines.append(dash)
    for item in items:
        lines.extend(_item_lines(item, width))
    lines.append(dash)
    balance = sale['total_paisa'] - sale['paid_paisa']
    lines.extend([_line('Subtotal:', receipt_money(sale['subtotal_paisa']), width),
                  _line('Discount:', receipt_money(sale['discount_paisa']), width)])
    if sale['gst_rate_bps']:
        lines.extend([_line('Taxable Amount:', receipt_money(sale['taxable_paisa']), width),
                      _line(f'{shop.get("tax_label", "GST")} ({sale["gst_rate_bps"] / 100:g}%):', receipt_money(sale['gst_paisa']), width)])
    lines.extend([dash,
                  _line('TOTAL:', receipt_money(sale['total_paisa']), width),
                  _line('Cash Received:', receipt_money(sale['paid_paisa']), width),
                  _line('Change: (Change Returned):' if balance <= 0 else 'Balance Due:', receipt_money(abs(balance)), width),
                  divider, ''] )
    footer = [printer_text(line).strip() for line in str(shop.get('footer', 'Thank you!\nPlease visit again')).replace('\r', '').split('\n') if line.strip()]
    if len(footer) == 1 and footer[0].lower() == 'thank you! please visit again':
        footer = ['Thank you!', 'Please visit again']
    lines.extend(line.center(width) for line in footer)
    return '\n'.join(lines)


def _save_pdf(text, path, paper, logo=''):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    width = 164 if paper == '58mm' else 226
    logo_height = 50 if logo else 0
    lines = text.splitlines()
    height = max(180, 38 + len(lines) * 12 + logo_height)
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    if logo:
        pdf.drawImage(ImageReader(BytesIO(base64.b64decode(logo))), width/2-30, height-56, width=60, height=42, preserveAspectRatio=True, anchor='c', mask='auto')
    pdf.setFont('Courier', 8 if paper == '58mm' else 7.5)
    for index, line in enumerate(lines):
        pdf.drawString(10, height - 24 - logo_height - index*12, line)
    pdf.save()


def preview(parent, title, text, qr=None, settings=None, auto_print=False):
    settings = settings or {}
    paper = settings.get('paper', '80mm')
    text_width = 32 if paper == '58mm' else 44
    window = tk.Toplevel(parent)
    window.title(title)
    window.minsize(390 if paper == '58mm' else 540, 480)
    window.geometry(f'{390 if paper == "58mm" else 540}x720')
    controls = ttk.Frame(window, padding=12)
    controls.pack(fill='x')
    print_status = tk.StringVar(value='')
    copies = tk.IntVar(value=int(settings.get('copies', 1)))
    ttk.Label(controls, text='Copies').pack(side='left')
    ttk.Spinbox(controls, from_=1, to=100, textvariable=copies, width=5).pack(side='left', padx=10)
    matrix = None
    logo = settings.get('shop_logo', '') if not qr else ''
    if logo:
        from PIL import Image, ImageTk
        logo_image = Image.open(BytesIO(base64.b64decode(logo)))
        logo_image.thumbnail((120, 70))
        window.logo_image = ImageTk.PhotoImage(logo_image)
        ttk.Label(window, image=window.logo_image).pack(pady=8)
    if qr:
        import qrcode
        code = qrcode.QRCode(border=4)
        code.add_data(qr)
        code.make(fit=True)
        matrix = code.get_matrix()
        size = max(2, min(6, 360 // len(matrix)))
        canvas = tk.Canvas(window, width=len(matrix)*size, height=len(matrix)*size, bg='white', highlightthickness=0)
        canvas.pack(pady=10)
        ttk.Label(window, text='Printed QR: 20 × 20 mm · product code below').pack()
        for y, row in enumerate(matrix):
            for x, black in enumerate(row):
                if black:
                    canvas.create_rectangle(x*size, y*size, (x+1)*size, (y+1)*size, fill='black', outline='')
    body = tk.Text(window, wrap='none', width=text_width, font=('Courier New', 10), padx=18, pady=15, bg='white')
    body.insert('1.0', text)
    body.configure(state='disabled')
    body.pack(fill='both', expand=True)

    print_button = None

    def finish_print(success, error=None):
        if not window.winfo_exists():
            return
        print_button.configure(state='normal')
        print_status.set('Printed successfully.' if success else 'Printing failed. The saved bill is available in Sales.')
        if not success:
            messagebox.showerror('Could not print', str(error), parent=window)

    def print_worker(payload_path, folder):
        try:
            script = Path(__file__).with_name('print.ps1')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(script), str(payload_path)], creationflags=0x08000000, capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError('Printing failed. Check the printer connection and Windows printer settings.')
            window.after(0, finish_print, True)
        except subprocess.TimeoutExpired:
            window.after(0, finish_print, False, RuntimeError('The printer did not respond within 90 seconds. Check the printer connection.'))
        except Exception as error:
            window.after(0, finish_print, False, error)

    def print_now():
        try:
            count = copies.get()
            if not 1 <= count <= 100:
                raise ValueError('Choose between 1 and 100 copies.')
            folder = tempfile.mkdtemp(prefix='shop-print-')
            payload = Path(folder) / 'print.json'
            payload.write_text(json.dumps(dict(text=text, matrix=matrix, copies=count, printer=settings.get('printer', ''), paper=settings.get('paper', '80mm'), logo=logo)), encoding='utf-8')
            print_button.configure(state='disabled')
            print_status.set('Printing...')
            threading.Thread(target=print_worker, args=(payload, folder), daemon=True).start()
        except Exception as error:
            finish_print(False, error)
    def save_pdf():
        path = filedialog.asksaveasfilename(parent=window, title='Save receipt as PDF', defaultextension='.pdf', filetypes=[('PDF document', '*.pdf')])
        if path:
            if qr:
                from .labels import export_labels
                export_labels([{'qr': qr, 'code': text.strip()}], path, copies.get())
            else:
                _save_pdf(text, path, settings.get('paper', '80mm'), logo)
    ttk.Button(controls, text='Cancel', command=window.destroy).pack(side='right')
    ttk.Button(controls, text='Save as PDF', command=save_pdf).pack(side='right', padx=8)
    print_button = ttk.Button(controls, text='Print', command=print_now, style='Accent.TButton')
    print_button.pack(side='right')
    ttk.Label(window, textvariable=print_status, foreground='#176b67').pack(anchor='w', padx=12, pady=(0, 8))
    if auto_print:
        window.after(100, print_now)
    return window
