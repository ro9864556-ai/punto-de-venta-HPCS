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
    c = login(app)
    c.post("/api/branch/select", json={"branch_id": 2})  # J. Jesús Reynoso (la Matriz es bodega)
    return c


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
    assert sale["folio"] == "JR-000001"  # venta en J. Jesús Reynoso
    assert client.get(f"/api/products/{p['id']}").get_json()["stock"] == 3
    assert client.get(f"/api/products/{phone['id']}").get_json()["stock"] == 1
    # IMEI ya vendido
    assert client.get("/api/lookup?code=356789012345678").status_code == 409
    # ticket
    html = client.get(f"/tickets/{sale['id']}").get_data(as_text=True)
    assert "JR-000001" in html and "356789012345678" in html
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
    # el vendedor no cobra: manda la nota a caja
    r = vend.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1}], "payment_method": "efectivo", "received": 300})
    assert r.status_code == 403
    # no cambia precios, pero sí puede descontar
    r = vend.post("/api/sales/pending", json={"items": [{"product_id": mica["id"], "qty": 1, "unit_price": 100}]})
    assert r.status_code == 400
    r = vend.post("/api/sales/pending", json={
        "items": [{"product_id": mica["id"], "qty": 1, "discount": 9}],
        "customer_name": "María López", "customer_phone": "5512345678",
        "device_model": "iPhone 17 Pro Max", "device_imei": "35 123456 789012 3", "seller_id": 1})
    assert r.status_code == 201, r.get_json()
    pend = r.get_json()["sale"]
    assert pend["status"] == "pendiente" and pend["seller_name"] == "Luis Vendedor"  # no puede usar a otro vendedor
    assert [x["id"] for x in caja.get("/api/sales/pending").get_json()] == [pend["id"]]
    assert client.get("/api/reports/summary").get_json()["sales_count"] == 0  # pendiente no cuenta
    # el cajero cobra la nota pendiente (el vendedor se conserva)
    r = caja.post("/api/sales", json={"pending_id": pend["id"], "items": [{"product_id": mica["id"], "qty": 1, "discount": 9}],
                                      "payment_method": "efectivo", "received": 300, "customer_name": "María López",
                                      "customer_phone": "5512345678", "device_model": "iPhone 17 Pro Max",
                                      "device_imei": "351234567890123"})
    assert r.status_code == 201, r.get_json()
    sale = r.get_json()["sale"]
    assert sale["id"] == pend["id"] and sale["folio"] == pend["folio"] and sale["status"] == "completada"
    assert sale["seller_name"] == "Luis Vendedor" and sale["cashier"] == "Caja 1"
    assert caja.get("/api/sales/pending").get_json() == []
    assert caja.post("/api/sales", json={"pending_id": pend["id"], "items": [{"product_id": mica["id"]}], "payment_method": "tarjeta"}).status_code == 400
    assert sale["device_imei"] == "351234567890123"
    text = vend.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True)
    for frag in ("Vendedor:", "Luis Vendedor", "María López", "5512345678", "Mica de hidrogel HD",
                 "Garantía: 6 meses", "iPhone 17 Pro Max", "351234567890123", "TOTAL $250.00"):
        assert frag in text, frag
    # el vendedor puede descartar su propia nota pendiente
    p2 = vend.post("/api/sales/pending", json={"items": [{"product_id": mica["id"], "qty": 1}]}).get_json()["sale"]
    assert vend.delete(f"/api/sales/pending/{p2['id']}").status_code == 200
    # cajero cobra directo a nombre de un vendedor
    r = caja.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1}], "payment_method": "tarjeta", "seller_id": 2})
    assert r.get_json()["sale"]["seller_name"] == "Luis Vendedor"
    # búsqueda de garantía por IMEI en todas las fechas
    found = vend.get("/api/sales?q=351234567890123&all=1&from=2000-01-01&to=2000-01-02").get_json()
    assert [s["id"] for s in found] == [sale["id"]]
    rep = client.get("/api/reports/summary").get_json()
    assert rep["by_seller"][0]["seller"] == "Luis Vendedor" and rep["by_seller"][0]["n"] == 2
    # cancelar solo admin
    assert caja.post(f"/api/sales/{sale['id']}/cancel", json={}).status_code == 403


