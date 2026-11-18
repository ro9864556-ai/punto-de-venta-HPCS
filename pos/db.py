"""Base de datos SQLite del punto de venta."""
import os
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL UNIQUE,
    serialized INTEGER NOT NULL DEFAULT 0,
    markup REAL NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    barcode TEXT UNIQUE,
    name TEXT NOT NULL,
    brand TEXT DEFAULT '',
    model TEXT DEFAULT '',
    color TEXT DEFAULT '',
    capacity TEXT DEFAULT '',
    category_id INTEGER REFERENCES categories(id),
    cost REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    wholesale_price REAL NOT NULL DEFAULT 0,
    stock REAL NOT NULL DEFAULT 0,
    min_stock REAL NOT NULL DEFAULT 0,
    serialized INTEGER NOT NULL DEFAULT 0,
    track_stock INTEGER NOT NULL DEFAULT 1,
    warranty_days INTEGER NOT NULL DEFAULT 0,
    location TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS serials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    imei TEXT NOT NULL UNIQUE,
    imei2 TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'disponible',
    sale_id INTEGER REFERENCES sales(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folio TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    subtotal REAL NOT NULL,
    discount REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    cost_total REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL,
    paid_cash REAL NOT NULL DEFAULT 0,
    paid_card REAL NOT NULL DEFAULT 0,
    paid_transfer REAL NOT NULL DEFAULT 0,
    received REAL NOT NULL DEFAULT 0,
    change REAL NOT NULL DEFAULT 0,
    customer_name TEXT DEFAULT '',
    customer_phone TEXT DEFAULT '',
    cashier TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'completada',
    cancelled_at TEXT
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER REFERENCES products(id),
    sku TEXT,
    name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL,
    imei TEXT DEFAULT '',
    warranty_days INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventory_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty REAL NOT NULL,
    kind TEXT NOT NULL,
    reference TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cash_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_serials_product ON serials(product_id, status);
CREATE INDEX IF NOT EXISTS idx_moves_product ON inventory_moves(product_id);
"""

DEFAULT_SETTINGS = {
    "store_name": "Mi Tienda de Celulares",
    "store_legal_name": "",
    "store_rfc": "",
    "store_address": "",
    "store_phone": "",
    "store_whatsapp": "",
    "currency_symbol": "$",
    "tax_rate": "16",
    "prices_include_tax": "1",
    "show_tax_breakdown": "1",
    "cashier_name": "",
    "ticket_header": "",
    "ticket_footer": "¡Gracias por su compra!",
    "warranty_text": "Garantía sujeta a revisión. No cubre daños por humedad, golpes o mal uso. Presentar este ticket.",
    "ticket_width": "80",
    "ticket_printer_mode": "browser",
    "ticket_printer_host": "",
    "ticket_printer_port": "9100",
    "ticket_printer_name": "",
    "ticket_open_drawer": "0",
    "ticket_copies": "1",
    "label_printer_mode": "download",
    "label_printer_host": "",
    "label_printer_port": "9100",
    "label_printer_name": "",
    "label_dpi": "203",
    "label_darkness": "15",
    "label_speed": "4",
    "label_offset_x": "0",
    "label_offset_y": "0",
    "label_template": "accesorio_50x25",
    "label_show_store": "1",
    "price_rounding": "9",
    "default_markup": "100",
    "folio_prefix": "V-",
    "barcode_prefix": "20",
    "allow_negative_stock": "0",
    "ticket_zebra_width_mm": "76",
}

DEFAULT_CATEGORIES = [
    # nombre, prefijo SKU, ¿con IMEI/serie?, % de ganancia sugerido sobre costo
    ("Celulares", "CEL", 1, 25),
    ("Fundas", "FUN", 0, 150),
    ("Micas y protectores", "MIC", 0, 200),
    ("Cargadores", "CAR", 0, 100),
    ("Cables", "CAB", 0, 120),
    ("Audífonos", "AUD", 0, 100),
    ("Bocinas", "BOC", 0, 80),
    ("Memorias y USB", "MEM", 0, 70),
    ("Smartwatch y wearables", "SWT", 0, 60),
    ("Power banks", "PWB", 0, 80),
    ("Soportes y holders", "SOP", 0, 120),
    ("Refacciones", "REF", 0, 100),
    ("Chips y recargas", "CHP", 0, 20),
    ("Accesorios varios", "ACC", 0, 100),
    ("Servicios", "SRV", 0, 0),
]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def default_db_path():
    base = os.environ.get("POS_DATA_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "punto_de_venta.db")


def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        conn.executemany("INSERT INTO categories(name, prefix, serialized, markup) VALUES (?,?,?,?)", DEFAULT_CATEGORIES)
    conn.commit()
    conn.close()


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]
