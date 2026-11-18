"""Cliente HTTP educado: respeta robots.txt, espera entre pedidos, reintenta con espera creciente
y guarda una caché local en disco. Opcionalmente renderiza JavaScript con Playwright."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from .config import Ajustes
from .robots import VerificadorRobots

log = logging.getLogger(__name__)

ESTADOS_REINTENTABLES = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 60.0


class ErrorDescarga(Exception):
    def __init__(self, url: str, motivo: str, estado: int | None = None):
        super().__init__(f"{motivo} ({url})")
        self.url, self.motivo, self.estado = url, motivo, estado


class BloqueadoPorRobots(ErrorDescarga):
    pass


@dataclass
class Respuesta:
    url: str           # URL final (después de redirecciones)
    estado: int
    texto: str
    desde_cache: bool = False


class CacheLocal:
    """Guarda el HTML de cada URL en un archivo JSON. Vence a las `horas` indicadas."""

    def __init__(self, carpeta: str | Path, horas: float):
        self.carpeta = Path(carpeta)
        self.segundos = horas * 3600

    def _ruta(self, url: str) -> Path:
        return self.carpeta / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def leer(self, url: str) -> Respuesta | None:
        ruta = self._ruta(url)
        if not ruta.is_file():
            return None
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Entrada de caché dañada, se ignora: %s", ruta)
            return None
        if time.time() - datos.get("guardado", 0) > self.segundos:
            return None
        return Respuesta(datos["url_final"], 200, datos["texto"], desde_cache=True)

    def guardar(self, url: str, respuesta: Respuesta) -> None:
        try:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            datos = {"url": url, "url_final": respuesta.url, "guardado": time.time(), "texto": respuesta.texto}
            self._ruta(url).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("No se pudo escribir la caché (%s)", exc)


class ClienteWeb:
    def __init__(self, ajustes: Ajustes, transporte: httpx.BaseTransport | None = None,
                 dormir: Callable[[float], None] = time.sleep, reloj: Callable[[], float] = time.monotonic,
                 usar_cache: bool = True):
        self.ajustes = ajustes
        self._dormir = dormir
        self._reloj = reloj
        self._ultimo_pedido: float | None = None
        self.estadisticas: Counter = Counter()
        self.http = httpx.Client(
            transport=transporte,
            headers={"User-Agent": ajustes.user_agent, "Accept-Language": "es-AR,es;q=0.9,en;q=0.5"},
            timeout=ajustes.timeout_segundos,
            follow_redirects=True,
        )
        self.cache = CacheLocal(ajustes.cache_dir, ajustes.cache_horas) if usar_cache and ajustes.cache_horas > 0 else None
        self.robots = VerificadorRobots(self.pedir_crudo, ajustes.user_agent) if ajustes.respetar_robots else None
        self._navegador = None  # Playwright, se crea solo si hace falta

    # ------------------------------------------------------------------ API pública

    def obtener(self, url: str, javascript: bool = False, esperar_selector: str | None = None) -> Respuesta:
        """Devuelve el HTML de `url` (200). Lanza BloqueadoPorRobots o ErrorDescarga."""
        if self.robots and not self.robots.permitido(url):
            self.estadisticas["bloqueados_robots"] += 1
            raise BloqueadoPorRobots(url, "robots.txt no permite esta URL")

        if self.cache:
            guardada = self.cache.leer(url)
            if guardada:
                self.estadisticas["desde_cache"] += 1
                log.debug("Caché: %s", url)
                return guardada

        if javascript:
            respuesta = self._obtener_con_navegador(url, esperar_selector)
        else:
            http_resp = self.pedir_crudo(url)
            if http_resp.status_code != 200:
                raise ErrorDescarga(url, f"El sitio respondió {http_resp.status_code}", http_resp.status_code)
            respuesta = Respuesta(str(http_resp.url), 200, http_resp.text)

        if self.cache:
            self.cache.guardar(url, respuesta)
        return respuesta

    def pedir_crudo(self, url: str) -> httpx.Response:
        """GET con demora entre pedidos y reintentos. Devuelve la respuesta aunque sea 404 o, si se
        agotaron los reintentos, el último 429/5xx. Lanza ErrorDescarga solo si falla la red."""
        ultimo_error = ""
        for intento in range(self.ajustes.reintentos + 1):
            self._esperar_turno(url)
            espera_sugerida = None
            try:
                self.estadisticas["pedidos_red"] += 1
                log.debug("GET %s (intento %d)", url, intento + 1)
                respuesta = self.http.get(url)
            except httpx.TransportError as exc:
                ultimo_error = f"error de red: {exc.__class__.__name__}: {exc}"
            else:
                if respuesta.status_code not in ESTADOS_REINTENTABLES:
                    return respuesta
                if intento == self.ajustes.reintentos:
                    log.error("%s sigue respondiendo %s después de %d intentos",
                              url, respuesta.status_code, intento + 1)
                    return respuesta
                ultimo_error = f"el sitio respondió {respuesta.status_code}"
                espera_sugerida = _leer_retry_after(respuesta)
            if intento < self.ajustes.reintentos:
                espera = espera_sugerida if espera_sugerida is not None else self.ajustes.espera_reintento * 2 ** intento
                self.estadisticas["reintentos"] += 1
                log.warning("%s en %s; reintento %d/%d en %.1f s",
                            ultimo_error, url, intento + 1, self.ajustes.reintentos, espera)
                self._dormir(espera)
        raise ErrorDescarga(url, f"Falló después de {self.ajustes.reintentos + 1} intentos: {ultimo_error}")

    def cerrar(self) -> None:
        self.http.close()
        if self._navegador:
            self._navegador.cerrar()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()

    # ------------------------------------------------------------------ internos

    def _esperar_turno(self, url: str) -> None:
        demora = self.ajustes.demora_segundos
        if self.robots:
            crawl_delay = self.robots.crawl_delay(url)
            if crawl_delay:
                demora = max(demora, crawl_delay)
        if self._ultimo_pedido is not None and demora > 0:
            falta = demora - (self._reloj() - self._ultimo_pedido)
            if falta > 0:
                self._dormir(falta)
        self._ultimo_pedido = self._reloj()

    def _obtener_con_navegador(self, url: str, esperar_selector: str | None) -> Respuesta:
        if self._navegador is None:
            self._navegador = NavegadorJS(self.ajustes)
        self._esperar_turno(url)
        self.estadisticas["pedidos_red"] += 1
        return self._navegador.obtener(url, esperar_selector)


def _leer_retry_after(respuesta: httpx.Response) -> float | None:
    valor = respuesta.headers.get("Retry-After")
    if not valor:
        return None
    try:
        return min(float(valor), MAX_RETRY_AFTER)
    except ValueError:
        return None  # formato fecha HTTP: se usa la espera exponencial


class NavegadorJS:
    """Renderiza páginas con JavaScript usando Playwright (opcional: requirements-js.txt)."""

    def __init__(self, ajustes: Ajustes):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ErrorDescarga("", "El sitio usa 'javascript: true' pero Playwright no está instalado. "
                                    "Instalar con: pip install -r requirements-js.txt && "
                                    "python -m playwright install chromium") from exc
        self.ajustes = ajustes
        self._pw = sync_playwright().start()
        self._navegador = self._pw.chromium.launch()
        self._pagina = self._navegador.new_page(user_agent=ajustes.user_agent)

    def obtener(self, url: str, esperar_selector: str | None) -> Respuesta:
        try:
            respuesta = self._pagina.goto(url, timeout=self.ajustes.timeout_segundos * 1000, wait_until="networkidle")
            if esperar_selector:
                self._pagina.wait_for_selector(esperar_selector, timeout=self.ajustes.timeout_segundos * 1000)
        except Exception as exc:  # noqa: BLE001 - Playwright tiene sus propias excepciones
            raise ErrorDescarga(url, f"Playwright no pudo cargar la página: {exc}") from exc
        estado = respuesta.status if respuesta else 200
        if estado != 200:
            raise ErrorDescarga(url, f"El sitio respondió {estado}", estado)
        return Respuesta(self._pagina.url, estado, self._pagina.content())

    def cerrar(self) -> None:
        self._navegador.close()
        self._pw.stop()
