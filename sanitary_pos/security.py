"""Offline users, permissions and audit records. PINs are never stored or logged."""
import hashlib
SECURITY_QUESTIONS = ('What was the name of your first school?', 'What is the name of your childhood best friend?', 'In which city were you born?', 'What was the name of your first pet?')
import hmac
import os
from datetime import datetime

from .db import UserError

PERMISSIONS = (
    'billing.create', 'billing.discount', 'billing.reprint',
    'products.view', 'products.add', 'products.edit', 'products.delete', 'products.change_price', 'products.print_qr',
    'stock.view', 'stock.increase', 'stock.decrease',
    'sales.view', 'sales.reprint', 'sales.cancel', 'sales.return', 'sales.view_returns',
    'backup.create', 'backup.restore',
    'settings.view', 'settings.edit', 'settings.tax',
    'users.view', 'users.manage', 'license.view', 'software.update',
)

ROLE_DEFAULTS = {
    'OWNER': set(PERMISSIONS),
    'MANAGER': {'billing.create', 'billing.discount', 'billing.reprint', 'products.view', 'products.add',
                'products.edit', 'products.change_price', 'products.print_qr', 'stock.view', 'stock.increase',
                'stock.decrease', 'sales.view', 'sales.reprint', 'sales.view_returns', 'backup.create', 'settings.view'},
    'CASHIER': {'billing.create', 'billing.reprint'},
}


def validate_pin(pin):
    pin = str(pin)
    if not (len(pin) in (4, 5, 6) and pin.isascii() and pin.isdigit()):
        raise UserError('PIN must contain 4 to 6 digits.')
    return pin


def hash_pin(pin, salt=None):
    pin = validate_pin(pin)
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.scrypt(pin.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt, digest


def pin_matches(pin, salt, digest):
    try:
        _, candidate = hash_pin(pin, bytes(salt))
        return hmac.compare_digest(candidate, bytes(digest))
    except UserError:
        return False


def hash_answer(answer, salt=None):
    answer = str(answer).strip().casefold()
    if len(answer) < 3:
        raise UserError('Security answer must contain at least 3 characters.')
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.scrypt(answer.encode('utf-8'), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt, digest


def answer_matches(answer, salt, digest):
    try:
        _, candidate = hash_answer(answer, bytes(salt))
        return hmac.compare_digest(candidate, bytes(digest))
    except UserError:
        return False


def timestamp():
    return datetime.now().isoformat(timespec='seconds')
