"""Etiquetas Zebra (ZPL II).

Cada plantilla se describe como una lista de elementos en milímetros. A partir de esa
misma descripción se genera:
  * el ZPL que se envía a la impresora Zebra, y
  * una vista previa SVG con las mismas medidas (en puntos de impresión).
"""
import html

from .barcodes import (barcode_symbology, code128_values, ean13_check_digit,
                       ean13_modules, code128_modules, is_valid_upca, svg_rects)

DPMM = {"152": 6, "203": 8, "300": 12, "600": 24}
CHAR_W = 0.56  # ancho promedio de carácter de la fuente 0 respecto a su altura


# ---------------------------------------------------------------- plantillas

TEMPLATES = {
    "accesorio_50x25": {
        "name": "Accesorio 2\" x 1\" (50 x 25 mm)",
        "size": (50.8, 25.4),
        "description": "Etiqueta estándar: nombre, precio grande y código de barras.",
    },
    "chico_38x25": {
        "name": "Chica 1.5\" x 1\" (38 x 25 mm)",
        "size": (38.1, 25.4),
        "description": "Para fundas, micas y cables.",
    },
    "mini_32x19": {
        "name": "Mini 1.25\" x 0.75\" (32 x 19 mm)",
        "size": (31.75, 19.05),
        "description": "Etiqueta pequeña para empaques chicos.",
    },
    "celular_50x38": {
        "name": "Celular 2\" x 1.5\" (50 x 38 mm)",
        "size": (50.8, 38.1),
        "description": "Equipo con marca, modelo, capacidad, color, precio e IMEI.",
    },
    "anaquel_76x51": {
        "name": "Anaquel / exhibidor 3\" x 2\" (76 x 51 mm)",
        "size": (76.2, 50.8),
        "description": "Precio grande para vitrina o anaquel.",
    },
    "solo_codigo_50x25": {
        "name": "Solo código 2\" x 1\" (50 x 25 mm)",
        "size": (50.8, 25.4),
        "description": "Código de barras y SKU para control de inventario (sin precio).",
    },
}


def format_price(value, symbol="$"):
    value = float(value or 0)
    if abs(value - round(value)) < 0.005:
        return f"{symbol}{value:,.0f}"
    return f"{symbol}{value:,.2f}"


def _spec_line(d):
    return " · ".join(x for x in [d.get("capacity"), d.get("color")] if x)


def template_elements(template, d, show_store=True):
    """Regresa (ancho_mm, alto_mm, elementos) para una plantilla y los datos de la etiqueta."""
    tpl = TEMPLATES.get(template) or TEMPLATES["accesorio_50x25"]
    w, h = tpl["size"]
    store = d.get("store", "") if show_store else ""
    name = d.get("name", "")
    price = format_price(d.get("price"), d.get("symbol", "$")) if d.get("price") not in (None, "") else ""
    code = d.get("barcode") or d.get("sku") or ""
    sku = d.get("sku", "")
    code_text = code if not sku or sku == code else f"{code}  {sku}"
    E = []

    def text(x, y, tw, th, value, align="C", lines=1):
        if value:
            E.append({"t": "text", "x": x, "y": y, "w": tw, "h": th, "text": str(value), "align": align, "lines": lines})

    def bc(x, y, bw, bh, value):
        if value:
            E.append({"t": "barcode", "x": x, "y": y, "w": bw, "h": bh, "data": str(value)})

    if template == "chico_38x25":
        top = 1.2
        if store:
            text(1, top, w - 2, 2.0, store)
            top += 2.4
        text(1, top, w - 2, 2.5, name, lines=2)
        text(1, top + 5.8, w - 2, 5.4, price)
        bc(1.5, 17.0, w - 3, 5.0, code)
        text(1, 22.5, w - 2, 1.9, code)
    elif template == "mini_32x19":
        text(0.8, 0.9, w - 1.6, 2.2, name)
        text(0.8, 3.5, w - 1.6, 3.6, price)
        bc(1.0, 7.8, w - 2, 7.2, code)
        text(0.8, 15.6, w - 1.6, 1.9, code)
    elif template == "celular_50x38":
        imei = d.get("imei") or ""
        title = " ".join(x for x in [d.get("brand"), d.get("model")] if x) or name
        top = 1.2
        if store:
            text(1.5, top, w - 3, 2.2, store)
            top += 2.6
        text(1.5, top, w - 3, 3.2, title, lines=2)
        text(1.5, top + 7.2, w - 3, 2.4, _spec_line(d) or (name if title != name else ""))
        text(1.5, 13.8, w - 3, 7.0, price)
        if imei:
            bc(2, 21.6, w - 4, 7.6, imei)
            text(1.5, 29.8, w - 3, 2.3, f"IMEI: {imei}")
            text(1.5, 32.8, w - 3, 1.9, code_text)
        else:
            bc(2, 21.6, w - 4, 8.4, code)
            text(1.5, 30.6, w - 3, 2.2, code_text)
    elif template == "anaquel_76x51":
        top = 1.5
        if store:
            text(2, top, w - 4, 2.8, store)
            top += 3.4
        text(2, top, w - 4, 4.0, name, lines=2)
        spec = " ".join(x for x in [d.get("brand"), d.get("model"), d.get("capacity"), d.get("color")] if x)
        text(2, top + 9.0, w - 4, 2.6, spec)
        text(2, 18.5, w - 4, 13.5, price)
        bc(8, 34.0, w - 16, 10.0, code)
        text(2, 45.2, w - 4, 2.6, code_text)
    elif template == "solo_codigo_50x25":
        text(1.5, 1.3, w - 3, 2.6, name, lines=2)
        bc(2, 7.6, w - 4, 11.0, code)
        text(1.5, 19.6, w - 3, 2.4, code)
        if sku and sku != code:
            text(1.5, 22.3, w - 3, 2.0, sku)
    else:  # accesorio_50x25
        top = 1.2
        if store:
            text(1.5, top, w - 3, 2.1, store)
            top += 2.5
        text(1.5, top, w - 3, 2.7, name, lines=2)
        text(1.5, 10.1, w - 3, 6.4, price)
        bc(2.5, 17.1, w - 5, 5.1, code)
        text(1.5, 22.7, w - 3, 1.9, code_text)
    return w, h, E


