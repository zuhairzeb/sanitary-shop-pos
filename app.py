"""Run with python app.py, or use the packaged SanitaryShopPOS.exe."""
import argparse
import logging
import os
from pathlib import Path
import sys


def enable_windows_dpi_awareness():
    if os.name != 'nt' or (not getattr(sys, 'frozen', False) and os.environ.get('POS_DPI_AWARE') != '1'):
        return
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


enable_windows_dpi_awareness()

vendor = Path(__file__).resolve().parent / '.vendor'
if vendor.exists():
    sys.path.insert(0, str(vendor))
    if not getattr(sys, 'frozen', False) and (vendor / 'tcl/tcl8.6').exists():
        os.environ['TCL_LIBRARY'] = str(vendor / 'tcl/tcl8.6')
        os.environ['TK_LIBRARY'] = str(vendor / 'tcl/tk8.6')

from sanitary_pos.db import Store
from sanitary_pos.ui import App
from sanitary_pos.auth_ui import SecurityScreen


def main():
    parser = argparse.ArgumentParser(description='Offline sanitary shop billing')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SanitaryShopPOS')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--performance-test-db', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.performance_test_db and getattr(sys, 'frozen', False):
        raise RuntimeError('Performance test mode is available only from the developer source checkout.')
    database_path = args.data_dir if args.performance_test_db else args.data_dir / 'shop.sqlite3'
    data_dir = database_path.parent if args.performance_test_db else args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data_dir / 'app.log', level=logging.ERROR)
    lock = open(data_dir / 'app.lock', 'a+b')
    lock.seek(0, 2)
    if lock.tell() == 0:
        lock.write(b'1')
        lock.flush()
    lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo('Already open', 'Sanitary Shop is already running. Please use the open window.')
            root.destroy()
            return
    try:
        while True:
            store = Store(database_path)
            development_test = bool(args.performance_test_db and store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dev_performance_marker'").fetchone())
            if args.performance_test_db and not development_test:
                store.conn.close()
                raise RuntimeError('The performance-test launch requires a marked development database.')
            if not args.smoke_test and not development_test:
                if not SecurityScreen(store, data_dir / 'license.json').start():
                    store.conn.close()
                    return
            app = App(store, development_mode=development_test)
            if args.smoke_test:
                app.after(750, app.close)
            app.mainloop()
            if not getattr(app, 'switch_requested', False):
                break
    except Exception:
        logging.exception('Startup failed')
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Could not open shop data', 'Could not open the shop data. Check that the data folder is available and writable. Details are in app.log.')
        root.destroy()
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    main()
