"""Agente de impresión para una sucursal.

Corre en la computadora de la sucursal (la que tiene conectadas la impresora de
tickets y la Zebra por USB). Cada 2 segundos pregunta al servidor central si hay
tickets o etiquetas para esta sucursal y los manda a la impresora local.

Uso:
    python agente.py                 (lee agente.json de esta carpeta)
    python agente.py otra_config.json

El archivo agente.json se descarga desde el sistema:
Configuración → Sucursales → "Descargar agente.json".
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pos import printing  # noqa: E402

INTERVALO = 2  # segundos entre consultas


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def cargar_config(path):
    if not os.path.exists(path):
        log(f"No encontré {path}.")
        log("Descárgalo desde el sistema: Configuración → Sucursales → Descargar agente.json,")
        log("y guárdalo en esta misma carpeta.")
        sys.exit(1)
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    for key in ("servidor", "sucursal", "token"):
        if not cfg.get(key):
            log(f"Falta '{key}' en {path}")
            sys.exit(1)
    cfg["servidor"] = cfg["servidor"].rstrip("/")
    return cfg


def pedir(cfg, method, path, data=None):
    params = urllib.parse.urlencode({"code": cfg["sucursal"], "token": cfg["token"]})
    url = f"{cfg['servidor']}{path}?{params}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "{}")


def imprimir(cfg, job):
    destino = cfg.get("impresora_etiquetas" if job["target"] == "label" else "impresora_tickets") or {}
    modo = destino.get("modo", "local")
    printing.send(base64.b64decode(job["data"]), modo, destino.get("host", ""), destino.get("puerto", 9100),
                  destino.get("nombre", ""))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "agente.json")
    cfg = cargar_config(path)
    log(f"Agente de impresión · sucursal {cfg['sucursal']} · servidor {cfg['servidor']}")
    log(f"Tickets   → {cfg.get('impresora_tickets', {}).get('nombre') or cfg.get('impresora_tickets', {}).get('host')}")
    log(f"Etiquetas → {cfg.get('impresora_etiquetas', {}).get('nombre') or cfg.get('impresora_etiquetas', {}).get('host')}")
    log("Deja esta ventana abierta. Para cerrar presiona Ctrl+C.")
    conectado = None
    while True:
        try:
            resp = pedir(cfg, "GET", "/api/agent/jobs")
            if conectado is not True:
                log(f"Conectado al servidor ({resp.get('branch', '')}).")
                conectado = True
            for job in resp.get("jobs", []):
                try:
                    imprimir(cfg, job)
                    pedir(cfg, "POST", f"/api/agent/jobs/{job['id']}/done", {"ok": True})
                    log(f"Impreso: {job.get('title') or job['target']}")
                except printing.PrintError as exc:
                    pedir(cfg, "POST", f"/api/agent/jobs/{job['id']}/done", {"ok": False, "error": str(exc)})
                    log(f"ERROR al imprimir {job.get('title')}: {exc}")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                log("El servidor rechazó la clave del agente. Descarga de nuevo agente.json.")
                time.sleep(30)
            else:
                log(f"Error del servidor: {exc}")
            conectado = False
        except (urllib.error.URLError, OSError) as exc:
            if conectado is not False:
                log(f"Sin conexión con el servidor ({exc}). Reintentando…")
            conectado = False
        time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Agente detenido.")
