"""Developer-only license generator for Sanitary Shop POS.

This utility is intentionally kept separate from the POS app. It signs customer licenses
using a private Ed25519 key that remains on the developer machine only.
"""

import argparse
import base64
import json
import re
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PRODUCT_NAME = 'Sanitary Shop POS'
DEFAULT_PRIVATE_KEY = Path(__file__).resolve().parents[1] / 'developer_keys' / 'ssp-ed25519.privatekey'
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / 'developer_keys' / 'generated_licenses'


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def text_key(document, prefix='SSP1'):
    return prefix + '.' + base64.urlsafe_b64encode(canonical(document)).decode('ascii').rstrip('=')


def sign_recovery(private_key_path, request):
    from datetime import datetime, timezone
    required = {'product', 'purpose', 'device_id', 'user_id', 'owner_name', 'nonce', 'expires_at'}
    if not required <= request.keys() or request['product'] != PRODUCT_NAME or request['purpose'] != 'owner-pin-reset':
        raise ValueError('Not an owner recovery request.')
    if datetime.fromisoformat(request['expires_at']) < datetime.now(timezone.utc):
        raise ValueError('Request expired. Ask the customer for a new request.')
    signature = load_private_key(private_key_path).sign(canonical(request))
    return text_key({'recovery': request, 'signature': base64.b64encode(signature).decode('ascii')}, 'SSPR1')


def load_private_key(path):
    raw = Path(path).read_bytes()
    if len(raw) != 32:
        raise ValueError('Private key must be exactly 32 raw bytes.')
    return Ed25519PrivateKey.from_private_bytes(raw)


def build_payload(shop, device_id, license_type, license_id, issue_date=None, expiry_date=None):
    shop = str(shop).strip()
    device_id = str(device_id).strip()
    license_type = str(license_type).upper()
    license_id = str(license_id).strip()
    if not shop or not device_id or not license_id:
        raise ValueError('Customer name, device ID and license ID are required.')
    if license_type not in {'LIFETIME', 'TRIAL'}:
        raise ValueError('License type must be either LIFETIME or TRIAL.')
    payload = {
        'license_id': license_id,
        'licensed_to': shop,
        'device_id': device_id,
        'license_type': license_type,
        'issue_date': issue_date or date.today().isoformat(),
        'product': PRODUCT_NAME,
    }
    if license_type == 'TRIAL':
        if not expiry_date:
            raise ValueError('Trial licenses require an expiry date.')
        payload['expiry_date'] = expiry_date
    elif expiry_date:
        payload['expiry_date'] = expiry_date
    return payload


def generate_license(private_key_path, shop, device_id, license_type, license_id, output_path, issue_date=None, expiry_date=None):
    key = load_private_key(private_key_path)
    payload = build_payload(shop, device_id, license_type, license_id, issue_date=issue_date, expiry_date=expiry_date)
    signature = key.sign(canonical(payload))
    document = {'license': payload, 'signature': base64.b64encode(signature).decode('ascii')}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2), encoding='utf-8')
    target.with_suffix('.key.txt').write_text(text_key(document), encoding='utf-8')
    return target, payload


def sanitize_filename(value):
    text = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value).strip())
    return text or 'license'


