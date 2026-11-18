"""Tickets de venta y corte de caja.

Un ticket se arma como una lista de renglones (modelo) y luego se convierte a:
  * ESC/POS (impresoras térmicas de tickets 58/80 mm),
  * HTML para imprimir desde el navegador,
  * ZPL para imprimirlo en una impresora Zebra,
  * texto plano.
"""
import html

from .barcodes import code128_modules, svg_rects
from .labels import DPMM, _code128_zpl_data, _zpl_escape, wrap_text
from .pricing import money

PAYMENT_NAMES = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia", "mixto": "Mixto"}


def chars_for_width(width_mm):
    return 32 if str(width_mm) == "58" else 48


class Ticket:
    def __init__(self, width_chars):
        self.width = width_chars
        self.lines = []

    def text(self, value, align="L", bold=False, big=False):
        limit = self.width // 2 if big else self.width
        for line in wrap_text(value, limit, 50):
            self.lines.append(("text", line, align, bold, big))

    def cols(self, left, right, bold=False):
        left, right = str(left), str(right)
        space = self.width - len(right) - 1
        if len(left) > space:
            # el texto largo se va arriba y el importe abajo a la derecha
            for line in wrap_text(left, self.width, 5):
                self.lines.append(("cols", line, "", bold))
            left = ""
        self.lines.append(("cols", left, right, bold))

    def sep(self, char="-"):
        self.lines.append(("sep", char))

    def barcode(self, data):
        self.lines.append(("barcode", data))

    def feed(self, n=1):
        self.lines.append(("feed", n))


# ---------------------------------------------------------------- construcción

def _store_header(t, s):
    t.text(s.get("store_name", ""), "C", bold=True, big=True)
    for key in ("store_legal_name", "store_rfc", "store_address", "store_phone", "store_whatsapp"):
        value = (s.get(key) or "").strip()
        if not value:
            continue
        prefix = {"store_rfc": "RFC: ", "store_phone": "Tel: ", "store_whatsapp": "WhatsApp: "}.get(key, "")
        t.text(prefix + value, "C")
    if (s.get("ticket_header") or "").strip():
        t.text(s["ticket_header"].strip(), "C")


def build_sale_ticket(sale, items, s, reprint=False):
    sym = s.get("currency_symbol", "$")
    m = lambda v: money(v, sym)  # noqa: E731
    t = Ticket(chars_for_width(s.get("ticket_width", "80")))
    _store_header(t, s)
    t.sep("=")
    if sale.get("status") == "cancelada":
        t.text("*** VENTA CANCELADA ***", "C", bold=True)
    if reprint:
        t.text("** REIMPRESIÓN **", "C", bold=True)
    t.cols("Folio:", sale["folio"], bold=True)
    t.cols("Fecha:", sale["created_at"][:16])
    if sale.get("cashier"):
        t.cols("Atendió:", sale["cashier"])
    if sale.get("customer_name"):
        t.cols("Cliente:", sale["customer_name"])
    if sale.get("customer_phone"):
        t.cols("Tel. cliente:", sale["customer_phone"])
    t.sep()
    units = 0
    for it in items:
        qty = float(it["qty"])
        units += qty
        qty_txt = f"{qty:g}"
        t.text(it["name"])
        t.cols(f"  {qty_txt} x {m(it['unit_price'])}", m(qty * float(it["unit_price"])))
        if float(it.get("discount") or 0):
            t.cols("  Descuento", "-" + m(it["discount"]))
        if it.get("imei"):
            t.text(f"  IMEI/Serie: {it['imei']}")
        if it.get("sku"):
            t.text(f"  SKU: {it['sku']}")
        if int(it.get("warranty_days") or 0):
            t.text(f"  Garantía: {it['warranty_days']} días")
    t.sep()
    t.cols("Artículos:", f"{units:g}")
    items_total = sum(float(i["qty"]) * float(i["unit_price"]) for i in items)
    line_disc = sum(float(i.get("discount") or 0) for i in items)
    t.cols("Importe:", m(items_total))
    if line_disc + float(sale.get("discount") or 0) > 0.004:
        t.cols("Descuentos:", "-" + m(line_disc + float(sale.get("discount") or 0)))
    if s.get("show_tax_breakdown", "1") == "1" and float(sale.get("tax") or 0) > 0:
        t.cols("Subtotal:", m(float(sale["total"]) - float(sale["tax"])))
        t.cols(f"IVA {float(s.get('tax_rate', 16)):g}%:", m(sale["tax"]))
    t.text(f"TOTAL {m(sale['total'])}", "R", bold=True, big=True)
    t.sep()
    method = sale.get("payment_method", "efectivo")
    if method == "mixto":
        for key, label in (("paid_cash", "Efectivo"), ("paid_card", "Tarjeta"), ("paid_transfer", "Transferencia")):
            if float(sale.get(key) or 0):
                t.cols(f"{label}:", m(sale[key]))
    else:
        t.cols(f"Pago con {PAYMENT_NAMES.get(method, method)}:", m(sale.get("received") or sale["total"]))
    if float(sale.get("change") or 0) > 0:
        t.cols("Cambio:", m(sale["change"]), bold=True)
    if sale.get("notes"):
        t.sep()
        t.text("Notas: " + sale["notes"])
    t.sep()
    if any(int(i.get("warranty_days") or 0) or i.get("imei") for i in items) and (s.get("warranty_text") or "").strip():
        t.text(s["warranty_text"].strip(), "C")
        t.feed()
    if (s.get("ticket_footer") or "").strip():
        t.text(s["ticket_footer"].strip(), "C", bold=True)
    t.feed()
    t.barcode(sale["folio"])
    t.feed(2)
    return t


