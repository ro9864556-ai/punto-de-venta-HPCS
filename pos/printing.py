"""Envío de datos crudos (ZPL / ESC-POS) a impresoras.

Modos:
  * network : impresora en red (Zebra / térmica) por TCP, normalmente puerto 9100.
  * local   : impresora instalada en el sistema (USB). En Windows usa pywin32;
              en Linux/macOS usa `lp -o raw` (CUPS).
"""
import os
import platform
import socket
import subprocess
import tempfile


class PrintError(Exception):
    pass


def send_network(data: bytes, host: str, port: int = 9100, timeout: float = 6.0):
    if not host:
        raise PrintError("Falta la dirección IP de la impresora (Configuración).")
    try:
        with socket.create_connection((host, int(port or 9100)), timeout=timeout) as sock:
            sock.sendall(data)
    except OSError as exc:
        raise PrintError(f"No se pudo conectar con la impresora {host}:{port} — {exc}") from exc


def send_local(data: bytes, printer_name: str, job_name="Punto de venta"):
    if not printer_name:
        raise PrintError("Falta el nombre de la impresora instalada (Configuración).")
    if platform.system() == "Windows":
        try:
            import win32print  # type: ignore
        except ImportError as exc:
            raise PrintError("Para imprimir por USB en Windows instala pywin32:  pip install pywin32") from exc
        try:
            handle = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(handle, 1, (job_name, None, "RAW"))
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, data)
                win32print.EndPagePrinter(handle)
                win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
        except Exception as exc:  # noqa: BLE001
            raise PrintError(f"Error de Windows al imprimir en '{printer_name}': {exc}") from exc
        return
    fd, path = tempfile.mkstemp(suffix=".raw")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        result = subprocess.run(["lp", "-d", printer_name, "-o", "raw", "-t", job_name, path],
                                capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise PrintError(f"CUPS rechazó el trabajo: {result.stderr.strip() or result.stdout.strip()}")
    except FileNotFoundError as exc:
        raise PrintError("No se encontró el comando 'lp' (CUPS) en este equipo.") from exc
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def send(data, mode, host="", port=9100, name=""):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if mode == "network":
        send_network(data, host, port)
    elif mode == "local":
        send_local(data, name)
    else:
        raise PrintError(f"Modo de impresión no soportado: {mode}")


def list_printers():
    if platform.system() == "Windows":
        try:
            import win32print  # type: ignore
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return [p[2] for p in win32print.EnumPrinters(flags)]
        except Exception:  # noqa: BLE001
            return []
    try:
        result = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:  # noqa: BLE001
        return []
