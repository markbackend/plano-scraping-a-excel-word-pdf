"""Lectura de robots.txt: decide si una URL se puede pedir y muestra qué reglas aplican a nuestro User-Agent."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

if TYPE_CHECKING:  # evita import circular
    import httpx

log = logging.getLogger(__name__)


@dataclass
class InfoRobots:
    url: str
    estado: str                                  # "ok", "no_existe", "prohibido", "error"
    texto: str = ""
    reglas: list[tuple[str, str]] = field(default_factory=list)  # [("Disallow", "/privado/"), ...]
    crawl_delay: float | None = None
    parser: RobotFileParser | None = None


def raiz(url: str) -> str:
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc}"


def reglas_para(texto: str, user_agent: str) -> list[tuple[str, str]]:
    """Devuelve las líneas Allow/Disallow de los grupos que aplican a `user_agent`
    (los grupos con su nombre; si no hay ninguno, los de '*')."""
    token = user_agent.split("/")[0].lower()
    grupos: list[tuple[list[str], list[tuple[str, str]]]] = []
    agentes: list[str] = []
    reglas: list[tuple[str, str]] = []
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0].strip()
        if ":" not in linea:
            continue
        clave, valor = (p.strip() for p in linea.split(":", 1))
        clave = clave.lower()
        if clave == "user-agent":
            if reglas:  # empieza un grupo nuevo
                grupos.append((agentes, reglas))
                agentes, reglas = [], []
            agentes.append(valor.lower())
        elif clave in ("allow", "disallow") and agentes:
            reglas.append((clave.capitalize(), valor))
    if agentes:
        grupos.append((agentes, reglas))

    propios = [r for ags, rs in grupos if any(a != "*" and a in token for a in ags) for r in rs]
    if propios:
        return propios
    return [r for ags, rs in grupos if "*" in ags for r in rs]


class VerificadorRobots:
    """Descarga robots.txt una vez por dominio y responde `permitido(url)`.

    `pedir` es una función url -> httpx.Response (la del ClienteWeb, con demora y reintentos)."""

    def __init__(self, pedir: Callable[[str], "httpx.Response"], user_agent: str):
        self._pedir = pedir
        self.user_agent = user_agent
        self._cache: dict[str, InfoRobots] = {}

    def info(self, url: str) -> InfoRobots:
        base = raiz(url)
        if base in self._cache:
            return self._cache[base]
        url_robots = f"{base}/robots.txt"
        parser = RobotFileParser(url_robots)
        try:
            respuesta = self._pedir(url_robots)
        except Exception as exc:  # noqa: BLE001 - cualquier falla de red: se permite, avisando
            log.warning("No se pudo leer %s (%s): se asume que no hay restricciones", url_robots, exc)
            parser.allow_all = True
            info = InfoRobots(url_robots, "error", parser=parser)
        else:
            if respuesta.status_code in (401, 403):
                parser.disallow_all = True
                info = InfoRobots(url_robots, "prohibido", parser=parser)
                log.warning("%s respondió %s: se considera TODO bloqueado", url_robots, respuesta.status_code)
            elif 400 <= respuesta.status_code < 500:
                parser.allow_all = True
                info = InfoRobots(url_robots, "no_existe", parser=parser)
                log.info("%s no existe (%s): sin restricciones", url_robots, respuesta.status_code)
            elif respuesta.status_code >= 500:
                parser.disallow_all = True
                info = InfoRobots(url_robots, "error", parser=parser)
                log.warning("%s respondió %s: por precaución se considera TODO bloqueado",
                            url_robots, respuesta.status_code)
            else:
                texto = respuesta.text
                parser.parse(texto.splitlines())
                demora = parser.crawl_delay(self.user_agent)
                info = InfoRobots(url_robots, "ok", texto=texto, reglas=reglas_para(texto, self.user_agent),
                                  crawl_delay=float(demora) if demora is not None else None, parser=parser)
                log.info("robots.txt leído: %d reglas aplican a nuestro User-Agent", len(info.reglas))
        self._cache[base] = info
        return info

    def permitido(self, url: str) -> bool:
        info = self.info(url)
        return info.parser.can_fetch(self.user_agent, url) if info.parser else True

    def crawl_delay(self, url: str) -> float | None:
        base = raiz(url)
        return self._cache[base].crawl_delay if base in self._cache else None