def build_cut_ticket(report, s):
    sym = s.get("currency_symbol", "$")
    m = lambda v: money(v, sym)  # noqa: E731
    t = Ticket(chars_for_width(s.get("ticket_width", "80")))
    t.text(s.get("store_name", ""), "C", bold=True, big=True)
    t.text("CORTE DE CAJA", "C", bold=True)
    t.sep("=")
    t.cols("Desde:", report["from"])
    t.cols("Hasta:", report["to"])
    t.cols("Impreso:", report["generated_at"][:16])
    t.sep()
    t.cols("Ventas realizadas:", str(report["sales_count"]))
    t.cols("Ventas canceladas:", str(report["cancelled_count"]))
    t.cols("Piezas vendidas:", f"{report['units']:g}")
    t.sep()
    t.text("POR FORMA DE PAGO", bold=True)
    t.cols("Efectivo:", m(report["cash"]))
    t.cols("Tarjeta:", m(report["card"]))
    t.cols("Transferencia:", m(report["transfer"]))
    t.cols("TOTAL VENDIDO:", m(report["total"]), bold=True)
    t.sep()
    t.text("EFECTIVO EN CAJA", bold=True)
    t.cols("Fondo / entradas:", m(report["cash_in"]))
    t.cols("Ventas en efectivo:", m(report["cash"]))
    t.cols("Retiros / gastos:", "-" + m(report["cash_out"]))
    t.cols("Esperado en caja:", m(report["expected_cash"]), bold=True)
    t.sep()
    t.cols("Descuentos dados:", m(report["discounts"]))
    t.cols("IVA incluido:", m(report["tax"]))
    t.cols("Costo de lo vendido:", m(report["cost"]))
    t.cols("Utilidad bruta:", m(report["profit"]), bold=True)
    if report.get("by_category"):
        t.sep()
        t.text("POR CATEGORÍA", bold=True)
        for row in report["by_category"]:
            t.cols(f"{row['category']} ({row['units']:g})", m(row["total"]))
    t.sep()
    t.feed()
    t.text("Firma: ____________________", "C")
    t.feed(2)
    return t


def build_test_ticket(s):
    t = Ticket(chars_for_width(s.get("ticket_width", "80")))
    _store_header(t, s)
    t.sep("=")
    t.text("PRUEBA DE IMPRESIÓN", "C", bold=True, big=True)
    t.text("Acentos: áéíóú ÁÉÍÓÚ ñÑ ü ¿? ¡!", "C")
    t.cols("Artículo de prueba", money(199, s.get("currency_symbol", "$")))
    t.sep()
    t.barcode("TEST-0001")
    t.feed(2)
    return t


