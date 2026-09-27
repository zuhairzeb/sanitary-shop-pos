"""Store a small normalized logo in SQLite so backups include it."""
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps
from .db import UserError


def encode_logo(path):
    if Path(path).stat().st_size > 5 * 1024 * 1024:
        raise UserError('Choose a logo smaller than 5 MB.')
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGBA')
            image.thumbnail((512, 512))
            output = BytesIO()
            image.save(output, format='PNG')
        return base64.b64encode(output.getvalue()).decode('ascii')
    except (OSError, ValueError, Image.DecompressionBombError):
        raise UserError('Choose a valid PNG, JPG or GIF image.') from None