def test_warranty_changes(app, client):
    client.post("/api/users", json={"username": "caja", "full_name": "Caja 1", "role": "cajero", "password": "1234"})
    client.post("/api/users", json={"username": "luis", "full_name": "Luis", "role": "vendedor", "password": "1234"})
    mica = _product(client, name="Mica de cristal Samsung A07", category_id=3, cost=30, price=129, initial_stock=10,
                    warranty_days=365, warranty_changes=3, ask_device=1)
    caja = login(app, "caja", "1234")
    sale = caja.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1}], "payment_method": "efectivo",
                                         "received": 129, "customer_phone": "55 1111 2222", "device_model": "Samsung A07",
                                         "device_imei": "359876543210987"}).get_json()["sale"]
    assert sale["items"][0]["warranty_changes"] == 3
    text = caja.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True)
    assert "Incluye 3 cambios" in text and "CONTROL DE CAMBIOS" in text and text.count("Firma:") == 3
    # búsqueda: por folio escaneado, IMEI y teléfono
    for q in (sale["folio"], "359876543210987", "5511112222"):
        res = caja.get(f"/api/warranty?q={q}").get_json()
        assert len(res) == 1 and res[0]["changes_left"] == 3 and res[0]["valid"], q
    item_id = res[0]["id"]
    # el vendedor puede consultar pero no registrar
    assert login(app, "luis", "1234").post("/api/warranty/claims", json={"sale_item_id": item_id}).status_code == 403
    for n in (1, 2, 3):
        r = caja.post("/api/warranty/claims", json={"sale_item_id": item_id, "notes": "se estrelló"}).get_json()
        assert r["item"]["changes_used"] == n
    assert r["item"]["changes_left"] == 0
    assert client.get(f"/api/products/{mica['id']}").get_json()["stock"] == 10 - 1 - 3  # venta + 3 micas de cambio
    claim_txt = caja.get(f"/tickets/cambio/{r['claim_id']}").get_data(as_text=True)
    assert "Cambio 3 de 3" in claim_txt and "Cambios restantes: 0" in claim_txt
    # sin cambios restantes: el cajero no puede; el admin puede autorizar
    assert caja.post("/api/warranty/claims", json={"sale_item_id": item_id}).status_code == 400
    r = client.post("/api/warranty/claims", json={"sale_item_id": item_id, "force": True})
    assert r.status_code == 201 and r.get_json()["item"]["changes_used"] == 4


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


def test_device_only_with_warranty(client):
    cable = _product(client, name="Cable USB-C", category_id=5, price=99, warranty_days=0)
    sale = client.post("/api/sales", json={"items": [{"product_id": cable["id"], "qty": 1}], "payment_method": "tarjeta",
                                           "device_model": "iPhone 13", "device_imei": "351111111111111"}).get_json()["sale"]
    assert sale["device_imei"] == "" and sale["device_model"] == ""
    assert "EQUIPO DEL CLIENTE" not in client.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True)


