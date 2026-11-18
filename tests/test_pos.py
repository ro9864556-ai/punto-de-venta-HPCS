import io

import pytest

from app import create_app
from pos.barcodes import code128_modules, ean13_check_digit, is_valid_ean13
from pos.labels import TEMPLATES, label_svg, label_zpl
from pos.pricing import round_price, suggest_price


@pytest.fixture()
def app(tmp_path):
    return create_app(str(tmp_path / "test.db"))


def login(app, user="admin", pwd="admin"):
    c = app.test_client()
    r = c.post("/api/login", json={"username": user, "password": pwd})
    assert r.status_code == 200, r.get_json()
    return c


@pytest.fixture()
def client(app):
    return login(app)


def test_round_price():
    assert round_price(143, "9") == 149
    assert round_price(149, "9") == 149
    assert round_price(150.2, "9") == 159
    assert round_price(143.2, "99") == 143.99
    assert round_price(143.2, "10") == 150
    assert round_price(143.2, "50") == 143.5
    assert round_price(0, "9") == 0


def test_suggest_price_adds_tax_when_cost_without_tax():
    r = suggest_price(100, 50, 16, cost_includes_tax=False, prices_include_tax=True, rounding="none")
    assert r["price"] == 174.0


def test_ean13():
    assert ean13_check_digit("750103131130") == "9"
    assert is_valid_ean13("7501031311309")
    assert not is_valid_ean13("7501031311308")


def test_code128_width():
    assert len(code128_modules("123456")) == 68


@pytest.mark.parametrize("tpl", list(TEMPLATES))
def test_labels_render(tpl):
    d = {"store": "Tienda", "name": "Funda uso rudo con un nombre larguísimo para probar el ajuste ñ", "price": 249,
         "sku": "FUN-SAM-0001", "barcode": "2000000000015", "imei": "356789012345678", "brand": "Samsung", "model": "A15"}
    s = {"label_dpi": "203"}
    z = label_zpl(tpl, d, s, copies=3)
    assert z.startswith("^XA") and z.strip().endswith("^XZ") and "^PQ3" in z
    assert "^CI28" in z
    assert "<svg" in label_svg(tpl, d, s)


def _product(client, **kw):
    data = {"name": "Funda Galaxy A15", "brand": "Samsung", "category_id": 2, "cost": 60, "price": 199, "initial_stock": 5}
    data.update(kw)
    r = client.post("/api/products", json=data)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_product_autocodes(client):
    p = _product(client)
    assert p["sku"] == "FUN-SAM-0001"
    assert is_valid_ean13(p["barcode"]) and p["barcode"].startswith("20")
    assert p["stock"] == 5
    p2 = _product(client, name="Otra funda")
    assert p2["sku"] == "FUN-SAM-0002"
    assert client.post("/api/products", json={"name": "dup", "sku": p["sku"]}).status_code == 400