def run_gui():
    root = tk.Tk()
    root.title('Sanitary Shop POS • License Generator')
    root.geometry(f'720x{min(820, root.winfo_screenheight() - 100)}')
    root.resizable(True, True)
    root.minsize(480, 400)
    root.configure(bg='#f6f8f7')

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 10), background='#f6f8f7', foreground='#1f2937')
    style.configure('Header.TLabel', font=('Segoe UI', 18, 'bold'), foreground='#14213d')
    style.configure('TEntry', padding=8)
    style.configure('Accent.TButton', padding=(18, 10), background='#087a55', foreground='white', bordercolor='#087a55', font=('Segoe UI', 10, 'bold'))
    style.map('Accent.TButton', background=[('active', '#16a36f')])

    footer = ttk.Frame(root, padding=(24, 12, 24, 18))
    footer.pack(side='bottom', fill='x')
    body = ttk.Frame(root)
    body.pack(fill='both', expand=True)
    canvas = tk.Canvas(body, bg='#f6f8f7', highlightthickness=0)
    scrollbar = ttk.Scrollbar(body, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(canvas, padding=24)
    form_window = canvas.create_window(0, 0, anchor='nw', window=frame)
    frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    def resize_form(event):
        canvas.itemconfigure(form_window, width=event.width)
        description.configure(wraplength=max(240, event.width - 48))
    canvas.bind('<Configure>', resize_form)
    root.bind('<MouseWheel>', lambda event: canvas.yview_scroll(int(-event.delta / 120), 'units'))
    ttk.Label(frame, text='Private License Generator', style='Header.TLabel').pack(anchor='w', pady=(0, 18))
    description = ttk.Label(frame, text='Developer-only: keep the private key on the vendor machine and never ship it with the POS.', wraplength=620)
    description.pack(anchor='w', pady=(0, 20))

    fields = {
        'shop': tk.StringVar(value='Sanitary Shop'),
        'device_id': tk.StringVar(value='SSP-2B12-86DB-38B7-C819'),
        'license_type': tk.StringVar(value='LIFETIME'),
        'issue_date': tk.StringVar(value=date.today().isoformat()),
        'expiry_date': tk.StringVar(value=''),
        'license_id': tk.StringVar(value='SSP-DEV-0001'),
        'private_key': tk.StringVar(value=str(DEFAULT_PRIVATE_KEY)),
    }

    def set_expiry_state(*_):
        if fields['license_type'].get() == 'TRIAL':
            expiry_entry.configure(state='normal')
            expiry_label.configure(foreground='#1f2937')
        else:
            expiry_entry.configure(state='disabled')
            expiry_label.configure(foreground='#667085')
            fields['expiry_date'].set('')

    for label, key in (('Customer / Shop Name', 'shop'), ('Device ID', 'device_id'), ('License ID', 'license_id'), ('Private key file', 'private_key'), ('Issue Date', 'issue_date'), ('Expiry Date (Trial only)', 'expiry_date')):
        field_label = ttk.Label(frame, text=label)
        field_label.pack(anchor='w', pady=(12, 4))
        if key == 'private_key':
            row = ttk.Frame(frame)
            row.pack(fill='x')
            entry = ttk.Entry(row, textvariable=fields[key], width=70)
            entry.pack(side='left', fill='x', expand=True)
            ttk.Button(row, text='Browse', command=lambda: fields['private_key'].set(filedialog.askopenfilename(title='Select private key file', filetypes=[('Ed25519 private key', '*.key *.privatekey *.bin')]))).pack(side='left', padx=(8, 0))
        else:
            if key == 'issue_date' or key == 'expiry_date':
                entry = ttk.Entry(frame, textvariable=fields[key], width=30)
                entry.pack(anchor='w')
            else:
                entry = ttk.Entry(frame, textvariable=fields[key], width=80)
                entry.pack(anchor='w', fill='x')
        if key == 'expiry_date':
            expiry_label = field_label
            expiry_entry = entry
    ttk.Label(frame, text='License Type').pack(anchor='w', pady=(12, 4))
    type_box = ttk.Combobox(frame, values=('LIFETIME', 'TRIAL'), textvariable=fields['license_type'], state='readonly', width=20)
    type_box.pack(anchor='w')
    fields['license_type'].trace_add('write', set_expiry_state)
    set_expiry_state()

    def show_key(title, key, note):
        dialog = tk.Toplevel(root)
        dialog.title(title)
        dialog.geometry('650x360')
        pane = ttk.Frame(dialog, padding=20)
        pane.pack(fill='both', expand=True)
        ttk.Label(pane, text=note, wraplength=560).pack(anchor='w', pady=(0, 12))
        output = tk.Text(pane, height=7, wrap='char')
        output.insert('1.0', key)
        output.configure(state='disabled')
        output.pack(fill='both', expand=True)
        def copy():
            root.clipboard_clear()
            root.clipboard_append(key)
        ttk.Button(pane, text='Copy key', command=copy, style='Accent.TButton').pack(fill='x', pady=10)

    def recovery():
        path = filedialog.askopenfilename(parent=root, title='Choose owner recovery request', filetypes=[('Recovery request', '*.json')])
        if not path: return
        try:
            request = json.loads(Path(path).read_text(encoding='utf-8'))
            if not messagebox.askyesno('Approve owner recovery',
                f"Verify this customer before approving.\nOwner: {request.get('owner_name')}\nDevice: {request.get('device_id')}\n\nAuthorize PIN reset?", parent=root):
                return
            key = sign_recovery(fields['private_key'].get(), request)
            show_key('Owner recovery key', key, 'Send this one-use recovery key only to the verified owner. It expires with their request.')
        except (OSError, ValueError, TypeError, KeyError) as error:
            messagebox.showerror('Recovery could not be approved', str(error), parent=root)

    def generate():
        try:
            output_name = f"{sanitize_filename(fields['shop'].get())}-{sanitize_filename(fields['device_id'].get())}.lic"
            destination = DEFAULT_OUT_DIR / output_name
            destination, payload = generate_license(
                private_key_path=fields['private_key'].get(),
                shop=fields['shop'].get(),
                device_id=fields['device_id'].get(),
                license_type=fields['license_type'].get(),
                license_id=fields['license_id'].get(),
                output_path=destination,
                issue_date=fields['issue_date'].get(),
                expiry_date=fields['expiry_date'].get() or None,
            )
            show_key('License generated', destination.with_suffix('.key.txt').read_text(encoding='utf-8'),
                     f'License file: {destination}\nSend the .lic file OR copy and send the key below.')
        except Exception as exc:  # pragma: no cover - GUI path
            messagebox.showerror('Unable to generate license', str(exc))

    ttk.Button(footer, text='Generate License', command=generate, style='Accent.TButton').pack(fill='x')
    ttk.Button(footer, text='Approve owner PIN recovery', command=recovery).pack(fill='x', pady=(8, 0))
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Developer-only Sanitary Shop POS license generator')
    parser.add_argument('--private-key', default=str(DEFAULT_PRIVATE_KEY), help='Path to the vendor-only raw 32-byte Ed25519 private key')
    parser.add_argument('--shop', help='Customer or shop name')
    parser.add_argument('--device-id', help='Target device ID to bind this license to')
    parser.add_argument('--type', dest='license_type', choices=('LIFETIME', 'TRIAL'), help='License type')
    parser.add_argument('--license-id', help='Customer-facing license ID')
    parser.add_argument('--issue-date', help='Issue date (YYYY-MM-DD). Defaults to today.')
    parser.add_argument('--expiry-date', help='Expiry date for TRIAL licenses (YYYY-MM-DD).')
    parser.add_argument('--out', help='Output .lic path. Defaults to developer_keys/generated_licenses/<shop>-<device>.lic')
    args = parser.parse_args()

    if args.shop is None and args.device_id is None and args.license_id is None and args.license_type is None and args.out is None:
        run_gui()
        return

    if not args.shop or not args.device_id or not args.license_id or not args.license_type:
        raise SystemExit(' --shop, --device-id, --license-id and --type are required when running in CLI mode.')

    destination = Path(args.out) if args.out else DEFAULT_OUT_DIR / f'{sanitize_filename(args.shop)}-{sanitize_filename(args.device_id)}.lic'
    target, _ = generate_license(
        private_key_path=args.private_key,
        shop=args.shop,
        device_id=args.device_id,
        license_type=args.license_type,
        license_id=args.license_id,
        output_path=destination,
        issue_date=args.issue_date,
        expiry_date=args.expiry_date,
    )
    print(f'License written to: {target}')


if __name__ == '__main__':
    main()