def test_phone_label_and_scan_to_sell(client):
    """Ejemplo real: Samsung Galaxy A07 4GB/128GB verde, nuevo, 1 año, IMEI 350000000000000."""
    phone = _product(client, name="Samsung Galaxy A07 4GB/128GB Verde", brand="Samsung", model="Galaxy A07", ram="4GB",
                     capacity="128GB", color="Verde", condition="Nuevo", category_id=1, cost=2300, price=2899,
                     serialized=1, warranty_days=365, initial_stock=0, imeis="350000000000000")
    assert phone["stock"] == 1 and phone["ram"] == "4GB" and phone["condition"] == "Nuevo"
    r = client.post("/api/labels/zpl", json={"template": "celular_50x38",
                                             "items": [{"product_id": phone["id"], "all_imeis": True, "qty": 1}]}).get_json()
    zpl = r["zpl"]
    assert r["count"] == 1
    for frag in ("Samsung Galaxy A07", "4GB RAM · 128GB · Verde", "NUEVO · Garantía 1 año", "$2,899", "IMEI: 350000000000000"):
        assert frag in zpl, frag
    assert "^BC" in zpl and ">;35000000000000>60" in zpl  # código de barras Code 128 con el IMEI
    # al escanear la etiqueta en caja se encuentra ese equipo exacto
    look = client.get("/api/lookup?code=350000000000000").get_json()
    assert look["product"]["id"] == phone["id"] and look["imei"] == "350000000000000"
    sale = client.post("/api/sales", json={"items": [{"product_id": phone["id"], "qty": 1, "imei": "350000000000000"}],
                                           "payment_method": "efectivo", "received": 3000}).get_json()["sale"]
    assert sale["items"][0]["imei"] == "350000000000000" and sale["items"][0]["warranty_days"] == 365
    assert client.get(f"/api/products/{phone['id']}").get_json()["stock"] == 0
    assert client.get("/api/lookup?code=350000000000000").status_code == 409  # ya vendido


