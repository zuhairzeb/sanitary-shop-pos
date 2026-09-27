"""One-use, device-bound vendor authorization for a forgotten owner PIN."""
import base64
import json
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import licensing
from .db import UserError
from .security import hash_pin, timestamp


def create_request(store, user_id):
    user = store.user(user_id)
    if user['role'] != 'OWNER' or not user['active']:
        raise UserError('Ask the shop Owner to reset your PIN in Users & Privileges.')
    request = dict(product=licensing.PRODUCT, purpose='owner-pin-reset', device_id=store.device_id(),
                   user_id=user_id, owner_name=user['name'], nonce=secrets.token_hex(24),
                   expires_at=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat())
    store.update_security_state(owner_recovery=json.dumps(request))
    return request


def apply_recovery(store, text, new_pin):
    try:
        document = licensing.decode_key(text, 'SSPR1')
        request = document['recovery']
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(licensing.PUBLIC_KEY_HEX)).verify(
            base64.b64decode(document['signature'], validate=True), licensing.canonical(request))
        pending = json.loads(store.security_state().get('owner_recovery') or '{}')
        if not pending or request != pending or request['purpose'] != 'owner-pin-reset' or request['product'] != licensing.PRODUCT:
            raise ValueError()
        if request['device_id'] != store.device_id() or datetime.fromisoformat(request['expires_at']) < datetime.now(timezone.utc):
            raise ValueError()
        user = store.user(request['user_id'])
        if user['role'] != 'OWNER' or not user['active']:
            raise ValueError()
    except (ValueError, TypeError, KeyError, InvalidSignature):
        raise UserError('Recovery key is invalid, expired or already used. Request a new key from your vendor.') from None
    salt, digest = hash_pin(new_pin)
    with store.conn:
        store.conn.execute('UPDATE pos_users SET pin_salt=?,pin_hash=?,updated_at=? WHERE id=?',
                           (salt, digest, timestamp(), user['id']))
        store.conn.execute("DELETE FROM security_state WHERE key='owner_recovery'")
    store.audit('Vendor approved owner PIN reset', user['name'])
