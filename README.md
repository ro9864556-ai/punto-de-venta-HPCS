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

## Usuarios

Primer inicio: usuario **admin**, contraseña **admin** (el sistema pide cambiarla).
Crea a tu equipo en **Configuración → Usuarios**:

| Rol | Puede |
|---|---|
| **Administración** | Todo, en todas las sucursales: inventarios, ventas, precios, configuración, usuarios, cancelar ventas, respaldos. |
| **Matriz (supervisor)** | Revisa todas las sucursales: da de alta productos y sube inventario a cualquiera (entradas, IMEI, traspasos, etiquetas), ve ventas, cortes y garantías de todas. No configura el sistema, no administra usuarios, no cancela ventas ni hace cambios masivos de precio. |
| **Cajero** | En su sucursal: cobra las notas de los vendedores, hace notas, etiquetas, inventario e IMEI, cambios por garantía, corte de caja. |
| **Vendedor** | En su sucursal: arma la venta y la envía a caja, consulta garantías. No ve costos, no cambia precios (sí puede dar descuento) y no cancela. |

## Varias sucursales en red

La instalación nueva ya trae la estructura de la tienda:

| Sucursal | Clave de folio | Quién trabaja ahí |
|---|---|---|
| **Matriz** | — (bodega, no vende) | Encargado de matriz: recibe la mercancía, la etiqueta y surte a las sucursales. Es la computadora **servidor**. |
| **J. Jesús Reynoso** | `JR-000001` | Cajeros y vendedores de esa sucursal. |
| **González Gallo** | `GG-000001` | Cajeros y vendedores de esa sucursal. |

**Administración** no es una sucursal: es el usuario administrador con sucursal “Todas”, que ve y controla
todo. Nombres, claves y direcciones se cambian en **Configuración → Sucursales**.

La computadora de la **Matriz es el servidor**: siempre encendida y guarda toda la información. Administración
y las sucursales entran desde el navegador. La Matriz no vende al público (casilla “Vende al público” en
Configuración → Sucursales); el encargado de matriz entra directo a Inventario y no ve la pantalla de Vender.
Las sucursales y la computadora de administración entran desde el navegador. Todas ven los mismos
productos y precios; cada sucursal tiene **su propia existencia, sus IMEI, sus folios** (`JR-000123`,
`GG-000124`), **su caja y sus impresoras**. Administración y Matriz pueden trabajar en cualquier sucursal
(selector 📍 en el menú) y ver reportes de una o de **todas las sucursales**. Los cajeros y vendedores
solo ven la suya. Entre sucursales se hacen **traspasos** (Inventario → movimiento “Traspaso”).

### Paso 1 · Red privada con Tailscale (gratis)
Así las computadoras se ven entre sí por internet de forma cifrada, sin abrir puertos ni contratar IP fija.
1. En **cada** computadora (servidor, sucursales y administración) instala Tailscale desde
   <https://tailscale.com/download> e inicia sesión con **la misma cuenta** (la de la tienda).
2. En la computadora de la **Matriz** abre **`iniciar_servidor_red.bat`** (ponlo en Inicio de Windows para que arranque solo). La ventana muestra la dirección,
   p. ej. `http://100.101.102.103:5000  (Tailscale)`. Si Windows pregunta por el firewall, da **Permitir**.
3. En las demás computadoras abre esa dirección en el navegador (crea un acceso directo en el escritorio).

> La computadora servidor debe estar encendida mientras las sucursales trabajan (desactiva la
> suspensión en Opciones de energía). Si una sucursal pierde internet, no podrá vender hasta que regrese.

### Paso 2 · Dar de alta las sucursales
Como administrador: **Configuración → Sucursales** → nombre, clave del folio (p. ej. `JR`), dirección y
teléfono (salen en el ticket de esa sucursal). En **Usuarios** asigna la sucursal de cada cajero y vendedor.
Para mover mercancía: **Inventario** → selecciona el producto → “Traspaso a otra sucursal”
(los celulares se traspasan escaneando su IMEI).