def test_sale_flow_and_cancel(client):
    p = _product(client)
    phone = _product(client, name="Galaxy A15 128GB", category_id=1, cost=2800, price=3499, serialized=1,
                     initial_stock=0, imeis="356789012345678\n356789012345679", warranty_days=90)
    assert phone["stock"] == 2
    look = client.get("/api/lookup?code=356789012345678").get_json()
    assert look["product"]["id"] == phone["id"] and look["imei"] == "356789012345678"
    assert client.get(f"/api/lookup?code={p['barcode']}").get_json()["product"]["id"] == p["id"]

    r = client.post("/api/sales", json={
        "items": [{"product_id": p["id"], "qty": 2, "discount": 20},
                  {"product_id": phone["id"], "qty": 1, "imei": "356789012345678"}],
        "payment_method": "efectivo", "received": 4000, "customer_name": "Juan"})
    assert r.status_code == 201, r.get_json()
    sale = r.get_json()["sale"]
    assert sale["total"] == 199 * 2 - 20 + 3499
    assert sale["change"] == round(4000 - sale["total"], 2)
    assert sale["folio"] == "V-000001"
    assert client.get(f"/api/products/{p['id']}").get_json()["stock"] == 3
    assert client.get(f"/api/products/{phone['id']}").get_json()["stock"] == 1
    # IMEI ya vendido
    assert client.get("/api/lookup?code=356789012345678").status_code == 409
    # ticket
    html = client.get(f"/tickets/{sale['id']}").get_data(as_text=True)
    assert "V-000001" in html and "356789012345678" in html
    assert client.get(f"/tickets/{sale['id']}?format=zpl").get_data(as_text=True).startswith("^XA")
    assert client.get(f"/tickets/{sale['id']}?format=escpos").data.startswith(b"\x1b@")
    rep = client.get("/api/reports/summary").get_json()
    assert rep["total"] == sale["total"] and rep["cash"] == sale["total"]
    assert rep["profit"] == round(sale["total"] - (60 * 2 + 2800), 2)
    # cancelar
    assert client.post(f"/api/sales/{sale['id']}/cancel", json={"reason": "prueba"}).status_code == 200
    assert client.get(f"/api/products/{p['id']}").get_json()["stock"] == 5
    assert client.get(f"/api/products/{phone['id']}").get_json()["stock"] == 2
    assert client.get("/api/reports/summary").get_json()["total"] == 0


def test_sale_validations(client):
    p = _product(client, initial_stock=1)
    r = client.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 2}], "payment_method": "tarjeta"})
    assert r.status_code == 400 and "existencia" in r.get_json()["error"]
    r = client.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 1}], "payment_method": "efectivo", "received": 10})
    assert r.status_code == 400
    r = client.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 1}], "payment_method": "mixto",
                                         "paid_cash": 100, "paid_card": 99})
    assert r.status_code == 201
    assert r.get_json()["sale"]["paid_card"] == 99 and r.get_json()["sale"]["paid_cash"] == 100


def test_labels_api(client):
    p = _product(client)
    r = client.post("/api/labels/preview", json={"template": "accesorio_50x25", "item": {"product_id": p["id"]}})
    assert r.status_code == 200 and "<svg" in r.get_json()["svg"]
    r = client.post("/api/labels/zpl", json={"items": [{"product_id": p["id"], "qty": 4},
                                                       {"custom": {"name": "Libre", "price": 50, "barcode": "ABC-1"}, "qty": 1}]})
    j = r.get_json()
    assert j["count"] == 5 and j["zpl"].count("^XA") == 2


def test_bulk_pricing_and_csv(client):
    p = _product(client, cost=100)
    r = client.post("/api/pricing/bulk", json={"category_id": 2, "value": 100, "rounding": "9", "apply": True}).get_json()
    assert r["rows"][0]["new_price"] == 209
    csv_text = client.get("/api/products/export.csv").get_data(as_text=True)
    assert p["sku"] in csv_text
    data = "name,category,cost,price,stock\nCable USB-C 1m,Cables,35,99,12\n"
    r = client.post("/api/products/import", data={"file": (io.BytesIO(data.encode()), "p.csv")},
                    content_type="multipart/form-data").get_json()
    assert r["created"] == 1 and not r["errors"]
    found = client.get("/api/products?q=Cable").get_json()[0]
    assert found["sku"].startswith("CAB-") and found["stock"] == 12


def test_requires_login(app):
    anon = app.test_client()
    assert anon.get("/api/products").status_code == 401
    assert anon.get("/").status_code == 302
    assert anon.get("/login").status_code == 200
    assert anon.post("/api/login", json={"username": "admin", "password": "mal"}).status_code == 401


