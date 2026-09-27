"""Offline, vector QR labels. QR square includes its required quiet zone."""
import qrcode
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4

QR_MM = 20


def qr_matrix(payload):
    qr = qrcode.QRCode(border=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def export_labels(products, path, copies=1):
    products = list(products)
    if not products or not 1 <= copies <= 100:
        raise ValueError('Select products and choose 1 to 100 copies.')
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle('Product QR labels - 20 x 20 mm')
    per_page = 54
    index = 0
    for product in products:
        matrix = qr_matrix(product['qr'])
        for _ in range(copies):
            if index and index % per_page == 0:
                pdf.showPage()
            cell = index % per_page
            x = (15 + cell % 6 * 31) * mm
            y = A4[1] - (15 + cell // 6 * 30 + QR_MM) * mm
            module = QR_MM * mm / len(matrix)
            pdf.setFillColorRGB(0, 0, 0)
            for row, values in enumerate(matrix):
                for col, black in enumerate(values):
                    if black:
                        pdf.rect(x + col * module, y + (len(matrix)-row-1) * module, module, module, stroke=0, fill=1)
            code = str(product['code'])
            size = min(8, 25 * mm / max(1, pdf.stringWidth(code, 'Helvetica', 1)))
            pdf.setFont('Helvetica', size)
            pdf.drawCentredString(x + 10*mm, y - 3*mm, code)
            index += 1
    pdf.save()
    return index
