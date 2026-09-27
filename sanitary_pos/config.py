import os
from pathlib import Path


def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SanitaryShopPOS'


def get_data_dir(default_dir=None, config_path=None):
    base_dir = Path(default_dir or default_data_dir()).expanduser().resolve()
    config_file = Path(config_path or base_dir / 'data-dir.txt').expanduser().resolve()
    if config_file.exists():
        text = config_file.read_text(encoding='utf-8').strip()
        if text:
            data_dir = Path(text).expanduser().resolve()
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def set_data_dir(data_dir, config_path=None):
    resolved = Path(data_dir).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    config_file = Path(config_path or default_data_dir() / 'data-dir.txt').expanduser().resolve()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(str(resolved), encoding='utf-8')
    return resolved
