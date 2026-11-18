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
    "store_name": "Hospital para Celulares Shop",
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
    "ticket_printer_mode": "local",
    "ticket_printer_host": "",
    "ticket_printer_port": "9100",
    "ticket_printer_name": "Hospital para celulares Shop",
    "ticket_open_drawer": "0",
    "ticket_copies": "1",
    "ticket_logo": "1",
    "ticket_change_boxes": "1",
    "seller_can_charge": "0",
    "label_printer_mode": "local",
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
    ("Micas de hidrogel", "HID", 0, 300),
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
    migrate(conn)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        conn.executemany("INSERT INTO categories(name, prefix, serialized, markup) VALUES (?,?,?,?)", DEFAULT_CATEGORIES)
        conn.execute("UPDATE categories SET ask_device=1 WHERE prefix IN ('MIC', 'HID', 'FUN', 'REF', 'SRV')")
    if not conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        from werkzeug.security import generate_password_hash
        conn.execute("INSERT INTO users(username, full_name, role, password_hash, must_change, created_at) VALUES (?,?,?,?,1,?)",
                     ("admin", "Administrador", "admin", generate_password_hash("admin"), now()))
    if not conn.execute("SELECT value FROM settings WHERE key='secret_key'").fetchone():
        import secrets
        conn.execute("INSERT INTO settings(key, value) VALUES ('secret_key', ?)", (secrets.token_hex(32),))
    conn.commit()
    conn.close()


ROLES = {"admin": "Administrador", "cajero": "Cajero", "vendedor": "Vendedor"}

MIGRATIONS = [
    # tabla, columna, definición
    ("categories", "ask_device", "INTEGER NOT NULL DEFAULT 0"),
    ("products", "ask_device", "INTEGER NOT NULL DEFAULT 0"),
    ("sales", "user_id", "INTEGER"),
    ("sales", "seller_id", "INTEGER"),
    ("sales", "seller_name", "TEXT DEFAULT ''"),
    ("sales", "device_model", "TEXT DEFAULT ''"),
    ("sales", "device_imei", "TEXT DEFAULT ''"),
    ("sales", "customer_email", "TEXT DEFAULT ''"),
    ("sales", "sent_at", "TEXT"),
    ("products", "warranty_changes", "INTEGER NOT NULL DEFAULT 0"),
    ("products", "ram", "TEXT DEFAULT ''"),
    ("products", "condition", "TEXT DEFAULT ''"),
    ("sale_items", "warranty_changes", "INTEGER NOT NULL DEFAULT 0"),
]


def migrate(conn):
    """Agrega tablas/columnas nuevas a bases de datos creadas con versiones anteriores."""
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        must_change INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL)""")
    for table, column, ddl in MIGRATIONS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_device_imei ON sales(device_imei)")
    conn.execute("""CREATE TABLE IF NOT EXISTS warranty_claims (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL REFERENCES sales(id),
        sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
        number INTEGER NOT NULL,
        product_id INTEGER,
        took_stock INTEGER NOT NULL DEFAULT 0,
        forced INTEGER NOT NULL DEFAULT 0,
        user_id INTEGER,
        user_name TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_item ON warranty_claims(sale_item_id)")


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings") if r["key"] != "secret_key"}


def warranty_label(days):
    """180 → '6 meses', 365 → '1 año', 15 → '15 días'."""
    days = int(days or 0)
    if days <= 0:
        return "Sin garantía"
    if days % 365 == 0:
        n = days // 365
        return f"{n} año" + ("s" if n > 1 else "")
    if days % 30 == 0:
        n = days // 30
        return f"{n} mes" + ("es" if n > 1 else "")
    return f"{days} día" + ("s" if days > 1 else "")


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows_to_list(rows):
    return [dict(r) for r in rows]
