"""Per-user Windows installer. Includes the complete application runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox
import winreg
from sanitary_pos.version import APP_VERSION

ROOT = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'SanitaryShopPOS'
KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\SanitaryShopPOS'
APP_NAME = 'Sanitary Shop POS'
START_MENU = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


class ApplicationStillOpenError(RuntimeError):
    """Raised only after the update installer has allowed the POS time to close."""


def resolve_payload_source():
    """Return the packaged app directory for installation.

    PyInstaller provides the bundled payload under sys._MEIPASS when frozen.
    When running from a source checkout, we fall back to the built portable app
    folder that lives next to the setup script.
    """
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            payload = Path(meipass) / 'payload'
            if payload.exists():
                return payload
    base_dir = Path(__file__).resolve().parent
    for candidate in (
        base_dir / 'payload',
        base_dir / 'dist' / 'SanitaryShopPOS',
        base_dir / 'build' / 'SanitaryShopPOS',
        base_dir / 'SanitaryShopPOS',
    ):
        if (candidate / 'SanitaryShopPOS.exe').is_file():
            return candidate
    raise FileNotFoundError('Could not find the packaged SanitaryShopPOS app bundle.')


def copy_application(destination):
    source = resolve_payload_source()
    if not (source / 'SanitaryShopPOS.exe').is_file():
        raise RuntimeError('Application files are incomplete. Please use the complete setup executable.')
    setup = Path(sys.executable) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent / 'dist' / 'SanitaryShopPOS-Setup.exe'
    if not setup.is_file():
        raise RuntimeError('Build or copy the setup executable before installing from source.')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    # An in-app update starts this installer just before the POS exits. Windows
    # keeps the executable and loaded DLLs locked briefly, so retry rather than
    # showing the user a long list of locked internal files.
    last_error = None
    for attempt in range(30):
        try:
            shutil.copytree(source, destination, dirs_exist_ok=True)
            uninstall_copy = destination / 'Uninstall.exe'
            if setup.resolve() != uninstall_copy.resolve():
                shutil.copy2(setup, uninstall_copy)
            return
        except (PermissionError, OSError, shutil.Error) as error:
            last_error = error
            if attempt < 29:
                time.sleep(1)
    raise ApplicationStillOpenError(
        'Sanitary Shop POS is still open. Please close it completely and then run the setup again.'
    ) from last_error


def install():
    copy_application(ROOT)
    app_exe = ROOT / 'SanitaryShopPOS.exe'
    uninstall_cmd = f'"{ROOT / "Uninstall.exe"}" --uninstall'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        for name, value in {
            'DisplayName': APP_NAME,
            'DisplayVersion': APP_VERSION,
            'Publisher': 'Sanitary Shop',
            'InstallLocation': str(ROOT),
            'UninstallString': uninstall_cmd,
            'QuietUninstallString': uninstall_cmd,
            'DisplayIcon': str(app_exe),
            'NoModify': '1',
            'NoRepair': '1',
        }.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    START_MENU.mkdir(parents=True, exist_ok=True)
    env = os.environ | {'SHOP_EXE': str(app_exe), 'SHOP_UNINSTALL': str(ROOT / 'Uninstall.exe')}
    subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                    "$w = New-Object -ComObject WScript.Shell; $app = $w.CreateShortcut([IO.Path]::Combine($env:APPDATA,'Microsoft','Windows','Start Menu','Programs','Sanitary Shop POS.lnk')); $app.TargetPath = $env:SHOP_EXE; $app.Save(); $uninstall = $w.CreateShortcut([IO.Path]::Combine($env:APPDATA,'Microsoft','Windows','Start Menu','Programs','Uninstall Sanitary Shop POS.lnk')); $uninstall.TargetPath = $env:SHOP_UNINSTALL; $uninstall.Arguments = '--uninstall'; $uninstall.IconLocation = $env:SHOP_EXE + ',0'; $uninstall.Save()"],
                   env=env, check=True, creationflags=0x08000000)


def uninstall():
    expected = (Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'SanitaryShopPOS').resolve()
    if ROOT.resolve() != expected:
        raise RuntimeError('Invalid installation folder.')
    for child in ROOT.iterdir():
        if child.name == 'Uninstall.exe':
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
    except FileNotFoundError:
        pass
    for link in (
        START_MENU / 'Sanitary Shop POS.lnk',
        START_MENU / 'Uninstall Sanitary Shop POS.lnk',
    ):
        link.unlink(missing_ok=True)
    env = os.environ | {'SHOP_UNINSTALL_ROOT': str(ROOT)}
    subprocess.Popen(['powershell.exe', '-NoProfile', '-Command',
                      "Start-Sleep -Seconds 3; Remove-Item -LiteralPath (Join-Path $env:SHOP_UNINSTALL_ROOT 'Uninstall.exe') -Force; Remove-Item -LiteralPath $env:SHOP_UNINSTALL_ROOT -Recurse -Force"],
                     env=env, creationflags=0x08000000)


if __name__ == '__main__':
    if '--verify-install' in sys.argv:
        import tempfile
        with tempfile.TemporaryDirectory(prefix='pos-install-check-') as folder:
            destination = Path(folder) / 'installed'
            copy_application(destination)
            result = subprocess.run([str(destination / 'SanitaryShopPOS.exe'), '--smoke-test', '--data-dir', str(Path(folder) / 'data')], timeout=40)
            if result.returncode:
                raise RuntimeError('Installed application startup failed.')
        sys.exit(0)
    root = tk.Tk()
    root.title('Sanitary Shop POS Setup')
    root.geometry('520x270')
    root.resizable(False, False)
    remove = '--uninstall' in sys.argv
    updating = not remove and (ROOT / 'SanitaryShopPOS.exe').is_file()
    action_text = 'Uninstall' if remove else 'Update and Open' if updating else 'Install and Open'
    success_text = 'Application removed. Shop data kept.' if remove else 'Application updated. The latest version is now open.' if updating else 'Installed. Find Sanitary Shop POS in the Start menu.'
    description = ('Remove the application. Your shop data will be kept.' if remove else
                   'An existing installation was found. Update the application without uninstalling.' if updating else
                   'Offline billing, products and stock.\nEverything needed is included. No internet required.')
    ttk.Label(root, text='Sanitary Shop POS', font=('Segoe UI', 23, 'bold')).pack(pady=22)
    ttk.Label(root, text=description,
              font=('Segoe UI', 12), justify='center').pack(pady=8)
    status = tk.StringVar()
    ttk.Label(root, textvariable=status).pack(pady=8)

    def run():
        action.configure(state='disabled')
        status.set('Please wait...')
        root.update()
        try:
            (uninstall if remove else install)()
            if not remove:
                subprocess.Popen([str(ROOT / 'SanitaryShopPOS.exe')])
            messagebox.showinfo('Finished', success_text)
            root.destroy()
        except Exception as error:
            messagebox.showerror('Setup could not finish', str(error))
            action.configure(state='normal')
    action = ttk.Button(root, text=action_text, command=run)
    action.pack(ipadx=30, ipady=10)
    if '--smoke-test' in sys.argv:
        root.after(750, root.destroy)
    root.mainloop()
