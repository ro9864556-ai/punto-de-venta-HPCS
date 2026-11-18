"""Codificación de códigos de barras (Code 128 y EAN-13) sin dependencias externas.

Se usa para:
  * validar / generar códigos EAN-13 internos,
  * dibujar la vista previa SVG de las etiquetas con el mismo ancho que imprimirá la Zebra.
"""

CODE128_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]
START_B, START_C, CODE_B, CODE_C, STOP = 104, 105, 100, 99, 106

EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011",
         "0110001", "0101111", "0111011", "0110111", "0001011"]
EAN_R = ["".join("1" if b == "0" else "0" for b in code) for code in EAN_L]
EAN_G = [code[::-1] for code in EAN_R]
EAN_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
              "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def _digit_run(text, i):
    n = 0
    while i + n < len(text) and text[i + n].isdigit():
        n += 1
    return n


def code128_values(text):
    """Convierte texto a la lista de valores Code 128 (subconjuntos B y C automáticos)."""
    if not text:
        raise ValueError("Código vacío")
    for ch in text:
        if not 32 <= ord(ch) <= 126:
            raise ValueError(f"Carácter no válido para Code 128: {ch!r}")

    values = []
    i = 0
    current = None
    while i < len(text):
        run = _digit_run(text, i)
        # Subconjunto C conviene con 4+ dígitos (o todo el texto numérico par)
        use_c = run >= 4 or (run == len(text) - i and run >= 2 and run % 2 == 0 and current is None)
        if use_c:
            pairs = run - (run % 2)
            if current is None:
                values.append(START_C)
            elif current != "C":
                values.append(CODE_C)
            current = "C"
            for k in range(i, i + pairs, 2):
                values.append(int(text[k:k + 2]))
            i += pairs
        else:
            if current is None:
                values.append(START_B)
            elif current != "B":
                values.append(CODE_B)
            current = "B"
            values.append(ord(text[i]) - 32)
            i += 1

    checksum = values[0]
    for pos, val in enumerate(values[1:], start=1):
        checksum += pos * val
    values.append(checksum % 103)
    values.append(STOP)
    return values


def code128_modules(text):
    """Regresa una cadena de '1'/'0' (barra/espacio) por módulo."""
    bits = []
    for val in code128_values(text):
        bar = True
        for w in CODE128_PATTERNS[val]:
            bits.append(("1" if bar else "0") * int(w))
            bar = not bar
    return "".join(bits)


def ean13_check_digit(digits12):
    digits12 = str(digits12)
    if len(digits12) != 12 or not digits12.isdigit():
        raise ValueError("Se requieren 12 dígitos")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits12))
    return str((10 - total % 10) % 10)


def is_valid_ean13(code):
    code = str(code or "")
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == code[12]


def is_valid_upca(code):
    code = str(code or "")
    return len(code) == 12 and code.isdigit() and is_valid_ean13("0" + code)


def ean13_modules(code):
    code = str(code)
    if len(code) == 12:
        code += ean13_check_digit(code)
    if not is_valid_ean13(code):
        raise ValueError("EAN-13 inválido")
    first, left, right = int(code[0]), code[1:7], code[7:]
    bits = "101"
    for d, p in zip(left, EAN_PARITY[first]):
        bits += EAN_L[int(d)] if p == "L" else EAN_G[int(d)]
    bits += "01010"
    for d in right:
        bits += EAN_R[int(d)]
    bits += "101"
    return bits


def barcode_symbology(code):
    """'EAN13' si el código es un EAN-13/UPC válido, de lo contrario 'CODE128'."""
    if is_valid_ean13(code):
        return "EAN13"
    return "CODE128"


def barcode_modules(code):
    if barcode_symbology(code) == "EAN13":
        return ean13_modules(code)
    return code128_modules(code)


def svg_rects(modules, x, y, module_w, height):
    """Rectángulos SVG para una secuencia de módulos (agrupa barras contiguas)."""
    rects = []
    i = 0
    while i < len(modules):
        if modules[i] == "1":
            j = i
            while j < len(modules) and modules[j] == "1":
                j += 1
            rects.append(f'<rect x="{x + i * module_w:.3f}" y="{y:.3f}" '
                         f'width="{(j - i) * module_w:.3f}" height="{height:.3f}"/>')
            i = j
        else:
            i += 1
    return "".join(rects)
