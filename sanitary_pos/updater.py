"""Offline-first software update checks and verified downloads."""
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request

from .db import UserError
from .version import APP_VERSION
from .licensing import PUBLIC_KEY_HEX

UPDATE_REPOSITORY = 'zuhairzeb/sanitary-shop-pos-updates'
UPDATE_MANIFEST_URL = f'https://github.com/{UPDATE_REPOSITORY}/releases/latest/download/update.json'
UPDATE_MANIFEST_PUBLIC_KEY_HEX = PUBLIC_KEY_HEX
EXPECTED_PUBLISHER = ''
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
VERSION_PATTERN = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')


def parse_version(value):
    match = VERSION_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise UserError('The update information is invalid.')
    return tuple(int(part) for part in match.groups())


def newer_version(version, current=APP_VERSION):
    return parse_version(version) > parse_version(current)


def validate_manifest(document):
    if not isinstance(document, dict):
        raise UserError('The update information is invalid.')
    latest = document.get('latest_version')
    url = document.get('download_url')
    digest = document.get('sha256')
    parse_version(latest)
    if not isinstance(url, str) or not url.lower().startswith('https://'):
        raise UserError('The update information is invalid.')
    if not url.lower().split('?', 1)[0].endswith('.exe'):
        raise UserError('The update information is invalid.')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise UserError('The update information is invalid.')
    notes = document.get('release_notes', [])
    if not isinstance(notes, list) or not all(isinstance(note, str) and note.strip() for note in notes):
        raise UserError('The update information is invalid.')
    return {'latest_version': str(latest), 'download_url': url, 'sha256': digest.lower(), 'release_notes': notes[:8]}


def _verify_manifest_signature(document):
    if not isinstance(document, dict):
        raise UserError('The update information is invalid.')
    if not UPDATE_MANIFEST_PUBLIC_KEY_HEX:
        return
    signature = document.get('signature')
    if not isinstance(signature, str):
        raise UserError('The update information could not be verified.')
    import base64
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    signed = {key: value for key, value in document.items() if key != 'signature'}
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(UPDATE_MANIFEST_PUBLIC_KEY_HEX)).verify(
            base64.b64decode(signature, validate=True), json.dumps(signed, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    except (ValueError, TypeError, InvalidSignature):
        raise UserError('The update information could not be verified.') from None


def fetch_manifest(url=None, timeout=8):
    if url is None:
        url = UPDATE_MANIFEST_URL
    if not url:
        raise UserError('Software updates are not configured yet.')
    if not url.lower().startswith('https://'):
        raise UserError('The update information is invalid.')
    request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'SanitaryShopPOS-Updater/1'})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            document = json.loads(response.read(256 * 1024).decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UserError('No update has been published yet. You can continue using the POS normally.') from None
        raise UserError('The update service is unavailable. Please try again later.') from None
    except (OSError, urllib.error.URLError, ValueError, UnicodeError):
        raise UserError('No internet connection. You can continue using the POS normally.') from None
    _verify_manifest_signature(document)
    return validate_manifest(document)


def check_due(last_checked, now):
    try:
        return not last_checked or now - int(last_checked) >= CHECK_INTERVAL_SECONDS
    except (TypeError, ValueError):
        return True


def download_verified(manifest, destination=None, progress=None, timeout=30):
    manifest = validate_manifest(manifest)
    target = Path(destination) if destination else Path(tempfile.gettempdir()) / f"SanitaryShopPOS-{manifest['latest_version']}.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.download')
    request = urllib.request.Request(manifest['download_url'], headers={'User-Agent': 'SanitaryShopPOS-Updater/1'})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response, temporary.open('wb') as output:
            expected = int(response.headers.get('Content-Length') or 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                if progress:
                    progress(min(100, total * 100 // expected) if expected else None)
        if digest.hexdigest().lower() != manifest['sha256']:
            raise UserError('The update could not be verified. Your current POS is unchanged.')
        temporary.replace(target)
        return target
    except UserError:
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError):
        temporary.unlink(missing_ok=True)
        raise UserError('Update download failed. Your current POS is unchanged.') from None


def update_backup(store):
    destination = store.path.parent / f'before-update-{__import__("datetime").datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3'
    store.backup(destination)
    return destination


def verify_windows_signature(package):
    if not EXPECTED_PUBLISHER:
        return
    command = "(Get-AuthenticodeSignature -LiteralPath $args[0]).SignerCertificate.Subject"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command, str(package)], capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or EXPECTED_PUBLISHER not in result.stdout:
        raise UserError('The update could not be verified. Your current POS is unchanged.')
