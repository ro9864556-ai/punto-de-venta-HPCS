"""Generador de precios, SKU y códigos de barras internos."""
import math
import re
import unicodedata

from .barcodes import ean13_check_digit

ROUNDING_MODES = {
    "none": "Sin redondeo (centavos exactos)",
    "1": "Al peso (149.37 → 150)",
    "5": "Múltiplos de 5 (147 → 150)",
    "10": "Múltiplos de 10 (143 → 150)",
    "9": "Terminación en 9 (143 → 149)",
    "99": "Terminación .99 (143.2 → 143.99)",
    "90": "Terminación .90 (143.2 → 143.90)",
    "50": "Medio peso (143.2 → 143.50)",
}


def round_price(value, mode="9"):
    """Redondea SIEMPRE hacia arriba según el modo (para no perder margen)."""
    value = float(value or 0)
    if value <= 0:
        return 0.0
    eps = 1e-9
    if mode == "none":
        return round(value, 2)
    if mode == "1":
        return float(math.ceil(value - eps))
    if mode == "5":
        return float(math.ceil(value / 5 - eps) * 5)
    if mode == "10":
        return float(math.ceil(value / 10 - eps) * 10)
    if mode == "9":
        # 143 → 149, 150 → 159, 9 → 9, 3 → 9
        result = math.ceil((value + 1) / 10 - eps) * 10 - 1
        return float(result)
    if mode == "99":
        return round(math.ceil(value + 0.01 - eps) - 0.01, 2)
    if mode == "90":
        return round(math.ceil(value + 0.10 - eps) - 0.10, 2)
    if mode == "50":
        return round(math.ceil(value * 2 - eps) / 2, 2)
    return round(value, 2)


def suggest_price(cost, markup_percent, tax_rate=16, cost_includes_tax=True,
                  prices_include_tax=True, rounding="9"):
    """Calcula precio de venta a partir del costo.

    * markup_percent: % de ganancia sobre el costo (100 = el doble).
    * Si el costo NO incluye IVA y los precios al público sí, se agrega IVA.
    """
    cost = float(cost or 0)
    markup = float(markup_percent or 0)
    tax = float(tax_rate or 0) / 100.0
    price = cost * (1 + markup / 100.0)
    if prices_include_tax and not cost_includes_tax:
        price *= (1 + tax)
    if not prices_include_tax and cost_includes_tax:
        price /= (1 + tax)
    final = round_price(price, rounding)
    profit = final - cost
    margin = (profit / final * 100) if final else 0
    return {
        "price": final,
        "raw_price": round(price, 2),
        "profit": round(profit, 2),
        "margin_percent": round(margin, 1),
        "markup_percent": round((profit / cost * 100) if cost else 0, 1),
    }


def _slug(text, length):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return text[:length]


def generate_sku(conn, category_id=None, brand=""):
    """SKU legible: PREFIJO-MARCA-0001 (p. ej. FUN-SAM-0007)."""
    prefix = "GEN"
    if category_id:
        row = conn.execute("SELECT prefix FROM categories WHERE id=?", (category_id,)).fetchone()
        if row:
            prefix = row["prefix"]
    brand_code = _slug(brand, 3)
    base = f"{prefix}-{brand_code}-" if brand_code else f"{prefix}-"
    rows = conn.execute("SELECT sku FROM products WHERE sku LIKE ?", (base + "%",)).fetchall()
    max_n = 0
    for r in rows:
        tail = r["sku"][len(base):]
        if tail.isdigit():
            max_n = max(max_n, int(tail))
    n = max_n + 1
    while True:
        sku = f"{base}{n:04d}"
        if not conn.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone():
            return sku
        n += 1


def generate_internal_barcode(conn, prefix="20"):
    """EAN-13 interno (prefijo 20-29 reservado para uso en tienda) con dígito verificador."""
    prefix = re.sub(r"\D", "", str(prefix or "20"))[:4] or "20"
    body_len = 12 - len(prefix)
    row = conn.execute("SELECT value FROM settings WHERE key='barcode_seq'").fetchone()
    seq = int(row["value"]) if row else 0
    while True:
        seq += 1
        code12 = prefix + str(seq).zfill(body_len)
        code = code12 + ean13_check_digit(code12)
        exists = conn.execute("SELECT 1 FROM products WHERE barcode=?", (code,)).fetchone()
        if not exists:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('barcode_seq', ?)", (str(seq),))
            return code


def money(value, symbol="$"):
    value = float(value or 0)
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.2f}"
