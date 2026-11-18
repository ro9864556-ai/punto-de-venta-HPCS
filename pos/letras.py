"""Cantidad con letra para notas de venta (pesos mexicanos).

    importe_con_letra(259)      -> "DOSCIENTOS CINCUENTA Y NUEVE PESOS 00/100 M.N."
    importe_con_letra(1521.5)   -> "MIL QUINIENTOS VEINTIÚN PESOS 50/100 M.N."
"""

UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
            "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve",
            "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis",
            "veintisiete", "veintiocho", "veintinueve"]
DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos",
            "setecientos", "ochocientos", "novecientos"]


def _hasta_999(n):
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    c, resto = divmod(n, 100)
    partes = [CENTENAS[c]] if c else []
    if resto < 30:
        partes.append(UNIDADES[resto])
    else:
        d, u = divmod(resto, 10)
        partes.append(DECENAS[d] + (f" y {UNIDADES[u]}" if u else ""))
    return " ".join(p for p in partes if p)


def _apocope(texto):
    """'uno' → 'un' antes de 'mil', 'millones' o 'pesos' (veintiuno → veintiún)."""
    if texto.endswith("veintiuno"):
        return texto[:-9] + "veintiún"
    if texto.endswith("uno"):
        return texto[:-3] + "un"
    return texto


def numero_a_letras(n):
    n = int(n)
    if n == 0:
        return "cero"
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else f"{_apocope(numero_a_letras(millones))} millones")
    if miles:
        partes.append("mil" if miles == 1 else f"{_apocope(_hasta_999(miles))} mil")
    if unidades:
        partes.append(_hasta_999(unidades))
    return " ".join(partes)


def importe_con_letra(valor, moneda_singular="peso", moneda_plural="pesos"):
    valor = round(float(valor or 0) + 1e-9, 2)
    enteros = int(valor)
    centavos = int(round((valor - enteros) * 100))
    palabras = _apocope(numero_a_letras(enteros))
    moneda = moneda_singular if enteros == 1 else moneda_plural
    if enteros and enteros % 1_000_000 == 0:
        moneda = "de " + moneda  # "un millón de pesos"
    return f"{palabras} {moneda} {centavos:02d}/100 M.N.".upper()