# ---------------------------------------------------------------- renderizadores

def _cols_line(width, left, right):
    space = width - len(right)
    return left[:space].ljust(space) + right


def to_text(t):
    out = []
    for ln in t.lines:
        kind = ln[0]
        if kind == "text":
            _, value, align, _, big = ln
            w = t.width // 2 if big else t.width
            value = {"L": value.ljust(w), "C": value.center(w), "R": value.rjust(w)}[align].rstrip()
            out.append(value)
        elif kind == "cols":
            out.append(_cols_line(t.width, ln[1], ln[2]))
        elif kind == "sep":
            out.append(ln[1] * t.width)
        elif kind == "barcode":
            out.append(f"[{ln[1]}]".center(t.width))
        elif kind == "feed":
            out.extend([""] * ln[1])
    return "\n".join(out)


ESC, GS = b"\x1b", b"\x1d"


def _enc(text):
    return text.encode("cp850", errors="replace")


def to_escpos(t, open_drawer=False, cut=True):
    out = bytearray(ESC + b"@" + ESC + b"t\x02")  # inicializa, página de códigos PC850 (acentos)
    for ln in t.lines:
        kind = ln[0]
        if kind == "text":
            _, value, align, bold, big = ln
            out += ESC + b"a" + bytes([{"L": 0, "C": 1, "R": 2}[align]])
            out += ESC + b"E" + (b"\x01" if bold else b"\x00")
            out += GS + b"!" + (b"\x11" if big else b"\x00")
            out += _enc(value) + b"\n"
            out += GS + b"!\x00" + ESC + b"E\x00"
        elif kind == "cols":
            out += ESC + b"a\x00" + ESC + b"E" + (b"\x01" if ln[3] else b"\x00")
            out += _enc(_cols_line(t.width, ln[1], ln[2])) + b"\n" + ESC + b"E\x00"
        elif kind == "sep":
            out += ESC + b"a\x00" + _enc(ln[1] * t.width) + b"\n"
        elif kind == "barcode":
            data = ln[1].encode("ascii", errors="replace")
            payload = b"{B" + data
            out += ESC + b"a\x01" + GS + b"h\x50" + GS + b"w\x02" + GS + b"H\x02" + GS + b"f\x00"
            out += GS + b"kI" + bytes([len(payload)]) + payload + b"\n" + ESC + b"a\x00"
        elif kind == "feed":
            out += b"\n" * ln[1]
    out += b"\n\n\n"
    if open_drawer:
        out += ESC + b"p\x00\x19\xfa"
    if cut:
        out += GS + b"V\x42\x03"
    return bytes(out)


def to_html(t, width_mm=80, title="Ticket", autoprint=False):
    paper = 58 if str(width_mm) == "58" else 80
    body = []
    for ln in t.lines:
        kind = ln[0]
        if kind == "text":
            _, value, align, bold, big = ln
            cls = ["l", {"L": "al", "C": "ac", "R": "ar"}[align]]
            if bold:
                cls.append("b")
            if big:
                cls.append("big")
            body.append(f'<div class="{" ".join(cls)}">{html.escape(value) or "&nbsp;"}</div>')
        elif kind == "cols":
            b = " b" if ln[3] else ""
            body.append(f'<div class="l row{b}"><span>{html.escape(ln[1])}</span><span>{html.escape(ln[2])}</span></div>')
        elif kind == "sep":
            body.append(f'<div class="sep sep-{"eq" if ln[1] == "=" else "dash"}"></div>')
        elif kind == "barcode":
            mods = code128_modules(ln[1])
            body.append(f'<div class="ac bc"><svg viewBox="0 0 {len(mods)} 40" preserveAspectRatio="none">'
                        f'{svg_rects(mods, 0, 0, 1, 40)}</svg><div>{html.escape(ln[1])}</div></div>')
        elif kind == "feed":
            body.append('<div class="l">&nbsp;</div>' * ln[1])
    script = "<script>window.addEventListener('load',()=>{setTimeout(()=>window.print(),250)});</script>" if autoprint else ""
    pad = 2 if paper == 58 else 4
    # Courier mide 0.6em por carácter: el tamaño se calcula para que quepan exactamente los caracteres del ticket
    font_mm = (paper - 2 * pad) / (t.width * 0.6)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