def test_branches_stock_transfer_reports_and_agent(app, client):
    import base64
    branches = {b["code"]: b for b in client.get("/api/branches").get_json()}
    assert [b["name"] for b in branches.values()] == ["Matriz", "J. Jesús Reynoso", "González Gallo"]
    s2 = branches["JR"]["id"]
    assert client.put(f"/api/branches/{s2}", json={"name": "J. Jesús Reynoso", "code": "JR", "address": "Calle 5 #20",
                                                    "phone": "55 2222 3333"}).status_code == 200
    client.post("/api/users", json={"username": "caja2", "full_name": "Caja Reynoso", "role": "cajero", "password": "1234", "branch_id": s2})
    client.post("/api/branch/select", json={"branch_id": 1})
    funda = _product(client, initial_stock=5)  # la mercancía entra a la Matriz (bodega)
    phone = _product(client, name="Galaxy A07", category_id=1, price=2899, serialized=1, initial_stock=0, imeis="350000000000000")
    caja2 = login(app, "caja2", "1234")
    assert caja2.get("/api/me").get_json()["branch"]["code"] == "JR"
    assert caja2.get(f"/api/products/{funda['id']}").get_json()["stock"] == 0  # existencia separada
    assert caja2.post("/api/sales", json={"items": [{"product_id": funda["id"], "qty": 1}], "payment_method": "tarjeta"}).status_code == 400
    # el teléfono está en la Matriz
    r = caja2.get("/api/lookup?code=350000000000000")
    assert r.status_code == 409 and "Matriz" in r.get_json()["error"]
    # traspasos Matriz → Centro
    assert client.post("/api/inventory/transfer", json={"product_id": funda["id"], "to_branch_id": s2, "qty": 2}).status_code == 200
    assert client.post("/api/inventory/transfer", json={"product_id": phone["id"], "to_branch_id": s2, "imeis": "350000000000000"}).status_code == 200
    assert client.post("/api/inventory/transfer", json={"product_id": funda["id"], "to_branch_id": s2, "qty": 50}).status_code == 400
    p = client.get(f"/api/products/{funda['id']}").get_json()
    assert p["stock"] == 3 and p["stock_total"] == 5
    assert {b["name"]: b["stock"] for b in p["stock_by_branch"]} == {"Matriz": 3, "J. Jesús Reynoso": 2, "González Gallo": 0}
    # venta en Centro: folio con su clave y existencia de Centro
    sale = caja2.post("/api/sales", json={"items": [{"product_id": funda["id"], "qty": 1},
                                                   {"product_id": phone["id"], "qty": 1, "imei": "350000000000000"}],
                                          "payment_method": "efectivo", "received": 5000}).get_json()["sale"]
    assert sale["folio"].startswith("JR-") and sale["branch_id"] == s2
    assert caja2.get(f"/api/products/{funda['id']}").get_json()["stock"] == 1
    assert client.get(f"/api/products/{funda['id']}").get_json()["stock"] == 3
    txt = caja2.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True)
    assert "Sucursal:" in txt and "J. Jesús Reynoso" in txt and "Calle 5 #20" in txt
    # la Matriz es bodega: no vende ni recibe notas
    r = client.post("/api/sales", json={"items": [{"product_id": funda["id"], "qty": 1}], "payment_method": "tarjeta"})
    assert r.status_code == 400 and "bodega" in r.get_json()["error"]
    assert client.post("/api/sales/pending", json={"items": [{"product_id": funda["id"], "qty": 1}]}).status_code == 400
    assert client.post("/api/branch/select", json={"branch_id": 3}).status_code == 200
    client.post("/api/inventory/adjust", json={"product_id": funda["id"], "kind": "entrada", "qty": 1})
    m = client.post("/api/sales", json={"items": [{"product_id": funda["id"], "qty": 1}], "payment_method": "tarjeta", "print": False}).get_json()["sale"]
    assert m["folio"].startswith("GG-")
    client.post("/api/branch/select", json={"branch_id": 1})
    # reportes: cajero solo su sucursal; administrador elige una o todas
    assert caja2.get("/api/reports/summary?branch=all").get_json()["sales_count"] == 1
    assert client.get("/api/reports/summary").get_json()["sales_count"] == 0  # Matriz (bodega)
    allr = client.get("/api/reports/summary?branch=all").get_json()
    assert allr["sales_count"] == 2 and {b["branch"]: b["n"] for b in allr["by_branch"]} == {"Matriz": 0, "J. Jesús Reynoso": 1, "González Gallo": 1}
    assert len(caja2.get("/api/sales?from=2000-01-01&to=2999-12-31&branch=all").get_json()) == 1
    # impresión por agente: el administrador configura la impresora de Centro
    assert client.post("/api/branch/select", json={"branch_id": s2}).status_code == 200
    assert client.get("/api/settings").get_json()["settings"]["ticket_printer_mode"] == "agent"  # sucursales: agente
    client.post("/api/branch/select", json={"branch_id": 1})
    st = client.get("/api/settings").get_json()["settings"]
    assert st["ticket_printer_mode"] != "agent" and st["label_printer_mode"] == "local"  # Matriz = servidor con Zebra USB
    r = caja2.post(f"/api/sales/{sale['id']}/print").get_json()
    assert r["mode"] == "agent"
    token = [b for b in client.get("/api/branches").get_json() if b["id"] == s2][0]["agent_token"]
    assert "agent_token" not in caja2.get("/api/branches").get_json()[0]
    anon = app.test_client()
    assert anon.get("/api/agent/jobs?code=JR&token=mal").status_code == 401
    jobs = anon.get(f"/api/agent/jobs?code=JR&token={token}").get_json()["jobs"]
    # venta original + reimpresión: las sucursales imprimen por agente desde la instalación
    assert [j["title"] for j in jobs] == ["Ticket JR-000001", "Ticket JR-000001"]
    assert all(base64.b64decode(j["data"]).startswith(b"\x1b@") for j in jobs)
    for j in jobs:
        assert anon.post(f"/api/agent/jobs/{j['id']}/done?code=JR&token={token}", json={"ok": True}).status_code == 200
    assert anon.get(f"/api/agent/jobs?code=JR&token={token}").get_json()["jobs"] == []
    cfg = client.get(f"/api/branches/{s2}/agente.json").get_json()
    assert cfg["sucursal"] == "JR" and cfg["token"] == token


