"""Servidor HTTP local que sirve una carpeta de HTML estático. Lo usan la demo y las pruebas."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)

SITIO_DEMO = Path(__file__).resolve().parent.parent / "tests" / "sitio_demo"


class _Manejador(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8",
                      ".txt": "text/plain; charset=utf-8"}

    def log_message(self, formato, *args):  # silencia el log por consola; queda en DEBUG
        log.debug("servidor local: " + formato, *args)


@contextmanager
def servir_carpeta(carpeta: str | Path = SITIO_DEMO, puerto: int = 0) -> Iterator[str]:
    """Levanta un servidor en 127.0.0.1 (puerto libre si puerto=0) y devuelve la URL base con '/'."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe la carpeta a servir: {carpeta}")
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), partial(_Manejador, directory=str(carpeta)))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}/"
    log.debug("Servidor local en %s sirviendo %s", base, carpeta)
    try:
        yield base
    finally:
        servidor.shutdown()
        servidor.server_close()


def cambiar_base(url: str, base: str) -> str:
    """Reemplaza esquema y host de `url` por los de `base` (mantiene ruta y query)."""
    destino, origen = urlsplit(base), urlsplit(url)
    return urlunsplit((destino.scheme, destino.netloc, origen.path, origen.query, origen.fragment))
