"""Customer-side Ed25519 license verification. This module contains no private key."""
import base64
import json
from datetime import date, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .db import UserError

PRODUCT = 'Sanitary Shop POS'
PUBLIC_KEY_HEX = '9c1cbe7b965159ccff9052e6a8593ed3d531f93dfc7bc54569c225cf04e1d633'


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def encode_key(document, prefix='SSP1'):
    return prefix + '.' + base64.urlsafe_b64encode(canonical(document)).decode('ascii').rstrip('=')


def decode_key(text, prefix='SSP1'):
    try:
        text = ''.join(text.split())
        if len(text) > 20000 or not text.startswith(prefix + '.'):
            raise ValueError()
        raw = text.split('.', 1)[1]
        document = json.loads(base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True))
        if not isinstance(document, dict):
            raise ValueError()
        return document
    except (ValueError, TypeError):
        raise UserError('This key could not be read. Paste the complete key.') from None


def load_license(path):
    try:
        document = path if isinstance(path, dict) else json.loads(Path(path).read_text(encoding='utf-8'))
        payload = document['license']
        if not isinstance(payload, dict):
            raise ValueError()
        signature = base64.b64decode(document['signature'], validate=True)
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(signature, canonical(payload))
        return payload
    except (OSError, ValueError, KeyError, TypeError, InvalidSignature):
        raise UserError('License could not be verified.') from None


def validate_license(path, current_device):
    payload = load_license(path)
    required = {'license_id', 'licensed_to', 'device_id', 'license_type', 'issue_date', 'product'}
    if not required <= payload.keys() or payload['product'] != PRODUCT:
        raise UserError('License could not be verified.')
    if payload['device_id'] != current_device:
        raise UserError('This license is registered to another device.')
    if payload['license_type'] not in ('LIFETIME', 'TRIAL'):
        raise UserError('License could not be verified.')
    if payload.get('expiry_date'):
        try:
            if date.fromisoformat(payload['expiry_date']) < date.today():
                raise UserError('This license has expired.')
        except ValueError:
            raise UserError('License could not be verified.') from None
    return payload


def trial_status(store):
    state = store.license_state()
    start = state.get('trial_started')
    if not start:
        return None
    today = date.today()
    try:
        started = date.fromisoformat(start)
        last_seen = date.fromisoformat(state.get('last_seen_date') or start)
    except ValueError:
        return {'valid': False, 'message': 'Trial data could not be verified.'}
    if today < last_seen:
        return {'valid': False, 'message': 'Device date was moved backwards. Contact the software vendor.'}
    remaining = 14 - (today - started).days
    store.update_license_state(last_seen_date=today.isoformat())
    return {'valid': remaining >= 0, 'remaining': max(0, remaining), 'message': 'Trial expired.' if remaining < 0 else ''}


def license_status(store, license_path):
    device = store.device_id()
    if Path(license_path).exists():
        try:
            return {'valid': True, 'kind': 'license', 'payload': validate_license(license_path, device), 'device_id': device}
        except UserError as error:
            return {'valid': False, 'kind': 'license', 'message': str(error), 'device_id': device}
    trial = trial_status(store)
    if trial:
        return {'valid': bool(trial['valid']), 'kind': 'trial', 'remaining': trial.get('remaining'), 'message': trial.get('message', ''), 'device_id': device}
    return {'valid': False, 'kind': 'none', 'message': 'Software activation is required.', 'device_id': device}
