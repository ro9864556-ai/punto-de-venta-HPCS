"""Punto de venta para tienda de celulares y accesorios.

Ejecutar:  python app.py      → abre http://localhost:5000
"""
import csv
import io
import os
import re
import sys
import threading
import webbrowser
from datetime import date, datetime, timedelta

from flask import Flask, Response, g, jsonify, redirect, render_template, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

from pos import db as dbm
from pos import labels, printing, tickets
from pos.barcodes import is_valid_ean13
from pos.pricing import ROUNDING_MODES, generate_internal_barcode, generate_sku, suggest_price

BASE_DIR = os.path.dirname(os.path.abspath(getattr(sys, "_MEIPASS", __file__)))


def create_app(db_path=None):
    app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"),
                static_folder=os.path.join(BASE_DIR, "static"))
    app.config["DB_PATH"] = db_path or dbm.default_db_path()
    app.config["JSON_SORT_KEYS"] = False
    app.json.ensure_ascii = False
    dbm.init_db(app.config["DB_PATH"])
    _c = dbm.connect(app.config["DB_PATH"])
    app.secret_key = _c.execute("SELECT value FROM settings WHERE key='secret_key'").fetchone()[0]
    _c.close()
    app.permanent_session_lifetime = timedelta(hours=14)

    # ------------------------------------------------------------ utilidades
    def conn():
        if "db" not in g:
            g.db = dbm.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    class ApiError(Exception):
        def __init__(self, message, status=400):
            super().__init__(message)
            self.status = status

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify({"error": str(err)}), err.status

    @app.errorhandler(printing.PrintError)
    def handle_print_error(err):
        return jsonify({"error": str(err)}), 502

    def settings():
        return dbm.get_settings(conn())

    def body():
        return request.get_json(silent=True) or {}

    def num(value, default=0.0):
        try:
            if value in (None, ""):
                return default
            return float(str(value).replace(",", "").replace("$", ""))
        except (TypeError, ValueError):
            raise ApiError(f"Valor numérico inválido: {value}")

    def r2(value):
        return round(float(value) + 1e-9, 2)

    def date_range():
        today = date.today().isoformat()
        d_from = request.args.get("from") or today
        d_to = request.args.get("to") or d_from
        return d_from, d_to

    def get_product(pid):
        row = conn().execute(
            "SELECT p.*, c.name AS category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=?",
            (pid,)).fetchone()
        if not row:
            raise ApiError("Producto no encontrado", 404)
        return dict(row)

    def sync_serial_stock(c, product_id):
        n = c.execute("SELECT COUNT(*) FROM serials WHERE product_id=? AND status='disponible'", (product_id,)).fetchone()[0]
        c.execute("UPDATE products SET stock=?, updated_at=? WHERE id=?", (n, dbm.now(), product_id))

    # ------------------------------------------------------------ usuarios y permisos
    # Lo que no aparece aquí lo puede usar cualquier usuario con sesión iniciada.
    ADMIN_ONLY = {
        "api_put_settings", "api_printers", "api_print_test", "api_category_create", "api_category_update",
        "api_category_delete", "api_product_create", "api_product_update", "api_product_delete", "api_products_bulk_create",
        "api_next_sku", "api_new_barcode", "api_pricing_suggest", "api_pricing_bulk", "api_delete_serial",
        "api_cancel_sale", "api_export_csv", "api_import_csv", "api_csv_template", "api_backup",
        "api_users", "api_user_create", "api_user_update",
    }
    STAFF_ONLY = {  # administrador y cajero
        "api_add_serials", "api_inventory_adjust", "api_inventory_moves", "api_cash_create", "api_cash_list",
        "api_report", "corte_page", "api_corte_print", "api_dashboard", "api_label_preview", "api_label_zpl",
    }
    PUBLIC = {"login_page", "api_login", "static"}

    def current_user():
        if "user" not in g:
            g.user = None
            uid = session.get("uid")
            if uid:
                row = conn().execute("SELECT id, username, full_name, role, must_change, active FROM users WHERE id=?",
                                     (uid,)).fetchone()
                if row and row["active"]:
                    g.user = dict(row)
        return g.user

    def is_vendedor():
        u = current_user()
        return bool(u and u["role"] == "vendedor")

    @app.before_request
    def check_access():
        if request.endpoint in PUBLIC or request.endpoint is None:
            return None
        user = current_user()
        wants_json = request.path.startswith("/api/")
        if not user:
            if wants_json:
                return jsonify({"error": "Inicia sesión"}), 401
            return redirect("/login")
        role = user["role"]
        if (request.endpoint in ADMIN_ONLY and role != "admin") or \
           (request.endpoint in STAFF_ONLY and role not in ("admin", "cajero")):
            msg = f"Tu usuario ({dbm.ROLES.get(role, role)}) no tiene permiso para esta acción."
            return (jsonify({"error": msg}), 403) if wants_json else (msg, 403)
        return None

    def strip_costs(obj):
        """Los vendedores no ven costos ni utilidades."""
        if is_vendedor():
            items = obj if isinstance(obj, list) else [obj]
            for it in items:
                for k in ("cost", "cost_total", "unit_cost"):
                    it.pop(k, None)
                for sub in it.get("items", []) or []:
                    sub.pop("unit_cost", None)
        return obj

    @app.get("/login")
    def login_page():
        users = conn().execute("SELECT username, must_change FROM users").fetchall()
        first = len(users) == 1 and users[0]["username"] == "admin" and users[0]["must_change"] == 1
        return render_template("login.html", store=settings().get("store_name", ""), first_run=first)

    @app.post("/api/login")
    def api_login():
        d = body()
        row = conn().execute("SELECT * FROM users WHERE username=? AND active=1", ((d.get("username") or "").strip(),)).fetchone()
        if not row or not check_password_hash(row["password_hash"], d.get("password") or ""):
            raise ApiError("Usuario o contraseña incorrectos", 401)
        session.clear()
        session.permanent = True
        session["uid"] = row["id"]
        return jsonify({"ok": True})

    @app.post("/api/logout")
    def api_logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/me")
    def api_me():
        u = dict(current_user())
        u["role_name"] = dbm.ROLES.get(u["role"], u["role"])
        return jsonify(u)

    @app.post("/api/me/password")
    def api_change_password():
        d = body()
        u = current_user()
        row = conn().execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()
        if not check_password_hash(row["password_hash"], d.get("current") or ""):
            raise ApiError("La contraseña actual no es correcta")
        new = d.get("new") or ""
        if len(new) < 4:
            raise ApiError("La contraseña nueva debe tener al menos 4 caracteres")
        conn().execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?", (generate_password_hash(new), u["id"]))
        conn().commit()
        return jsonify({"ok": True})

    @app.get("/api/sellers")
    def api_sellers():
        rows = conn().execute("SELECT id, full_name, role FROM users WHERE active=1 ORDER BY full_name").fetchall()
        return jsonify(dbm.rows_to_list(rows))

    @app.get("/api/device-models")
    def api_device_models():
        """Modelos de equipos capturados antes, para autocompletar."""
        rows = conn().execute("""SELECT device_model, COUNT(*) n FROM sales WHERE device_model<>'' GROUP BY device_model
                                 ORDER BY n DESC LIMIT 300""").fetchall()
        known = [r["device_model"] for r in rows]
        base = ["iPhone 17 Pro Max", "iPhone 17 Pro", "iPhone 17", "iPhone Air", "iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 16",
                "iPhone 15 Pro Max", "iPhone 15", "iPhone 14", "iPhone 13", "iPhone 12", "iPhone 11", "Samsung Galaxy S25 Ultra",
                "Samsung Galaxy S24", "Samsung Galaxy A56", "Samsung Galaxy A36", "Samsung Galaxy A16", "Samsung Galaxy A15",
                "Xiaomi Redmi Note 14", "Xiaomi Redmi 14C", "Motorola Moto G85", "Motorola Moto G35", "Motorola Moto E15"]
        return jsonify(known + [m for m in base if m not in known])

    @app.get("/api/users")
    def api_users():
        rows = conn().execute("SELECT id, username, full_name, role, active, must_change, created_at FROM users ORDER BY role, full_name").fetchall()
        return jsonify({"users": dbm.rows_to_list(rows), "roles": dbm.ROLES})

    def _user_values(d, require_password):
        username = re.sub(r"\s", "", d.get("username") or "").lower()
        full_name = (d.get("full_name") or "").strip()
        role = d.get("role")
        if not username or not full_name:
            raise ApiError("Usuario y nombre son obligatorios")
        if role not in dbm.ROLES:
            raise ApiError("Rol inválido")
        pwd = d.get("password") or ""
        if (require_password or pwd) and len(pwd) < 4:
            raise ApiError("La contraseña debe tener al menos 4 caracteres")
        return username, full_name, role, pwd

    def _check_last_admin(uid, role, active):
        if role == "admin" and active:
            return
        others = conn().execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0]
        if not others:
            raise ApiError("Debe quedar al menos un administrador activo")

    @app.post("/api/users")
    def api_user_create():
        username, full_name, role, pwd = _user_values(body(), True)
        try:
            cur = conn().execute("INSERT INTO users(username, full_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                                 (username, full_name, role, generate_password_hash(pwd), dbm.now()))
            conn().commit()
        except Exception:
            raise ApiError(f"El usuario '{username}' ya existe")
        return jsonify({"id": cur.lastrowid}), 201

    @app.put("/api/users/<int:uid>")
    def api_user_update(uid):
        d = body()
        username, full_name, role, pwd = _user_values(d, False)
        active = 0 if d.get("active") in (0, False, "0") else 1
        _check_last_admin(uid, role, active)
        c = conn()
        try:
            c.execute("UPDATE users SET username=?, full_name=?, role=?, active=? WHERE id=?", (username, full_name, role, active, uid))
        except Exception:
            raise ApiError(f"El usuario '{username}' ya existe")
        if pwd:
            c.execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?", (generate_password_hash(pwd), uid))
        c.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ páginas
    @app.route("/")
    def index():
        return render_template("index.html")

    # ------------------------------------------------------------ configuración
    @app.get("/api/settings")
    def api_get_settings():
        return jsonify({"settings": settings(), "rounding_modes": ROUNDING_MODES,
                        "label_templates": {k: {"name": v["name"], "description": v["description"],
                                                "size": v["size"]} for k, v in labels.TEMPLATES.items()}})

    @app.put("/api/settings")
    def api_put_settings():
        data = body()
        c = conn()
        for key, value in data.items():
            if key in dbm.DEFAULT_SETTINGS or key in ("ticket_zebra_width_mm", "allow_negative_stock"):
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(value)))
        c.commit()
        return jsonify({"settings": settings()})

    @app.get("/api/printers")
    def api_printers():
        return jsonify({"printers": printing.list_printers()})

    @app.post("/api/print/test")
    def api_print_test():
        target = body().get("target", "label")
        s = settings()
        if target == "label":
            zpl = labels.test_label_zpl(s)
            if s.get("label_printer_mode") == "download":
                return jsonify({"zpl": zpl, "message": "Modo descarga: se generó el archivo ZPL."})
            printing.send(zpl, s["label_printer_mode"], s.get("label_printer_host"), s.get("label_printer_port"),
                          s.get("label_printer_name"))
            return jsonify({"message": "Etiqueta de prueba enviada."})
        t = tickets.build_test_ticket(s)
        return _dispatch_ticket(t, s, "Prueba")

    # ------------------------------------------------------------ categorías
    @app.get("/api/categories")
    def api_categories():
        rows = conn().execute("""SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id AND p.active=1) AS products
                                 FROM categories c ORDER BY c.name""").fetchall()
        return jsonify(dbm.rows_to_list(rows))

    @app.post("/api/categories")
    def api_category_create():
        d = body()
        name = (d.get("name") or "").strip()
        prefix = re.sub(r"[^A-Z0-9]", "", (d.get("prefix") or name[:3]).upper())[:5]
        if not name or not prefix:
            raise ApiError("Nombre y prefijo son obligatorios")
        try:
            c = conn()
            cur = c.execute("INSERT INTO categories(name, prefix, serialized, markup, ask_device) VALUES (?,?,?,?,?)",
                            (name, prefix, 1 if d.get("serialized") else 0, num(d.get("markup"), 100), 1 if d.get("ask_device") else 0))
            c.commit()
        except Exception as exc:  # sqlite3.IntegrityError
            raise ApiError(f"La categoría o el prefijo ya existe ({exc})")
        return jsonify({"id": cur.lastrowid})

    @app.put("/api/categories/<int:cid>")
    def api_category_update(cid):
        d = body()
        c = conn()
        try:
            c.execute("UPDATE categories SET name=?, prefix=?, serialized=?, markup=?, ask_device=? WHERE id=?",
                      (d.get("name", "").strip(), re.sub(r"[^A-Z0-9]", "", d.get("prefix", "").upper())[:5],
                       1 if d.get("serialized") else 0, num(d.get("markup"), 100), 1 if d.get("ask_device") else 0, cid))
            c.commit()
        except Exception as exc:
            raise ApiError(f"No se pudo guardar: {exc}")
        return jsonify({"ok": True})

    @app.delete("/api/categories/<int:cid>")
    def api_category_delete(cid):
        c = conn()
        if c.execute("SELECT COUNT(*) FROM products WHERE category_id=?", (cid,)).fetchone()[0]:
            raise ApiError("La categoría tiene productos; muévelos antes de borrarla.")
        c.execute("DELETE FROM categories WHERE id=?", (cid,))
        c.commit()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ productos
    PRODUCT_FIELDS = ["sku", "barcode", "name", "brand", "model", "color", "capacity", "category_id", "cost", "price",
                      "wholesale_price", "min_stock", "serialized", "track_stock", "warranty_days", "location", "notes",
                      "ask_device"]

    @app.get("/api/products")
    def api_products():
        q = (request.args.get("q") or "").strip()
        sql = ["""SELECT p.*, c.name AS category_name FROM products p
                  LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1"""]
        params = []
        if request.args.get("inactive") != "1":
            sql.append("AND p.active=1")
        if request.args.get("category"):
            sql.append("AND p.category_id=?")
            params.append(request.args["category"])
        if request.args.get("low") == "1":
            sql.append("AND p.track_stock=1 AND p.stock<=p.min_stock")
        if q:
            for word in q.split():
                like = f"%{word}%"
                sql.append("AND (p.name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ? OR p.brand LIKE ? OR p.model LIKE ? "
                           "OR p.color LIKE ? OR p.id IN (SELECT product_id FROM serials WHERE imei LIKE ?))")
                params += [like] * 7
        sql.append("ORDER BY p.name LIMIT ?")
        params.append(int(request.args.get("limit", 500)))
        return jsonify(strip_costs(dbm.rows_to_list(conn().execute(" ".join(sql), params).fetchall())))

    @app.get("/api/products/<int:pid>")
    def api_product(pid):
        p = get_product(pid)
        p["serials"] = dbm.rows_to_list(conn().execute(
            "SELECT s.*, sa.folio FROM serials s LEFT JOIN sales sa ON sa.id=s.sale_id WHERE s.product_id=? ORDER BY s.status, s.id DESC",
            (pid,)).fetchall())
        return jsonify(strip_costs(p))

    @app.get("/api/products/next-sku")
    def api_next_sku():
        return jsonify({"sku": generate_sku(conn(), request.args.get("category_id") or None, request.args.get("brand", ""))})

    @app.get("/api/products/new-barcode")
    def api_new_barcode():
        c = conn()
        code = generate_internal_barcode(c, settings().get("barcode_prefix", "20"))
        c.commit()
        return jsonify({"barcode": code})

    def _product_values(d, c, existing=None):
        vals = {}
        for f in PRODUCT_FIELDS:
            if f in d:
                vals[f] = d[f]
            elif existing is not None:
                vals[f] = existing[f]
        vals["name"] = (vals.get("name") or "").strip()
        if not vals["name"]:
            raise ApiError("El nombre del producto es obligatorio")
        for f in ("cost", "price", "wholesale_price", "min_stock"):
            vals[f] = num(vals.get(f), 0)
        vals["warranty_days"] = int(num(vals.get("warranty_days"), 0))
        vals["serialized"] = 1 if vals.get("serialized") in (1, True, "1", "true", "on") else 0
        vals["track_stock"] = 0 if vals.get("track_stock") in (0, False, "0", "false") else 1
        vals["ask_device"] = 1 if vals.get("ask_device") in (1, True, "1", "true", "on") else 0
        if vals["serialized"]:
            vals["track_stock"] = 1
        vals["category_id"] = int(vals["category_id"]) if vals.get("category_id") not in (None, "", 0, "0") else None
        for f in ("brand", "model", "color", "capacity", "location", "notes"):
            vals[f] = (vals.get(f) or "").strip()
        vals["sku"] = (vals.get("sku") or "").strip().upper() or generate_sku(c, vals["category_id"], vals["brand"])
        barcode = re.sub(r"\s", "", str(vals.get("barcode") or ""))
        if not barcode:
            barcode = generate_internal_barcode(c, settings().get("barcode_prefix", "20"))
        vals["barcode"] = barcode
        return vals

    def _check_unique(c, vals, pid=None):
        for f, label in (("sku", "SKU"), ("barcode", "código de barras")):
            row = c.execute(f"SELECT id, name FROM products WHERE {f}=? AND id<>?", (vals[f], pid or 0)).fetchone()
            if row:
                raise ApiError(f"El {label} {vals[f]} ya lo usa: {row['name']}")

    @app.post("/api/products")
    def api_product_create():
        d = body()
        c = conn()
        vals = _product_values(d, c)
        _check_unique(c, vals)
        ts = dbm.now()
        cols = list(vals.keys())
        cur = c.execute(f"INSERT INTO products({', '.join(cols)}, stock, created_at, updated_at) "
                        f"VALUES ({', '.join('?' * len(cols))}, 0, ?, ?)", [vals[k] for k in cols] + [ts, ts])
        pid = cur.lastrowid
        initial = num(d.get("initial_stock"), 0)
        if initial and not vals["serialized"]:
            c.execute("UPDATE products SET stock=? WHERE id=?", (initial, pid))
            c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                      (pid, initial, "entrada", "Inventario inicial", ts))
        imeis = _parse_imeis(d.get("imeis"))
        if imeis and vals["serialized"]:
            _add_serials(c, pid, imeis, "Alta de producto")
        c.commit()
        return jsonify(get_product(pid)), 201

    @app.post("/api/products/bulk")
    def api_products_bulk_create():
        """Alta rápida de varios productos (p. ej. todos los tipos de micas)."""
        rows = body().get("rows") or []
        c = conn()
        created, errors = [], []
        ts = dbm.now()
        for n, row in enumerate(rows, start=1):
            if not (row.get("name") or "").strip():
                continue
            try:
                vals = _product_values(row, c)
                _check_unique(c, vals)
                cols = list(vals.keys())
                pid = c.execute(f"INSERT INTO products({', '.join(cols)}, stock, created_at, updated_at) "
                                f"VALUES ({', '.join('?' * len(cols))}, 0, ?, ?)", [vals[k] for k in cols] + [ts, ts]).lastrowid
                initial = num(row.get("initial_stock"), 0)
                if initial and vals["track_stock"] and not vals["serialized"]:
                    c.execute("UPDATE products SET stock=? WHERE id=?", (initial, pid))
                    c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                              (pid, initial, "entrada", "Inventario inicial", ts))
                created.append({"id": pid, "sku": vals["sku"], "name": vals["name"]})
            except ApiError as exc:
                errors.append(f"Renglón {n} ({row.get('name')}): {exc}")
        c.commit()
        return jsonify({"created": created, "errors": errors})

    @app.put("/api/products/<int:pid>")
    def api_product_update(pid):
        existing = get_product(pid)
        c = conn()
        vals = _product_values(body(), c, existing)
        _check_unique(c, vals, pid)
        sets = ", ".join(f"{k}=?" for k in vals)
        c.execute(f"UPDATE products SET {sets}, active=1, updated_at=? WHERE id=?", list(vals.values()) + [dbm.now(), pid])
        if vals["serialized"]:
            sync_serial_stock(c, pid)
        c.commit()
        return jsonify(get_product(pid))

    @app.delete("/api/products/<int:pid>")
    def api_product_delete(pid):
        get_product(pid)
        c = conn()
        used = c.execute("SELECT COUNT(*) FROM sale_items WHERE product_id=?", (pid,)).fetchone()[0]
        if used or c.execute("SELECT COUNT(*) FROM serials WHERE product_id=?", (pid,)).fetchone()[0]:
            c.execute("UPDATE products SET active=0, updated_at=? WHERE id=?", (dbm.now(), pid))
            msg = "Producto desactivado (tiene historial de ventas/IMEI)."
        else:
            c.execute("DELETE FROM inventory_moves WHERE product_id=?", (pid,))
            c.execute("DELETE FROM products WHERE id=?", (pid,))
            msg = "Producto eliminado."
        c.commit()
        return jsonify({"message": msg})

    @app.get("/api/lookup")
    def api_lookup():
        """Busca por código de barras, SKU o IMEI (lo que manda el lector)."""
        code = (request.args.get("code") or "").strip()
        if not code:
            raise ApiError("Código vacío")
        c = conn()
        row = c.execute("SELECT id FROM products WHERE active=1 AND (barcode=? OR UPPER(sku)=UPPER(?))", (code, code)).fetchone()
        if row:
            return jsonify({"product": strip_costs(get_product(row["id"])), "imei": None})
        if len(code) == 12 and code.isdigit():  # UPC leído como EAN con 0 inicial o viceversa
            row = c.execute("SELECT id FROM products WHERE active=1 AND barcode IN (?, ?)", ("0" + code, code.lstrip("0"))).fetchone()
            if row:
                return jsonify({"product": strip_costs(get_product(row["id"])), "imei": None})
        serial = c.execute("SELECT * FROM serials WHERE imei=? OR imei2=?", (code, code)).fetchone()
        if serial:
            if serial["status"] != "disponible":
                raise ApiError(f"El IMEI {code} ya fue vendido.", 409)
            return jsonify({"product": strip_costs(get_product(serial["product_id"])), "imei": serial["imei"]})
        raise ApiError(f"No se encontró ningún producto con el código {code}", 404)

    # ------------------------------------------------------------ precios
    @app.post("/api/pricing/suggest")
    def api_pricing_suggest():
        d = body()
        s = settings()
        return jsonify(suggest_price(num(d.get("cost")), num(d.get("markup"), num(s.get("default_markup"), 100)),
                                     num(s.get("tax_rate"), 16), d.get("cost_includes_tax", True) not in (False, "0", 0),
                                     s.get("prices_include_tax", "1") == "1",
                                     d.get("rounding") or s.get("price_rounding", "9")))

    @app.post("/api/pricing/bulk")
    def api_pricing_bulk():
        """Recalcula precios de una categoría (o todas) con un % de ganancia. apply=false solo muestra."""
        d = body()
        s = settings()
        c = conn()
        sql = "SELECT id, sku, name, cost, price FROM products WHERE active=1 AND cost>0"
        params = []
        if d.get("category_id"):
            sql += " AND category_id=?"
            params.append(d["category_id"])
        if d.get("q"):
            sql += " AND (name LIKE ? OR brand LIKE ? OR sku LIKE ?)"
            params += [f"%{d['q']}%"] * 3
        mode = d.get("mode", "markup")
        rows = []
        for p in c.execute(sql + " ORDER BY name", params).fetchall():
            if mode == "percent_change":
                from pos.pricing import round_price
                new = round_price(p["price"] * (1 + num(d.get("value")) / 100), d.get("rounding") or s.get("price_rounding", "9"))
            else:
                new = suggest_price(p["cost"], num(d.get("value"), 100), num(s.get("tax_rate"), 16),
                                    d.get("cost_includes_tax", True) not in (False, "0", 0),
                                    s.get("prices_include_tax", "1") == "1",
                                    d.get("rounding") or s.get("price_rounding", "9"))["price"]
            rows.append({"id": p["id"], "sku": p["sku"], "name": p["name"], "cost": p["cost"], "old_price": p["price"], "new_price": new})
        if d.get("apply"):
            ts = dbm.now()
            for r in rows:
                c.execute("UPDATE products SET price=?, updated_at=? WHERE id=?", (r["new_price"], ts, r["id"]))
            c.commit()
        return jsonify({"rows": rows, "applied": bool(d.get("apply"))})

    # ------------------------------------------------------------ IMEI / series e inventario
    def _parse_imeis(value):
        if not value:
            return []
        if isinstance(value, str):
            value = re.split(r"[\s,;]+", value)
        out = []
        for v in value:
            v = str(v).strip()
            if v and v not in out:
                out.append(v)
        return out

    def _add_serials(c, pid, imeis, notes=""):
        ts = dbm.now()
        added, skipped = [], []
        for imei in imeis:
            if c.execute("SELECT 1 FROM serials WHERE imei=? OR imei2=?", (imei, imei)).fetchone():
                skipped.append(imei)
                continue
            c.execute("INSERT INTO serials(product_id, imei, status, created_at) VALUES (?,?,?,?)", (pid, imei, "disponible", ts))
            added.append(imei)
        if added:
            c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                      (pid, len(added), "entrada", (notes + " IMEI: " + ", ".join(added))[:900], ts))
        sync_serial_stock(c, pid)
        return added, skipped

    @app.post("/api/products/<int:pid>/serials")
    def api_add_serials(pid):
        p = get_product(pid)
        if not p["serialized"]:
            raise ApiError("Este producto no maneja IMEI / número de serie")
        imeis = _parse_imeis(body().get("imeis"))
        if not imeis:
            raise ApiError("Captura al menos un IMEI")
        c = conn()
        added, skipped = _add_serials(c, pid, imeis, body().get("notes", ""))
        c.commit()
        return jsonify({"added": added, "skipped": skipped, "stock": get_product(pid)["stock"]})

    @app.delete("/api/serials/<int:sid>")
    def api_delete_serial(sid):
        c = conn()
        row = c.execute("SELECT * FROM serials WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ApiError("IMEI no encontrado", 404)
        if row["status"] != "disponible":
            raise ApiError("No se puede borrar un IMEI vendido")
        c.execute("DELETE FROM serials WHERE id=?", (sid,))
        c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                  (row["product_id"], -1, "salida", f"Baja de IMEI {row['imei']}", dbm.now()))
        sync_serial_stock(c, row["product_id"])
        c.commit()
        return jsonify({"ok": True})

    @app.post("/api/inventory/adjust")
    def api_inventory_adjust():
        d = body()
        p = get_product(int(d.get("product_id") or 0))
        if p["serialized"]:
            raise ApiError("Los productos con IMEI se ajustan dando de alta o baja cada IMEI")
        kind = d.get("kind", "entrada")
        qty = num(d.get("qty"))
        if kind == "entrada":
            delta = abs(qty)
        elif kind == "salida":
            delta = -abs(qty)
        elif kind == "conteo":
            delta = qty - float(p["stock"])
        else:
            raise ApiError("Tipo de movimiento inválido")
        c = conn()
        ts = dbm.now()
        c.execute("UPDATE products SET stock=stock+?, updated_at=? WHERE id=?", (delta, ts, p["id"]))
        if d.get("cost") not in (None, "") and kind == "entrada":
            c.execute("UPDATE products SET cost=? WHERE id=?", (num(d.get("cost")), p["id"]))
        c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                  (p["id"], delta, kind, d.get("notes", ""), ts))
        c.commit()
        return jsonify(get_product(p["id"]))

    @app.get("/api/inventory/moves")
    def api_inventory_moves():
        sql = """SELECT m.*, p.name, p.sku FROM inventory_moves m JOIN products p ON p.id=m.product_id WHERE 1=1"""
        params = []
        if request.args.get("product_id"):
            sql += " AND m.product_id=?"
            params.append(request.args["product_id"])
        sql += " ORDER BY m.id DESC LIMIT 300"
        return jsonify(dbm.rows_to_list(conn().execute(sql, params).fetchall()))

    # ------------------------------------------------------------ ventas
    @app.post("/api/sales")
    def api_create_sale():
        d = body()
        s = settings()
        items_in = d.get("items") or []
        if not items_in:
            raise ApiError("El ticket está vacío")
        c = conn()
        allow_negative = s.get("allow_negative_stock", "0") == "1"
        lines, used_imeis = [], set()
        qty_by_product = {}
        for it in items_in:
            p = get_product(int(it.get("product_id") or 0))
            qty = num(it.get("qty"), 1)
            if qty <= 0:
                raise ApiError(f"Cantidad inválida para {p['name']}")
            price = num(it.get("unit_price"), p["price"]) if it.get("unit_price") not in (None, "") else float(p["price"])
            if is_vendedor() and abs(price - float(p["price"])) > 0.004:
                raise ApiError(f"Los vendedores no pueden cambiar el precio de {p['name']}; usa descuento o pide autorización.")
            discount = num(it.get("discount"), 0)
            warranty = int(num(it.get("warranty_days"), p["warranty_days"])) if it.get("warranty_days") not in (None, "") else int(p["warranty_days"])
            imei = (it.get("imei") or "").strip()
            if p["serialized"]:
                if not imei:
                    raise ApiError(f"Escanea o selecciona el IMEI de {p['name']}")
                if qty != 1:
                    raise ApiError("Los equipos con IMEI se venden de uno en uno")
                ser = c.execute("SELECT * FROM serials WHERE product_id=? AND imei=?", (p["id"], imei)).fetchone()
                if not ser or ser["status"] != "disponible" or imei in used_imeis:
                    raise ApiError(f"El IMEI {imei} no está disponible")
                used_imeis.add(imei)
            line_total = r2(qty * price - discount)
            if line_total < 0:
                raise ApiError(f"El descuento de {p['name']} es mayor que el importe")
            qty_by_product[p["id"]] = qty_by_product.get(p["id"], 0) + qty
            lines.append({"p": p, "qty": qty, "price": r2(price), "discount": r2(discount), "total": line_total, "imei": imei,
                          "warranty": max(0, warranty)})
        if not allow_negative:
            for pid, qty in qty_by_product.items():
                p = get_product(pid)
                if p["track_stock"] and not p["serialized"] and float(p["stock"]) < qty:
                    raise ApiError(f"Sin existencia suficiente de {p['name']} (hay {float(p['stock']):g})")

        subtotal = r2(sum(l["total"] for l in lines))
        discount = r2(num(d.get("discount"), 0))
        if discount > subtotal:
            raise ApiError("El descuento es mayor que el total")
        rate = num(s.get("tax_rate"), 16) / 100
        if s.get("prices_include_tax", "1") == "1":
            total = r2(subtotal - discount)
            tax = r2(total - total / (1 + rate)) if rate else 0
        else:
            base = subtotal - discount
            tax = r2(base * rate)
            total = r2(base + tax)

        method = d.get("payment_method", "efectivo")
        paid_cash = paid_card = paid_transfer = 0.0
        received = num(d.get("received"), total)
        if method == "efectivo":
            if received + 0.004 < total:
                raise ApiError("El efectivo recibido es menor que el total")
            paid_cash, change = total, r2(received - total)
        elif method == "tarjeta":
            paid_card, received, change = total, total, 0.0
        elif method == "transferencia":
            paid_transfer, received, change = total, total, 0.0
        elif method == "mixto":
            cash_in = num(d.get("paid_cash"))
            paid_card = r2(num(d.get("paid_card")))
            paid_transfer = r2(num(d.get("paid_transfer")))
            received = r2(cash_in + paid_card + paid_transfer)
            if received + 0.004 < total:
                raise ApiError("La suma de los pagos es menor que el total")
            if paid_card + paid_transfer > total + 0.004:
                raise ApiError("Tarjeta + transferencia no pueden exceder el total")
            change = r2(received - total)
            paid_cash = r2(cash_in - change)
        else:
            raise ApiError("Forma de pago inválida")

        cost_total = r2(sum(l["qty"] * float(l["p"]["cost"]) for l in lines))
        user = current_user()
        seller_id = user["id"]
        if d.get("seller_id") and not is_vendedor():
            seller_id = int(d["seller_id"])
        seller = c.execute("SELECT id, full_name FROM users WHERE id=? AND active=1", (seller_id,)).fetchone()
        if not seller:
            raise ApiError("Vendedor inválido")
        ts = dbm.now()
        cur = c.execute(
            """INSERT INTO sales(folio, created_at, subtotal, discount, tax, total, cost_total, payment_method,
                   paid_cash, paid_card, paid_transfer, received, change, customer_name, customer_phone, cashier, notes,
                   user_id, seller_id, seller_name, device_model, device_imei, customer_email)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"TMP-{ts}-{os.getpid()}", ts, subtotal, discount, tax, total, cost_total, method, paid_cash, paid_card,
             paid_transfer, received, change, (d.get("customer_name") or "").strip(), (d.get("customer_phone") or "").strip(),
             user["full_name"], (d.get("notes") or "").strip(), user["id"], seller["id"], seller["full_name"],
             (d.get("device_model") or "").strip(), re.sub(r"\s", "", d.get("device_imei") or ""),
             (d.get("customer_email") or "").strip()))
        sale_id = cur.lastrowid
        folio = f"{s.get('folio_prefix', 'V-')}{sale_id:06d}"
        c.execute("UPDATE sales SET folio=? WHERE id=?", (folio, sale_id))
        for l in lines:
            p = l["p"]
            c.execute("""INSERT INTO sale_items(sale_id, product_id, sku, name, qty, unit_price, unit_cost, discount, total, imei, warranty_days)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (sale_id, p["id"], p["sku"], p["name"], l["qty"], l["price"], p["cost"], l["discount"], l["total"],
                       l["imei"], l["warranty"]))
            if p["serialized"]:
                c.execute("UPDATE serials SET status='vendido', sale_id=? WHERE product_id=? AND imei=?", (sale_id, p["id"], l["imei"]))
                sync_serial_stock(c, p["id"])
                c.execute("INSERT INTO inventory_moves(product_id, qty, kind, reference, notes, created_at) VALUES (?,?,?,?,?,?)",
                          (p["id"], -1, "venta", folio, f"IMEI {l['imei']}", ts))
            elif p["track_stock"]:
                c.execute("UPDATE products SET stock=stock-?, updated_at=? WHERE id=?", (l["qty"], ts, p["id"]))
                c.execute("INSERT INTO inventory_moves(product_id, qty, kind, reference, created_at) VALUES (?,?,?,?,?)",
                          (p["id"], -l["qty"], "venta", folio, ts))
        c.commit()
        sale = _sale(sale_id)
        result = {"sale": strip_costs(dict(sale))}
        if d.get("print", True):
            try:
                result["print"] = _print_sale(sale, s)
            except printing.PrintError as exc:
                result["print_error"] = str(exc)
        return jsonify(result), 201

    def _sale(sale_id):
        c = conn()
        row = c.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not row:
            raise ApiError("Venta no encontrada", 404)
        sale = dict(row)
        sale["items"] = dbm.rows_to_list(c.execute("SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,)).fetchall())
        return sale

    @app.get("/api/sales")
    def api_sales():
        d_from, d_to = date_range()
        q = (request.args.get("q") or "").strip()
        sql = "SELECT s.*, (SELECT SUM(qty) FROM sale_items WHERE sale_id=s.id) AS units FROM sales s WHERE 1=1"
        params = []
        if not (q and request.args.get("all") == "1"):
            sql += " AND date(s.created_at) BETWEEN ? AND ?"
            params += [d_from, d_to]
        if q:
            # búsqueda de garantías: folio, cliente, teléfono, IMEI del equipo del cliente o del equipo vendido
            sql += """ AND (s.folio LIKE ? OR s.customer_name LIKE ? OR s.customer_phone LIKE ? OR s.device_imei LIKE ?
                       OR s.device_model LIKE ? OR s.seller_name LIKE ?
                       OR s.id IN (SELECT sale_id FROM sale_items WHERE name LIKE ? OR imei LIKE ? OR sku LIKE ?))"""
            params += [f"%{q}%"] * 9
        elif is_vendedor():
            sql += " AND s.seller_id=?"
            params.append(current_user()["id"])
        if request.args.get("seller"):
            sql += " AND s.seller_id=?"
            params.append(request.args["seller"])
        sql += " ORDER BY s.id DESC LIMIT 1000"
        return jsonify(strip_costs(dbm.rows_to_list(conn().execute(sql, params).fetchall())))

    @app.get("/api/sales/<int:sale_id>")
    def api_sale(sale_id):
        return jsonify(strip_costs(_sale(sale_id)))

    @app.post("/api/sales/<int:sale_id>/cancel")
    def api_cancel_sale(sale_id):
        sale = _sale(sale_id)
        if sale["status"] == "cancelada":
            raise ApiError("La venta ya está cancelada")
        c = conn()
        ts = dbm.now()
        reason = (body().get("reason") or "").strip()
        for it in sale["items"]:
            if not it["product_id"]:
                continue
            p = c.execute("SELECT * FROM products WHERE id=?", (it["product_id"],)).fetchone()
            if not p:
                continue
            if it["imei"]:
                c.execute("UPDATE serials SET status='disponible', sale_id=NULL WHERE imei=?", (it["imei"],))
                sync_serial_stock(c, p["id"])
                c.execute("INSERT INTO inventory_moves(product_id, qty, kind, reference, notes, created_at) VALUES (?,?,?,?,?,?)",
                          (p["id"], 1, "cancelación", sale["folio"], f"IMEI {it['imei']}", ts))
            elif p["track_stock"]:
                c.execute("UPDATE products SET stock=stock+? WHERE id=?", (it["qty"], p["id"]))
                c.execute("INSERT INTO inventory_moves(product_id, qty, kind, reference, created_at) VALUES (?,?,?,?,?)",
                          (p["id"], it["qty"], "cancelación", sale["folio"], ts))
        notes = (sale.get("notes") or "") + (f" | Cancelada: {reason}" if reason else "")
        c.execute("UPDATE sales SET status='cancelada', cancelled_at=?, notes=? WHERE id=?", (ts, notes.strip(" |"), sale_id))
        c.commit()
        return jsonify(_sale(sale_id))

    # ------------------------------------------------------------ tickets
    def _dispatch_ticket(t, s, title, copies=1):
        mode = s.get("ticket_printer_mode", "browser")
        if mode == "browser":
            return jsonify({"mode": "browser"})
        if mode == "zebra":
            data = tickets.to_zpl(t, s)
            for _ in range(copies):
                printing.send(data, s.get("label_printer_mode") if s.get("label_printer_mode") != "download" else "network",
                              s.get("label_printer_host"), s.get("label_printer_port"), s.get("label_printer_name"))
            return jsonify({"mode": "zebra", "message": f"{title}: enviado a la Zebra"})
        data = tickets.to_escpos(t, open_drawer=s.get("ticket_open_drawer") == "1")
        for _ in range(copies):
            printing.send(data, mode, s.get("ticket_printer_host"), s.get("ticket_printer_port"), s.get("ticket_printer_name"))
        return jsonify({"mode": mode, "message": f"{title}: enviado a la impresora de tickets"})

    def _print_sale(sale, s, reprint=False):
        t = tickets.build_sale_ticket(sale, sale["items"], s, reprint=reprint)
        copies = max(1, int(num(s.get("ticket_copies"), 1)))
        resp = _dispatch_ticket(t, s, f"Ticket {sale['folio']}", copies)
        return resp.get_json()

    @app.post("/api/sales/<int:sale_id>/print")
    def api_print_sale(sale_id):
        return jsonify(_print_sale(_sale(sale_id), settings(), reprint=True))

    @app.get("/tickets/<int:sale_id>")
    def ticket_page(sale_id):
        s = settings()
        sale = _sale(sale_id)
        fmt = request.args.get("format", "html")
        t = tickets.build_sale_ticket(sale, sale["items"], s, reprint=request.args.get("reprint") == "1")
        if fmt == "txt":
            return Response(tickets.to_text(t), mimetype="text/plain; charset=utf-8")
        if fmt == "zpl":
            return Response(tickets.to_zpl(t, s), mimetype="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=ticket_{sale['folio']}.zpl"})
        if fmt == "escpos":
            return Response(tickets.to_escpos(t), mimetype="application/octet-stream",
                            headers={"Content-Disposition": f"attachment; filename=ticket_{sale['folio']}.bin"})
        return tickets.to_html(t, s.get("ticket_width", "80"), f"Ticket {sale['folio']}", autoprint=request.args.get("print") == "1")

    # ------------------------------------------------------------ caja y reportes
    @app.post("/api/cash")
    def api_cash_create():
        d = body()
        kind = d.get("kind")
        if kind not in ("entrada", "salida"):
            raise ApiError("Tipo inválido")
        amount = abs(num(d.get("amount")))
        if not amount:
            raise ApiError("Captura el monto")
        c = conn()
        c.execute("INSERT INTO cash_movements(kind, amount, notes, created_at) VALUES (?,?,?,?)",
                  (kind, amount, d.get("notes", ""), dbm.now()))
        c.commit()
        return jsonify({"ok": True})

    @app.get("/api/cash")
    def api_cash_list():
        d_from, d_to = date_range()
        return jsonify(dbm.rows_to_list(conn().execute(
            "SELECT * FROM cash_movements WHERE date(created_at) BETWEEN ? AND ? ORDER BY id DESC", (d_from, d_to)).fetchall()))

    def _report(d_from, d_to):
        c = conn()
        where = "date(created_at) BETWEEN ? AND ?"
        agg = c.execute(f"""SELECT COUNT(*) n, COALESCE(SUM(total),0) total, COALESCE(SUM(paid_cash),0) cash,
                               COALESCE(SUM(paid_card),0) card, COALESCE(SUM(paid_transfer),0) transfer,
                               COALESCE(SUM(tax),0) tax, COALESCE(SUM(cost_total),0) cost, COALESCE(SUM(discount),0) disc
                            FROM sales WHERE status='completada' AND {where}""", (d_from, d_to)).fetchone()
        line_disc = c.execute(f"""SELECT COALESCE(SUM(i.discount),0), COALESCE(SUM(i.qty),0) FROM sale_items i JOIN sales s ON s.id=i.sale_id
                                  WHERE s.status='completada' AND date(s.created_at) BETWEEN ? AND ?""", (d_from, d_to)).fetchone()
        cancelled = c.execute(f"SELECT COUNT(*) FROM sales WHERE status='cancelada' AND {where}", (d_from, d_to)).fetchone()[0]
        cash_in = c.execute(f"SELECT COALESCE(SUM(amount),0) FROM cash_movements WHERE kind='entrada' AND {where}", (d_from, d_to)).fetchone()[0]
        cash_out = c.execute(f"SELECT COALESCE(SUM(amount),0) FROM cash_movements WHERE kind='salida' AND {where}", (d_from, d_to)).fetchone()[0]
        by_cat = c.execute("""SELECT COALESCE(cat.name,'Sin categoría') category, SUM(i.qty) units, SUM(i.total) total,
                                     SUM(i.total - i.qty*i.unit_cost) profit
                              FROM sale_items i JOIN sales s ON s.id=i.sale_id LEFT JOIN products p ON p.id=i.product_id
                              LEFT JOIN categories cat ON cat.id=p.category_id
                              WHERE s.status='completada' AND date(s.created_at) BETWEEN ? AND ?
                              GROUP BY 1 ORDER BY total DESC""", (d_from, d_to)).fetchall()
        top = c.execute("""SELECT i.name, i.sku, SUM(i.qty) units, SUM(i.total) total FROM sale_items i JOIN sales s ON s.id=i.sale_id
                           WHERE s.status='completada' AND date(s.created_at) BETWEEN ? AND ?
                           GROUP BY i.product_id ORDER BY units DESC, total DESC LIMIT 15""", (d_from, d_to)).fetchall()
        by_day = c.execute("""SELECT date(created_at) day, COUNT(*) n, SUM(total) total FROM sales
                              WHERE status='completada' AND date(created_at) BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""",
                           (d_from, d_to)).fetchall()
        by_seller = c.execute("""SELECT COALESCE(NULLIF(seller_name,''), cashier, 'Sin vendedor') seller, COUNT(*) n, SUM(total) total,
                                        SUM(total - cost_total) profit
                                 FROM sales WHERE status='completada' AND date(created_at) BETWEEN ? AND ?
                                 GROUP BY 1 ORDER BY total DESC""", (d_from, d_to)).fetchall()
        total = r2(agg["total"])
        return {
            "by_seller": [{**dict(r), "total": r2(r["total"] or 0), "profit": r2(r["profit"] or 0)} for r in by_seller],
            "from": d_from, "to": d_to, "generated_at": dbm.now(),
            "sales_count": agg["n"], "cancelled_count": cancelled, "units": float(line_disc[1]),
            "total": total, "cash": r2(agg["cash"]), "card": r2(agg["card"]), "transfer": r2(agg["transfer"]),
            "tax": r2(agg["tax"]), "cost": r2(agg["cost"]), "profit": r2(total - agg["cost"]),
            "discounts": r2(agg["disc"] + line_disc[0]),
            "average_ticket": r2(total / agg["n"]) if agg["n"] else 0,
            "cash_in": r2(cash_in), "cash_out": r2(cash_out), "expected_cash": r2(cash_in + agg["cash"] - cash_out),
            "by_category": [{**dict(r), "units": float(r["units"] or 0), "total": r2(r["total"] or 0), "profit": r2(r["profit"] or 0)} for r in by_cat],
            "top_products": dbm.rows_to_list(top),
            "by_day": dbm.rows_to_list(by_day),
        }

    @app.get("/api/reports/summary")
    def api_report():
        return jsonify(_report(*date_range()))

    @app.get("/reports/corte")
    def corte_page():
        s = settings()
        t = tickets.build_cut_ticket(_report(*date_range()), s)
        return tickets.to_html(t, s.get("ticket_width", "80"), "Corte de caja", autoprint=request.args.get("print") == "1")

    @app.post("/api/reports/corte/print")
    def api_corte_print():
        s = settings()
        return _dispatch_ticket(tickets.build_cut_ticket(_report(*date_range()), s), s, "Corte de caja")

    @app.get("/api/dashboard")
    def api_dashboard():
        c = conn()
        today = date.today().isoformat()
        rep = _report(today, today)
        low = c.execute("SELECT COUNT(*) FROM products WHERE active=1 AND track_stock=1 AND stock<=min_stock").fetchone()[0]
        products = c.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0]
        value = c.execute("SELECT COALESCE(SUM(stock*cost),0), COALESCE(SUM(stock*price),0) FROM products WHERE active=1 AND track_stock=1").fetchone()
        return jsonify({"today": rep, "low_stock": low, "products": products,
                        "inventory_cost": r2(value[0]), "inventory_retail": r2(value[1])})

    # ------------------------------------------------------------ etiquetas Zebra
    def _label_jobs(d, s):
        """Convierte la cola de etiquetas en (plantilla, datos, copias)."""
        template = d.get("template") or s.get("label_template", "accesorio_50x25")
        jobs = []
        for item in d.get("items") or []:
            copies = max(0, int(num(item.get("qty"), 1)))
            tpl = item.get("template") or template
            if item.get("custom"):
                cd = item["custom"]
                data = {"store": s.get("store_name", ""), "symbol": s.get("currency_symbol", "$"),
                        "name": cd.get("name", ""), "price": cd.get("price", ""), "sku": cd.get("sku", ""),
                        "barcode": cd.get("barcode") or cd.get("sku") or "", "brand": cd.get("brand", ""),
                        "model": cd.get("model", ""), "color": cd.get("color", ""), "capacity": cd.get("capacity", ""),
                        "imei": cd.get("imei", "")}
                if copies:
                    jobs.append((tpl, data, copies))
                continue
            p = get_product(int(item.get("product_id") or 0))
            if item.get("all_imeis") and p["serialized"]:
                for ser in conn().execute("SELECT imei FROM serials WHERE product_id=? AND status='disponible' ORDER BY id",
                                          (p["id"],)).fetchall():
                    jobs.append((tpl, labels.label_data_from_product(p, s, ser["imei"]), max(1, copies)))
            elif copies:
                jobs.append((tpl, labels.label_data_from_product(p, s, item.get("imei")), copies))
        if not jobs:
            raise ApiError("No hay etiquetas para imprimir")
        return jobs

    @app.post("/api/labels/preview")
    def api_label_preview():
        d = body()
        s = settings()
        if d.get("label_dpi"):
            s["label_dpi"] = str(d["label_dpi"])
        jobs = _label_jobs({**d, "items": d.get("items") or [d.get("item") or {}]}, s)
        tpl, data, _ = jobs[0]
        return jsonify({"svg": labels.label_svg(tpl, data, s), "zpl": labels.label_zpl(tpl, data, s), "count": len(jobs)})

    @app.post("/api/labels/zpl")
    def api_label_zpl():
        d = body()
        s = settings()
        jobs = _label_jobs(d, s)
        zpl = "".join(labels.label_zpl(t, data, s, copies) for t, data, copies in jobs)
        total = sum(c for _, _, c in jobs)
        if d.get("print"):
            mode = s.get("label_printer_mode", "download")
            if mode == "download":
                raise ApiError("La impresora de etiquetas está en modo 'Descargar archivo'. Configúrala en Configuración.")
            printing.send(zpl, mode, s.get("label_printer_host"), s.get("label_printer_port"), s.get("label_printer_name"))
            return jsonify({"message": f"{total} etiqueta(s) enviadas a la Zebra", "count": total})
        if d.get("download"):
            return Response(zpl, mimetype="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=etiquetas_{datetime.now():%Y%m%d_%H%M}.zpl"})
        return jsonify({"zpl": zpl, "count": total})

    # ------------------------------------------------------------ importar / exportar / respaldo
    CSV_FIELDS = ["sku", "barcode", "name", "brand", "model", "color", "capacity", "category", "cost", "price",
                  "wholesale_price", "stock", "min_stock", "serialized", "track_stock", "warranty_days", "location", "notes"]

    @app.get("/api/products/export.csv")
    def api_export_csv():
        rows = conn().execute("""SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c ON c.id=p.category_id
                                 WHERE p.active=1 ORDER BY p.name""").fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(CSV_FIELDS)
        for r in rows:
            w.writerow([r[f] if f != "category" else (r["category"] or "") for f in CSV_FIELDS])
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=productos_{date.today()}.csv"})

    @app.post("/api/products/import")
    def api_import_csv():
        f = request.files.get("file")
        if not f:
            raise ApiError("Selecciona un archivo CSV")
        raw = f.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t") if text.strip() else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        c = conn()
        cats = {r["name"].lower(): r["id"] for r in c.execute("SELECT id, name FROM categories")}
        created = updated = 0
        errors = []
        ts = dbm.now()
        for n, row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            try:
                cat_name = row.get("category") or row.get("categoria") or ""
                cat_id = cats.get(cat_name.lower()) if cat_name else None
                if cat_name and not cat_id:
                    prefix = re.sub(r"[^A-Z]", "", cat_name.upper())[:3] or "GEN"
                    while c.execute("SELECT 1 FROM categories WHERE prefix=?", (prefix,)).fetchone():
                        prefix = prefix[:2] + str(len(cats) % 10)
                    cat_id = c.execute("INSERT INTO categories(name, prefix) VALUES (?,?)", (cat_name, prefix)).lastrowid
                    cats[cat_name.lower()] = cat_id
                data = {k: row.get(k) for k in PRODUCT_FIELDS if row.get(k) not in (None, "")}
                data["name"] = row.get("name") or row.get("nombre") or ""
                if cat_id:
                    data["category_id"] = cat_id
                existing = None
                if row.get("sku"):
                    existing = c.execute("SELECT * FROM products WHERE sku=?", (row["sku"].upper(),)).fetchone()
                if not existing and row.get("barcode"):
                    existing = c.execute("SELECT * FROM products WHERE barcode=?", (row["barcode"],)).fetchone()
                if existing:
                    vals = _product_values(data, c, dict(existing))
                    _check_unique(c, vals, existing["id"])
                    c.execute(f"UPDATE products SET {', '.join(f'{k}=?' for k in vals)}, active=1, updated_at=? WHERE id=?",
                              list(vals.values()) + [ts, existing["id"]])
                    pid = existing["id"]
                    updated += 1
                else:
                    vals = _product_values(data, c)
                    _check_unique(c, vals)
                    cols = list(vals.keys())
                    pid = c.execute(f"INSERT INTO products({', '.join(cols)}, stock, created_at, updated_at) VALUES "
                                    f"({', '.join('?' * len(cols))}, 0, ?, ?)", [vals[k] for k in cols] + [ts, ts]).lastrowid
                    created += 1
                if row.get("stock") not in (None, "") and not vals["serialized"]:
                    new_stock = num(row["stock"])
                    old = c.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()["stock"]
                    if new_stock != old:
                        c.execute("UPDATE products SET stock=? WHERE id=?", (new_stock, pid))
                        c.execute("INSERT INTO inventory_moves(product_id, qty, kind, notes, created_at) VALUES (?,?,?,?,?)",
                                  (pid, new_stock - old, "conteo", "Importación CSV", ts))
            except ApiError as exc:
                errors.append(f"Fila {n}: {exc}")
        c.commit()
        return jsonify({"created": created, "updated": updated, "errors": errors[:50]})

    @app.get("/api/products/template.csv")
    def api_csv_template():
        sample = [CSV_FIELDS,
                  ["", "", "Funda uso rudo Galaxy A15", "Samsung", "Galaxy A15", "Negro", "", "Fundas", "60", "", "", "10", "3", "0", "1", "0", "", ""],
                  ["", "7501234567895", "Cargador 20W USB-C", "Apple", "", "Blanco", "", "Cargadores", "180", "349", "", "5", "2", "0", "1", "30", "Vitrina 1", ""]]
        buf = io.StringIO()
        csv.writer(buf).writerows(sample)
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=plantilla_productos.csv"})

    @app.get("/api/backup")
    def api_backup():
        c = conn()
        c.execute("PRAGMA wal_checkpoint(FULL)")
        return send_file(app.config["DB_PATH"], as_attachment=True,
                         download_name=f"respaldo_punto_de_venta_{datetime.now():%Y%m%d_%H%M}.db")

    @app.get("/api/barcode/validate")
    def api_barcode_validate():
        code = request.args.get("code", "")
        return jsonify({"ean13": is_valid_ean13(code)})

    app.ApiError = ApiError
    return app


def main():
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    app = create_app()
    url = f"http://localhost:{port}"
    print("=" * 60)
    print(" Punto de venta listo. Abre en tu navegador:", url)
    print(" Base de datos:", app.config["DB_PATH"])
    print(" Para cerrar presiona Ctrl+C")
    print("=" * 60)
    if os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
