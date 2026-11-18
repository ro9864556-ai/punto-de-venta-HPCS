"""Logo de la tienda: conversión a 1 bit para impresoras térmicas (ESC/POS) y Zebra (ZPL)."""
import io
import os

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow es opcional: sin él los tickets salen sin logo
    Image = None

STATIC_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "logo.png")


def logo_path(data_dir):
    custom = os.path.join(data_dir, "logo.png")
    if os.path.exists(custom):
        return custom
    return STATIC_LOGO if os.path.exists(STATIC_LOGO) else None


def save_logo(data_dir, file_bytes):
    if Image is None:
        raise ValueError("Instala Pillow para cambiar el logo:  pip install Pillow")
    im = Image.open(io.BytesIO(file_bytes))
    im = ImageOps.exif_transpose(im).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("RGB")
    # recorta el margen blanco
    bbox = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 55 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    im.thumbnail((800, 800))
    im.save(os.path.join(data_dir, "logo.png"), optimize=True)


def monochrome(path, width_dots, threshold=150):
    """Imagen 1 bit (True = punto negro) escalada al ancho indicado."""
    if Image is None or not path or not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("L")
    w = max(8, int(width_dots))
    h = max(1, round(im.height * w / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    # umbral (no tramado): los colores sólidos del logo salen negros y nítidos
    return im.point(lambda v: 0 if v < threshold else 255, mode="1")


def _rows(img):
    w, h = img.size
    width_bytes = (w + 7) // 8
    px = img.load()
    rows = []
    for y in range(h):
        row = bytearray(width_bytes)
        for x in range(w):
            if px[x, y] == 0:
                row[x // 8] |= 0x80 >> (x % 8)
        rows.append(bytes(row))
    return width_bytes, rows


def escpos_raster(img):
    """Comando GS v 0 (imagen raster) en bloques para no saturar el búfer de la impresora."""
    width_bytes, rows = _rows(img)
    out = bytearray()
    for start in range(0, len(rows), 128):
        chunk = rows[start:start + 128]
        out += b"\x1dv0\x00" + bytes([width_bytes & 0xFF, width_bytes >> 8, len(chunk) & 0xFF, len(chunk) >> 8])
        out += b"".join(chunk)
    return bytes(out)


def zpl_graphic(img, x, y):
    """Campo ^GFA con la imagen en hexadecimal."""
    width_bytes, rows = _rows(img)
    data = "".join(r.hex().upper() for r in rows)
    total = width_bytes * len(rows)
    return f"^FO{x},{y}^GFA,{total},{total},{width_bytes},{data}^FS"


def png_bytes(img):
    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