# ---------------------------------------------------------------- utilidades

def wrap_text(text, max_chars, max_lines):
    words = str(text or "").split()
    lines, current = [], ""
    for word in words:
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last[: max(0, max_chars - 1)].rstrip() + "…") if len(last) >= max_chars else last + "…"
    return lines or [""]


def _fit_font(text, width_dots, height_dots, lines):
    """Reduce el tamaño de letra si el texto de una línea no cabe (precios, códigos)."""
    if lines > 1:
        return height_dots
    needed = len(text) * height_dots * CHAR_W
    if needed > width_dots:
        return max(10, int(width_dots / (len(text) * CHAR_W)))
    return height_dots


def _zpl_escape(text):
    out = []
    for ch in text:
        if ch in "_^~\\":
            out.append("_%02X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _normalize_barcode(data):
    """Regresa (simbología, datos, módulos)."""
    data = str(data).strip()
    if is_valid_upca(data):
        data = "0" + data
    sym = barcode_symbology(data)
    if sym == "EAN13":
        return sym, data, ean13_modules(data)
    clean = "".join(ch for ch in data if 32 <= ord(ch) <= 126) or "0"
    return "CODE128", clean, code128_modules(clean)


def _code128_zpl_data(text):
    """Datos para ^BC en modo N con cambios de subconjunto explícitos (igual que la vista previa)."""
    values = code128_values(text)[:-2]  # sin checksum ni stop
    out, subset = [], None
    for v in values:
        if v == 104:
            out.append(">:"); subset = "B"
        elif v == 105:
            out.append(">;"); subset = "C"
        elif v == 100 and subset == "C":
            out.append(">6"); subset = "B"
        elif v == 99 and subset == "B":
            out.append(">5"); subset = "C"
        elif subset == "C":
            out.append(f"{v:02d}")
        else:
            ch = chr(v + 32)
            out.append(">0" if ch == ">" else ch)
    return "".join(out)


def _layout(elements, dpmm):
    """Convierte mm → puntos y resuelve envoltura de texto y ancho de barras."""
    max_module = 3 if dpmm <= 8 else 4
    resolved = []
    for e in elements:
        x, y = round(e["x"] * dpmm), round(e["y"] * dpmm)
        w, h = round(e["w"] * dpmm), round(e["h"] * dpmm)
        if e["t"] == "text":
            lines = e.get("lines", 1)
            h = _fit_font(e["text"], w, h, lines)
            max_chars = max(1, int(w / (h * CHAR_W)))
            wrapped = wrap_text(e["text"], max_chars, lines)
            resolved.append({"t": "text", "x": x, "y": y, "w": w, "h": h, "lines": wrapped, "align": e.get("align", "C")})
        elif e["t"] == "barcode":
            sym, data, modules = _normalize_barcode(e["data"])
            module = max(1, min(max_module, w // len(modules)))
            bw = len(modules) * module
            bx = x + max(0, (w - bw) // 2)
            resolved.append({"t": "barcode", "x": bx, "y": y, "h": h, "module": module, "sym": sym,
                             "data": data, "modules": modules, "width": bw, "overflow": bw > w})
    return resolved


# ---------------------------------------------------------------- salida ZPL / SVG

def label_zpl(template, data, settings, copies=1):
    dpmm = DPMM.get(str(settings.get("label_dpi", "203")), 8)
    w_mm, h_mm, elements = template_elements(template, data, settings.get("label_show_store", "1") == "1")
    items = _layout(elements, dpmm)
    darkness = max(0, min(30, int(float(settings.get("label_darkness", 15) or 15))))
    speed = max(1, min(14, int(float(settings.get("label_speed", 4) or 4))))
    off_x = round(float(settings.get("label_offset_x", 0) or 0) * dpmm)
    off_y = round(float(settings.get("label_offset_y", 0) or 0) * dpmm)
    z = ["^XA", "^CI28", f"~SD{darkness:02d}", f"^PR{speed}", "^MMT",
         f"^PW{round(w_mm * dpmm)}", f"^LL{round(h_mm * dpmm)}", f"^LH{off_x},{off_y}"]
    for it in items:
        if it["t"] == "text":
            content = "\\&".join(_zpl_escape(line) for line in it["lines"])
            z.append(f"^FO{it['x']},{it['y']}^A0N,{it['h']},{it['h']}"
                     f"^FB{it['w']},{len(it['lines'])},0,{it['align']},0^FH^FD{content}^FS")
        elif it["sym"] == "EAN13":
            z.append(f"^FO{it['x']},{it['y']}^BY{it['module']},2,{it['h']}^BEN,{it['h']},N,N^FD{it['data'][:12]}^FS")
        else:
            z.append(f"^FO{it['x']},{it['y']}^BY{it['module']},2,{it['h']}"
                     f"^BCN,{it['h']},N,N,N,N^FD{_code128_zpl_data(it['data'])}^FS")
    z.append(f"^PQ{max(1, int(copies))},0,1,Y")
    z.append("^XZ")
    return "\n".join(z) + "\n"


def label_svg(template, data, settings, scale_px_per_mm=6):
    dpmm = DPMM.get(str(settings.get("label_dpi", "203")), 8)
    w_mm, h_mm, elements = template_elements(template, data, settings.get("label_show_store", "1") == "1")
    items = _layout(elements, dpmm)
    W, H = round(w_mm * dpmm), round(h_mm * dpmm)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'width="{w_mm * scale_px_per_mm:.0f}" height="{h_mm * scale_px_per_mm:.0f}" class="label-svg">',
           f'<rect width="{W}" height="{H}" rx="{dpmm}" fill="#fff" stroke="#c9c9c9"/>']
    for it in items:
        if it["t"] == "text":
            anchor = {"L": "start", "C": "middle", "R": "end"}[it["align"]]
            tx = {"L": it["x"], "C": it["x"] + it["w"] / 2, "R": it["x"] + it["w"]}[it["align"]]
            for i, line in enumerate(it["lines"]):
                ty = it["y"] + i * it["h"] + it["h"] * 0.86
                out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{it["h"]}" text-anchor="{anchor}" '
                           f'font-family="Arial Narrow, Roboto Condensed, Arial, sans-serif" font-weight="700" '
                           f'fill="#000">{html.escape(line)}</text>')
        else:
            color = "#c00" if it["overflow"] else "#000"
            out.append(f'<g fill="{color}">{svg_rects(it["modules"], it["x"], it["y"], it["module"], it["h"])}</g>')
    out.append("</svg>")
    return "".join(out)


def label_data_from_product(product, settings, imei=None):
    return {
        "store": settings.get("store_name", ""),
        "symbol": settings.get("currency_symbol", "$"),
        "name": product.get("name", ""),
        "brand": product.get("brand", ""),
        "model": product.get("model", ""),
        "color": product.get("color", ""),
        "capacity": product.get("capacity", ""),
        "price": product.get("price", 0),
        "sku": product.get("sku", ""),
        "barcode": product.get("barcode") or product.get("sku", ""),
        "imei": imei or "",
    }


def test_label_zpl(settings):
    data = {"store": settings.get("store_name", ""), "name": "PRUEBA DE IMPRESION Zebra áéíóú ñ",
            "price": 199, "sku": "TEST-0001", "barcode": "2000000000015", "symbol": "$"}
    return label_zpl(settings.get("label_template", "accesorio_50x25"), data, settings)
