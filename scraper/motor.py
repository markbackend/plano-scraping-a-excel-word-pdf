"""Orquesta la corrida: recorre páginas, extrae registros, quita duplicados y entra al detalle."""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .cliente import BloqueadoPorRobots, ClienteWeb, ErrorDescarga
from .config import Ajustes, Sitio
from .extractor import extraer_detalle, extraer_items, url_numero, url_siguiente

log = logging.getLogger(__name__)


@dataclass
class Resultado:
    sitio: Sitio
    registros: list[dict[str, Any]]
    columnas: list[str]
    tipos: dict[str, str]
    estadisticas: Counter
    errores: list[str] = field(default_factory=list)
    inicio: datetime = field(default_factory=datetime.now)
    fin: datetime | None = None

    @property
    def titulo(self) -> str:
        return self.sitio.titulo_informe or f"Datos extraídos de {self.sitio.nombre}"

    def resumen(self) -> str:
        e = self.estadisticas
        return (f"{len(self.registros)} registros | {e['paginas']} páginas | {e['duplicados']} duplicados | "
                f"{e['descartados']} descartados | {e['pedidos_red']} pedidos ({e['desde_cache']} desde caché) | "
                f"{e['bloqueados_robots']} bloqueados por robots.txt | {len(self.errores)} errores")


class Scraper:
    def __init__(self, sitio: Sitio, ajustes: Ajustes, cliente: ClienteWeb | None = None):
        self.sitio = sitio
        self.ajustes = ajustes
        self.cliente = cliente or ClienteWeb(ajustes)
        self._propio = cliente is None

    def correr(self) -> Resultado:
        sitio = self.sitio
        resultado = Resultado(sitio, [], sitio.columnas(), sitio.tipos(), Counter())
        vistos: set[tuple] = set()
        log.info("Inicio: %s (%s)", sitio.nombre, sitio.url_inicial)
        try:
            for url, html in self._paginas(resultado):
                registros, descartados = extraer_items(html, url, sitio)
                resultado.estadisticas["descartados"] += descartados
                if not registros and sitio.paginacion.tipo == "numero":
                    log.info("Página sin elementos (%s): fin de la paginación", url)
                    break
                for registro in registros:
                    clave = self._clave(registro)
                    if clave in vistos:
                        resultado.estadisticas["duplicados"] += 1
                        continue
                    vistos.add(clave)
                    if sitio.detalle:
                        registro.update(self._detalle(registro, resultado))
                    resultado.registros.append({c: registro.get(c) for c in resultado.columnas})
                    if sitio.max_registros and len(resultado.registros) >= sitio.max_registros:
                        log.info("Se alcanzó max_registros=%d", sitio.max_registros)
                        return resultado
            return resultado
        finally:
            resultado.estadisticas.update(self.cliente.estadisticas)
            resultado.fin = datetime.now()
            if self._propio:
                self.cliente.cerrar()
            log.info("Fin: %s", resultado.resumen())

    # ------------------------------------------------------------------ internos

    def _obtener(self, url: str) -> str:
        return self.cliente.obtener(url, self.sitio.javascript, self.sitio.esperar_selector).texto

    def _paginas(self, resultado: Resultado):
        """Genera (url, html) de cada página de la lista según el tipo de paginación.
        Un error en la primera página corta la corrida; en las siguientes, se registra y se termina."""
        sitio = self.sitio
        pag = sitio.paginacion
        maximo = pag.max_paginas or self.ajustes.max_paginas

        if pag.tipo == "numero":
            n = pag.desde
            while (pag.hasta is None or n <= pag.hasta) and resultado.estadisticas["paginas"] < maximo:
                url = url_numero(sitio, n)
                html = self._pagina(url, resultado, primera=(n == pag.desde))
                if html is None:
                    return
                yield url, html
                n += 1
            return

        url: str | None = sitio.url_inicial
        visitadas: set[str] = set()
        while url and resultado.estadisticas["paginas"] < maximo:
            if url in visitadas:
                log.warning("La paginación vuelve a una página ya visitada (%s): se corta", url)
                return
            visitadas.add(url)
            html = self._pagina(url, resultado, primera=(len(visitadas) == 1))
            if html is None:
                return
            yield url, html
            url = url_siguiente(html, url, pag) if pag.tipo == "siguiente" else None
        if url and resultado.estadisticas["paginas"] >= maximo:
            log.info("Se alcanzó el máximo de %d páginas", maximo)

    def _pagina(self, url: str, resultado: Resultado, primera: bool) -> str | None:
        try:
            html = self._obtener(url)
        except ErrorDescarga as exc:
            if primera:
                raise
            if exc.estado == 404:
                log.info("No hay más páginas (%s devolvió 404)", url)
            else:
                log.error("No se pudo leer la página %s: %s", url, exc.motivo)
                resultado.errores.append(f"Página {url}: {exc.motivo}")
            return None
        resultado.estadisticas["paginas"] += 1
        return html

    def _detalle(self, registro: dict[str, Any], resultado: Resultado) -> dict[str, Any]:
        detalle = self.sitio.detalle
        vacio = {c.nombre: c.por_defecto for c in detalle.campos}
        url = registro.get(detalle.enlace)
        if not url:
            return vacio
        try:
            html = self._obtener(url)
        except BloqueadoPorRobots:
            log.warning("Detalle bloqueado por robots.txt: %s", url)
            resultado.errores.append(f"Detalle {url}: bloqueado por robots.txt")
            return vacio
        except ErrorDescarga as exc:
            log.error("No se pudo leer el detalle %s: %s", url, exc.motivo)
            resultado.errores.append(f"Detalle {url}: {exc.motivo}")
            return vacio
        resultado.estadisticas["detalles"] += 1
        return extraer_detalle(html, url, self.sitio)

    def _clave(self, registro: dict[str, Any]) -> tuple:
        campos = self.sitio.deduplicar_por or [c.nombre for c in self.sitio.campos]
        return tuple(str(registro.get(c)) for c in campos)