@page {{ size: {paper}mm auto; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: #fff; color: #000; }}
body {{ width: {paper}mm; padding: 3mm {pad}mm; font: {font_mm:.3f}mm/1.3 'Courier New', Courier, monospace; }}
.l {{ white-space: pre; overflow: hidden; }}
.al {{ text-align: left; }} .ac {{ text-align: center; }} .ar {{ text-align: right; }}
.b {{ font-weight: 700; }} .big {{ font-size: 2em; font-weight: 700; line-height: 1.15; }}
.row {{ display: flex; justify-content: space-between; }}
.row span:first-child {{ overflow: hidden; }}
.row span:last-child {{ white-space: pre; }}
.sep {{ margin: 3px 0; }} .sep-dash {{ border-top: 1px dashed #000; }} .sep-eq {{ border-top: 3px double #000; }}
.bc svg {{ width: 80%; height: 34px; display: block; margin: 4px auto 1px; }}
@media screen {{ body {{ margin: 12px auto; box-shadow: 0 2px 14px rgba(0,0,0,.18); }} html {{ background: #e9e9e9; }} }}
</style></head><body>{''.join(body)}{script}</body></html>"""


def to_zpl(t, settings):
    """Ticket como etiqueta continua para impresora Zebra."""
    dpmm = DPMM.get(str(settings.get("label_dpi", "203")), 8)
    width_mm = float(settings.get("ticket_zebra_width_mm", "76") or 76)
    pw = round(width_mm * dpmm)
    margin = round(2 * dpmm)
    inner = pw - 2 * margin
    fh = max(16, int(inner / (t.width * 0.56)))  # alto de letra para que quepan los caracteres
    lh = int(fh * 1.25)
    y = margin
    z = []
    for ln in t.lines:
        kind = ln[0]
        if kind == "text":
            _, value, align, bold, big = ln
            h = fh * 2 if big else fh
            z.append(f"^FO{margin},{y}^A0N,{h},{h}^FB{inner},1,0,{align},0^FH^FD{_zpl_escape(value)}^FS")
            y += int(h * 1.25)
        elif kind == "cols":
            if ln[1]:
                z.append(f"^FO{margin},{y}^A0N,{fh},{fh}^FB{inner},1,0,L,0^FH^FD{_zpl_escape(ln[1])}^FS")
            if ln[2]:
                z.append(f"^FO{margin},{y}^A0N,{fh},{fh}^FB{inner},1,0,R,0^FH^FD{_zpl_escape(ln[2])}^FS")
            y += lh
        elif kind == "sep":
            z.append(f"^FO{margin},{y + lh // 3}^GB{inner},{3 if ln[1] == '=' else 1},{3 if ln[1] == '=' else 1}^FS")
            y += lh
        elif kind == "barcode":
            mods = code128_modules(ln[1])
            module = max(1, min(3, inner // len(mods)))
            bx = margin + max(0, (inner - len(mods) * module) // 2)
            bh = 8 * dpmm
            z.append(f"^FO{bx},{y}^BY{module},2,{bh}^BCN,{bh},N,N,N,N^FD{_code128_zpl_data(ln[1])}^FS")
            y += bh + 4
            z.append(f"^FO{margin},{y}^A0N,{fh},{fh}^FB{inner},1,0,C,0^FH^FD{_zpl_escape(ln[1])}^FS")
            y += lh
        elif kind == "feed":
            y += lh * ln[1]
    y += margin
    return "\n".join(["^XA", "^CI28", "^MNN", "^MMT", f"^PW{pw}", f"^LL{y}", "^LH0,0"] + z + ["^PQ1", "^XZ"]) + "\n"