def test_matriz_supervisor_role(app, client):
    """Matriz: revisa ambas sucursales y sube inventario a cualquiera; no configura ni cancela."""
    client.post("/api/users", json={"username": "matriz", "full_name": "Encargado Matriz", "role": "matriz",
                                    "password": "1234", "branch_id": 1})
    client.post("/api/users", json={"username": "caja", "full_name": "Caja GG", "role": "cajero", "password": "1234", "branch_id": 3})
    m = login(app, "matriz", "1234")
    me = m.get("/api/me").get_json()
    assert me["role_name"] == "Matriz (supervisor)" and me["can_switch_branch"]
    # da de alta productos y sube inventario directo a González Gallo
    p = m.post("/api/products", json={"name": "Cargador 20W", "category_id": 4, "cost": 90, "price": 199}).get_json()
    assert m.post("/api/branch/select", json={"branch_id": 3}).status_code == 200
    assert m.post("/api/inventory/adjust", json={"product_id": p["id"], "kind": "entrada", "qty": 8}).status_code == 200
    assert m.post("/api/inventory/transfer", json={"product_id": p["id"], "to_branch_id": 2, "qty": 3}).status_code == 200
    stock = {b["name"]: b["stock"] for b in m.get(f"/api/products/{p['id']}").get_json()["stock_by_branch"]}
    assert stock == {"Matriz": 0, "J. Jesús Reynoso": 3, "González Gallo": 5}
    # ve ventas y cortes de todas las sucursales
    caja = login(app, "caja", "1234")
    caja.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 1}], "payment_method": "tarjeta", "print": False})
    assert m.get("/api/reports/summary?branch=all").get_json()["sales_count"] == 1
    # no configura, no administra usuarios, no cancela, no cambia precios masivos, no borra productos
    assert m.put("/api/settings", json={"store_name": "x"}).status_code == 403
    assert m.get("/api/users").status_code == 403
    assert m.post("/api/sales/1/cancel", json={}).status_code == 403
    assert m.post("/api/pricing/bulk", json={"value": 10}).status_code == 403
    assert m.delete(f"/api/products/{p['id']}").status_code == 403
    # el encargado de matriz no vende, ni siquiera en una sucursal
    r = m.post("/api/sales", json={"items": [{"product_id": p["id"], "qty": 1}], "payment_method": "tarjeta"})
    assert r.status_code == 403
    assert all(u["role"] != "matriz" for u in m.get("/api/sellers").get_json())
    # el cajero no puede cambiar de sucursal ni dar de alta productos
    assert caja.post("/api/branch/select", json={"branch_id": 1}).status_code == 403
    assert caja.post("/api/products", json={"name": "x"}).status_code == 403