### Paso 3 · Impresoras de cada sucursal (agente de impresión)
El servidor no puede llegar a las impresoras USB de otra sucursal; por eso en cada sucursal corre un
programa pequeño, el **agente**, que recibe los tickets y etiquetas y los manda a sus impresoras.
1. Copia la carpeta del programa a la computadora de la sucursal (con Python instalado).
2. En el sistema: **Configuración → Sucursales → Descargar agente.json** de esa sucursal y guárdalo
   en la carpeta del programa. Revisa ahí el nombre de la impresora de tickets y de la Zebra
   (como aparecen en Windows).
3. Abre **`iniciar_agente.bat`** y déjalo abierto (puedes ponerlo en Inicio de Windows). Debe decir
   “Conectado al servidor”.
4. En el sistema, como administrador, cambia a esa sucursal (📍) y en **Configuración → Tickets** y
   **Etiquetas Zebra** elige “Agente de impresión de la sucursal”. En Configuración → Sucursales verás
   el agente como **Conectado**.

La Matriz (servidor) imprime las etiquetas en su Zebra USB directamente (“USB instalada en este equipo”),
así que **no necesita agente**. J. Jesús Reynoso y González Gallo ya vienen configuradas para imprimir por
agente; solo falta instalar el agente en su computadora. Administración no necesita agente.

## Logo

El logo de **Hospital para Celulares Shop** aparece en el inicio de sesión, el menú y arriba de cada
nota y corte de caja. En la impresora térmica y en la Zebra se imprime en blanco y negro (vista previa
en **Configuración → Tienda → Logo**). Desde ahí se puede subir otro logo o desactivar su impresión.

## Flujo de venta: vendedor → caja

1. El **vendedor** escanea los productos, captura cliente y teléfono (y el modelo e IMEI del equipo si la venta lleva garantía) y presiona
   **Enviar a caja (F2)**. La nota queda *pendiente de cobro* (no cuenta en el corte ni descuenta inventario).
2. El **cajero** ve el aviso **Notas por cobrar** (con contador en el menú), da clic en **Cobrar**, puede
   ajustar la nota y cobra con F2. Se imprime la nota con el nombre del vendedor y de quien cobró.
3. El cajero también puede hacer notas y cobrarlas directamente. Si quieres que los vendedores también
   cobren, actívalo en **Configuración → Usuarios**.

## Garantías y cambios (F3)

Cada producto define su **garantía** (p. ej. 1 año) y cuántos **cambios** incluye (p. ej. 3 para una mica
de cristal). En la nota se imprime “Incluye 3 cambios” y un recuadro **Control de cambios** con renglones
de fecha y firma como respaldo en papel.

Cuando el cliente regresa: **Garantías** → escanea el código del ticket o escribe el IMEI (*#06#) o el
teléfono. El sistema muestra si la garantía sigue vigente, cuántos cambios lleva (● ● ○) y el historial.
**Registrar cambio** descuenta la mica del inventario e imprime un comprobante “Cambio 2 de 3 · Cambios
restantes: 1” con firma del cliente. Sin cambios disponibles o con la garantía vencida solo un
administrador puede autorizar un cambio extra.

## Nota de venta

Cada nota lleva: fecha, vendedor, cliente, teléfono, los artículos con su precio y
garantía (con fecha de vencimiento), el **modelo y el IMEI del equipo del cliente** cuando la venta lleva
garantía, y el total. Si ningún artículo tiene garantía, esa sección no aparece.
Los productos marcados con “Pedir modelo e IMEI del equipo del cliente” (micas, fundas, reparaciones)
avisan si falta capturarlos. En **Ventas** se busca una garantía por IMEI, teléfono, nombre o folio en
todas las fechas.

Para cargar todos los tipos de micas usa **Productos → Alta rápida (varios)** → *Sugerir tipos de micas*,
pon el precio y la garantía y guarda.

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

### Configuración de esta tienda (Windows)
Ya viene preconfigurado así (cámbialo en **Configuración** si hace falta):

- **Etiquetas**: Zebra por **USB**. En *Configuración → Etiquetas Zebra* selecciona en “Nombre de la
  Zebra USB” la impresora tal como aparece en *Panel de control → Dispositivos e impresoras*.
- **Tickets**: térmica genérica USB llamada **`Hospital para celulares Shop`**, papel de 80 mm, comandos
  ESC/POS. Si tu rollo es de 58 mm cámbialo en *Configuración → Tickets*. Imprime el **Ticket de prueba**:
  si los acentos salen mal o la impresora no responde, elige “Navegador” como modo de impresión.

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
