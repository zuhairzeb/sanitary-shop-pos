"""Self-contained printable documents; no internet resources."""
import json
from html import escape
from pathlib import Path
from .db import money, quantity
from .printing import receipt_text


def page(title, body, paper='80mm'):
    width = {'58mm': '48mm', '80mm': '70mm', 'A4': '180mm'}.get(paper, '70mm')
    size = 'A4' if paper == 'A4' else 'auto'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title>
<style>@page{{size:{size};margin:5mm}}*{{box-sizing:border-box}}body{{font:14px Arial,sans-serif;color:#000;background:white;max-width:{width};margin:20px auto}}
h1{{font-size:22px;margin:8px 0}}h2{{font-size:17px}}p{{margin:5px 0;overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse;margin:16px 0}}td,th{{padding:7px 2px;text-align:right;vertical-align:top}}td:first-child,th:first-child{{text-align:left;overflow-wrap:anywhere}}tr{{break-inside:avoid}}thead{{display:table-header-group}}th{{border-bottom:1px solid}}small{{font-size:11px}}.total{{font-size:19px;font-weight:bold;border-top:1px solid;padding-top:10px}}button{{padding:12px 20px;font-size:16px;cursor:pointer}}.tools{{margin:20px 0}}@media print{{body{{margin:0}}.tools{{display:none}}}}</style></head><body>
<div class="tools"><button onclick="window.print()">Print</button><p>Choose your printer and paper size.</p></div>{body}</body></html>'''


def write_receipt(store, sale_id, folder):
    sale, items = store.sale(sale_id)
    shop = json.loads(sale['shop_json'])
    body = f'<pre style="font:13px Courier New,monospace;white-space:pre-wrap">{escape(receipt_text(store, sale_id, shop.get("paper")))}</pre>'
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'bill-{sale_id:06d}.html'
    path.write_text(page(f'Bill #{sale_id:06d}', body, shop['paper']), encoding='utf-8')
    return path


def write_label(product, folder):
    import qrcode
    from qrcode.image.svg import SvgPathImage
    qr = qrcode.make(product['qr'], image_factory=SvgPathImage, box_size=8, border=4)
    svg = qr.to_string().decode('utf-8')
    body = f"<h2>{escape(product['name'])}</h2>{svg}<p>{escape(product['code'])}</p><p>Rs. {money(product['selling_paisa'])}</p>"
    path = Path(folder) / f"label-{product['id']}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page('Product QR label', body), encoding='utf-8')
    return path
