# Punto de Venta HPCS — Celulares y accesorios

Sistema completo de punto de venta para tienda de celulares y accesorios:
**ventas con ticket, etiquetas Zebra (ZPL), códigos de barras, SKU, generador de precios,
inventario con IMEI y corte de caja**. Funciona en la computadora de la tienda, sin internet,
desde el navegador.

## Instalación (Windows)

1. Instala **Python 3.10 o más reciente** desde <https://www.python.org/downloads/>
   (marca la casilla **“Add Python to PATH”**).
2. Descarga esta carpeta y da doble clic en **`iniciar.bat`**.
   La primera vez instala lo necesario; después abre el navegador en `http://localhost:5000`.

En Linux/macOS: `./iniciar.sh`. Manual: `pip install -r requirements.txt` y `python app.py`.

Los datos se guardan en `datos/punto_de_venta.db`. Haz respaldos desde
**Configuración → Descargar respaldo**.

> Para usarlo desde otra computadora o tablet de la red local inicia con `HOST=0.0.0.0`
> (en Windows: `set HOST=0.0.0.0` antes de `python app.py`) y abre `http://IP-de-la-PC:5000`.

## Módulos

| Módulo | Qué hace |
|---|---|
| **Vender** (F1) | Escanea código de barras, SKU o IMEI; busca por nombre; cambia precio, cantidad y descuento; descuento general; cobro en efectivo (con cambio y billetes rápidos), tarjeta, transferencia o mixto. F2 cobra, F4 enfoca el buscador. |
| **Productos** | Alta con **SKU automático** (`FUN-SAM-0001` = categoría-marca-consecutivo), **código EAN-13 interno** con dígito verificador (o el del fabricante), **generador de precio** (costo + % de ganancia + IVA + redondeo), mayoreo, garantía, existencia mínima. Importar / exportar CSV (Excel). |
| **Generador de precios masivo** | Recalcula precios por categoría con % de ganancia sobre costo, o sube/baja un % el precio actual, con vista previa antes de aplicar. Redondeos: terminación en 9, .99, .90, .50, al peso, a 5 o 10. |
| **Etiquetas Zebra** | Cola de impresión con vista previa real. Plantillas: accesorio 2"×1", chica 1.5"×1", mini 1.25"×0.75", **celular 2"×1.5" con IMEI**, anaquel 3"×2" y solo código. Impresión directa a la Zebra o descarga `.zpl`. Etiqueta libre para ofertas. |
| **Inventario e IMEI** | Entradas, salidas, conteo físico, alta de IMEIs escaneándolos (y mandarlos a etiquetas), alerta de existencia baja e historial de movimientos. |
| **Ventas y tickets** | Historial con búsqueda por folio, cliente, teléfono o IMEI; reimpresión; cancelación (regresa el inventario y libera el IMEI). Ticket en HTML, ESC/POS, ZPL o texto. |
| **Corte y reportes** | Corte de caja por día o periodo: por forma de pago, fondo/gastos de caja, efectivo esperado, utilidad, ventas por categoría y productos más vendidos. Impresión del corte. |
| **Configuración** | Datos de la tienda, RFC, leyendas, texto de garantía, IVA, impresoras, categorías con prefijo de SKU y % de ganancia. |

## Impresoras

### Etiquetas Zebra (ZPL)
En **Configuración → Etiquetas Zebra** elige:

- **Zebra en red**: IP de la impresora y puerto `9100` (ZD220/ZD420/ZD421/ZT230 con red).
- **Zebra USB**: instala el driver *ZDesigner* y escribe el nombre exacto de la impresora
  (p. ej. `ZDesigner GC420t (EPL)` o `ZDesigner ZD220-203dpi ZPL`). En Windows requiere `pywin32`
  (se instala solo con `iniciar.bat`). Usa el driver **ZPL**, no EPL.
- **Descargar archivo**: genera el `.zpl` para mandarlo con Zebra Setup Utilities.

Configura la **resolución** (203 o 300 dpi), oscuridad, velocidad y desplazamiento si la impresión
sale corrida. Usa **Etiqueta de prueba** para verificar.

### Tickets
- **Navegador**: funciona con cualquier impresora instalada (selecciónala en el diálogo de impresión,
  papel 80 mm o 58 mm, márgenes “ninguno”).
- **Térmica en red / USB (ESC/POS)**: impresión directa sin diálogo, con corte de papel y apertura de
  cajón de dinero opcional (Epson TM-T20, 3nStar, EC Line, Xprinter, etc.).
- **Zebra (ZPL)**: imprime el ticket en la Zebra (útil con rollo continuo).

## Formato CSV para importar

Columnas: `sku, barcode, name, brand, model, color, capacity, category, cost, price,
wholesale_price, stock, min_stock, serialized, track_stock, warranty_days, location, notes`.
Solo `name` es obligatorio. Si `sku` o `barcode` ya existen, el producto se actualiza.
Descarga la plantilla desde **Productos → Importar CSV**.

## Desarrollo

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Estructura:

```
app.py            servidor Flask y API REST
pos/barcodes.py   Code 128 y EAN-13 (sin dependencias)
pos/labels.py     plantillas de etiquetas → ZPL y vista previa SVG
pos/tickets.py    ticket de venta / corte → ESC/POS, HTML, ZPL, texto
pos/pricing.py    generador de precios, SKU y códigos internos
pos/printing.py   envío a impresoras (red 9100, Windows RAW, CUPS)
pos/db.py         esquema SQLite y configuración por defecto
templates/, static/  interfaz web
```