def test_roles_and_vendedor_rules(app, client):
    assert client.post("/api/users", json={"username": "luis", "full_name": "Luis Vendedor", "role": "vendedor", "password": "1234"}).status_code == 201
    assert client.post("/api/users", json={"username": "caja", "full_name": "Caja 1", "role": "cajero", "password": "1234"}).status_code == 201
    mica = _product(client, name="Mica de hidrogel HD", category_id=3, cost=40, price=259, track_stock=0,
                    warranty_days=180, ask_device=1)
    vend = login(app, "luis", "1234")
    caja = login(app, "caja", "1234")
    # permisos
    assert vend.post("/api/products", json={"name": "x"}).status_code == 403
    assert caja.post("/api/products", json={"name": "x"}).status_code == 403
    assert vend.get("/api/reports/summary").status_code == 403
    assert caja.get("/api/reports/summary").status_code == 200
    assert vend.get("/api/users").status_code == 403
    assert "cost" not in vend.get(f"/api/products/{mica['id']}").get_json()
    # el vendedor no cambia precios, pero sí puede descontar
    r = vend.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1, "unit_price": 100}], "payment_method": "efectivo", "received": 300})
    assert r.status_code == 400
    r = vend.post("/api/sales", json={
        "items": [{"product_id": mica["id"], "qty": 1, "discount": 9}], "payment_method": "efectivo", "received": 300,
        "customer_name": "María López", "customer_phone": "5512345678",
        "device_model": "iPhone 17 Pro Max", "device_imei": "35 123456 789012 3", "seller_id": 1})
    assert r.status_code == 201, r.get_json()
    sale = r.get_json()["sale"]
    assert sale["seller_name"] == "Luis Vendedor"  # un vendedor no puede vender a nombre de otro
    assert sale["device_imei"] == "351234567890123" and "cost_total" not in sale
    text = vend.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True)
    for frag in ("Vendedor:", "Luis Vendedor", "María López", "5512345678", "Mica de hidrogel HD",
                 "Garantía: 6 meses", "iPhone 17 Pro Max", "351234567890123", "TOTAL $250.00"):
        assert frag in text, frag
    # el cajero cobra a nombre de un vendedor
    r = caja.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1}], "payment_method": "tarjeta", "seller_id": 2})
    assert r.get_json()["sale"]["seller_name"] == "Luis Vendedor"
    # búsqueda de garantía por IMEI en todas las fechas
    found = vend.get("/api/sales?q=351234567890123&all=1&from=2000-01-01&to=2000-01-02").get_json()
    assert [s["id"] for s in found] == [sale["id"]]
    rep = client.get("/api/reports/summary").get_json()
    assert rep["by_seller"][0]["seller"] == "Luis Vendedor" and rep["by_seller"][0]["n"] == 2
    # cancelar solo admin
    assert caja.post(f"/api/sales/{sale['id']}/cancel", json={}).status_code == 403


def test_last_admin_and_password(app, client):
    assert client.put("/api/users/1", json={"username": "admin", "full_name": "A", "role": "cajero"}).status_code == 400
    assert client.post("/api/me/password", json={"current": "admin", "new": "nueva123"}).status_code == 200
    login(app, "admin", "nueva123")


def test_bulk_create_micas(client):
    rows = [{"name": "Mica de hidrogel HD", "category_id": 3, "price": 259, "warranty_days": 180, "track_stock": 0, "ask_device": 1},
            {"name": "Mica de hidrogel mate", "category_id": 3, "price": 259, "warranty_days": 180, "track_stock": 0},
            {"name": ""}]
    r = client.post("/api/products/bulk", json={"rows": rows}).get_json()
    assert len(r["created"]) == 2 and not r["errors"]
    assert r["created"][0]["sku"].startswith("MIC-")


def test_logo_in_tickets(client):
    p = _product(client)
    sale = client.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 1}], "payment_method": "tarjeta",
                                           "print": False}).get_json()["sale"]
    assert b"\x1dv0\x00" in client.get(f"/tickets/{sale['id']}?format=escpos").data  # imagen raster ESC/POS
    assert "^GFA," in client.get(f"/tickets/{sale['id']}?format=zpl").get_data(as_text=True)
    assert 'class="logo"' in client.get(f"/tickets/{sale['id']}").get_data(as_text=True)
    assert client.get("/logo-ticket.png").status_code == 200
    assert client.application.test_client().get("/logo.png").status_code == 200  # visible en el login
    client.put("/api/settings", json={"ticket_logo": "0"})
    assert b"\x1dv0\x00" not in client.get(f"/tickets/{sale['id']}?format=escpos").data
