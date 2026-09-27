"""Stable per-Windows-install device identity. No remote lookup is needed."""
import hashlib
import os
import platform
import uuid


def machine_anchor():
    value = ''
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as key:
                value = winreg.QueryValueEx(key, 'MachineGuid')[0]
        except OSError:
            pass
    return value or f'{platform.system()}|{platform.release()}|{uuid.getnode():012x}'


def device_id(installation_salt):
    encoded = (machine_anchor() + '|' + installation_salt).encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest().upper()
    return 'SSP-' + '-'.join((digest[0:4], digest[4:8], digest[8:12], digest[12:16]))