def test_branch_labels_its_own_inventory(app, client):
    """Ejemplo: la Matriz entrega 8 Samsung A07 a González Gallo y ellos imprimen sus etiquetas."""
    client.post("/api/users", json={"username": "cajagg", "full_name": "Caja GG", "role": "cajero", "password": "1234", "branch_id": 3})
    client.post("/api/branch/select", json={"branch_id": 1})  # Matriz
    imeis = [f"3500000000000{n:02d}" for n in range(8)]
    a07 = _product(client, name="Samsung Galaxy A07 4GB/128GB Verde", brand="Samsung", model="Galaxy A07", category_id=1,
                   price=2899, serialized=1, initial_stock=0, imeis="\n".join(imeis))
    funda = _product(client, name="Funda A07", initial_stock=10)
    otra = _product(client, name="Mica sin existencia en GG", initial_stock=4)
    assert client.post("/api/inventory/transfer", json={"product_id": a07["id"], "to_branch_id": 3, "imeis": "\n".join(imeis)}).status_code == 200
    assert client.post("/api/inventory/transfer", json={"product_id": funda["id"], "to_branch_id": 3, "qty": 5}).status_code == 200
    gg = login(app, "cajagg", "1234")
    incoming = {r["name"]: r for r in gg.get("/api/inventory/incoming").get_json()}
    assert incoming["Samsung Galaxy A07 4GB/128GB Verde"]["imeis"] == imeis
    assert incoming["Funda A07"]["pending"] == 5 and incoming["Funda A07"]["reference"] == "← Matriz"
    # imprime las 8 etiquetas (una por IMEI) en la Zebra de González Gallo (por su agente)
    r = gg.post("/api/labels/zpl", json={"template": "celular_50x38", "items": [{"product_id": a07["id"], "all_imeis": True}],
                                         "print": True})
    assert r.status_code == 200 and r.get_json()["count"] == 8 and "González Gallo" in r.get_json()["message"]
    token = [b for b in client.get("/api/branches").get_json() if b["id"] == 3][0]["agent_token"]
    jobs = app.test_client().get(f"/api/agent/jobs?code=GG&token={token}").get_json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["target"] == "label"
    import base64
    zpl = base64.b64decode(jobs[0]["data"]).decode()
    assert zpl.count("^XA") == 8 and all(f"IMEI: {i}" in zpl for i in imeis)
    # solo lo que hay en su inventario
    assert gg.post("/api/labels/zpl", json={"items": [{"product_id": funda["id"], "qty": 5}]}).status_code == 200
    r = gg.post("/api/labels/zpl", json={"items": [{"product_id": otra["id"], "qty": 1}]})
    assert r.status_code == 400 and "no tiene existencia" in r.get_json()["error"]
    assert gg.post("/api/labels/zpl", json={"items": [{"product_id": a07["id"], "imei": "359999999999999"}]}).status_code == 400
    # un equipo vendido ya no aparece para etiquetar
    gg.post("/api/sales", json={"items": [{"product_id": a07["id"], "qty": 1, "imei": imeis[0]}], "payment_method": "tarjeta", "print": False})
    again = {r["name"]: r for r in gg.get("/api/inventory/incoming").get_json()}
    assert again["Samsung Galaxy A07 4GB/128GB Verde"]["pending"] == 7


def test_politicas_de_garantia_en_la_nota(client):
    mica = _product(client, name="Mica Hidrogel Matte", category_id=3, cost=40, price=259, track_stock=0,
                    warranty_days=180, warranty_changes=1, ask_device=1)
    sale = client.post("/api/sales", json={"items": [{"product_id": mica["id"], "qty": 1}], "payment_method": "efectivo",
                                           "received": 300, "customer_name": "Jesús", "customer_phone": "3781852433",
                                           "device_model": "Samsung S24", "device_imei": "357425227138540",
                                           "print": False}).get_json()["sale"]
    txt = " ".join(client.get(f"/tickets/{sale['id']}?format=txt").get_data(as_text=True).split())
    for frag in ("POLÍTICAS DE GARANTÍA:", "NO APLICA GARANTÍA SIN NOTA, HOLOGRAMA Y EMPAQUE",
                 "ESTA GARANTÍA NO SERÁ VÁLIDA BAJO LAS SIGUIENTES CONDICIONES", "6. No aplica garantía si no presenta su nota de compra.",
                 "9. En baterías", "Acepto y estoy consciente de las políticas de garantía.", "Firma del cliente",
                 "Cliente: Jesús", "TOTAL $259.00"):  # el formato de la nota sigue igual
        assert frag in txt, frag
    assert "Garantía: 6 meses" in txt
    # todas las notas llevan las políticas; un producto sin garantía lo dice en su renglón
    aro = _product(client, name="Aro MagSafe", category_id=12, price=49, track_stock=0, warranty_days=0)
    s2 = client.post("/api/sales", json={"items": [{"product_id": aro["id"], "qty": 1}], "payment_method": "tarjeta",
                                         "print": False}).get_json()["sale"]
    t2 = client.get(f"/tickets/{s2['id']}?format=txt").get_data(as_text=True)
    assert "Sin garantía" in t2 and "ESTA GARANTÍA NO SERÁ VÁLIDA" in t2 and "Firma del cliente" in t2
    # se puede desactivar
    client.put("/api/settings", json={"warranty_policy_print": "nunca"})
    t3 = client.get(f"/tickets/{s2['id']}?format=txt").get_data(as_text=True)
    assert "Firma del cliente" not in t3 and "POLÍTICAS DE GARANTÍA" not in t3
