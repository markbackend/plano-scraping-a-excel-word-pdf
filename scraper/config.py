"""Carga y valida la definición de un sitio (archivo YAML) y los ajustes generales (variables de entorno).

Precedencia de los ajustes: valores por defecto < variables de entorno < sección `opciones:` del YAML.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

TIPOS_VALIDOS = {"texto", "numero", "precio", "entero", "fecha", "url"}
PAGINACIONES_VALIDAS = {"siguiente", "numero", "ninguna"}


class ErrorConfig(Exception):
    """El archivo YAML o una variable de entorno tiene un valor inválido."""


# --------------------------------------------------------------------------- ajustes generales

def _env_bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _env_num(nombre: str, defecto: float, tipo=float):
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    try:
        return tipo(valor.strip())
    except ValueError as exc:
        raise ErrorConfig(f"La variable {nombre}={valor!r} debe ser un número") from exc


@dataclass
class Ajustes:
    user_agent: str = "MarkScraper/1.0 (+https://github.com/markbackend)"
    demora_segundos: float = 1.0        # pausa mínima entre pedidos al sitio
    reintentos: int = 3                 # reintentos ante errores de red, 429 o 5xx
    espera_reintento: float = 2.0       # espera base (se duplica en cada intento)
    timeout_segundos: float = 20.0
    respetar_robots: bool = True
    cache_dir: str = ".cache"
    cache_horas: float = 24.0           # 0 = sin caché
    salida_dir: str = "salidas"
    max_paginas: int = 50
    csv_separador: str = ";"
    csv_decimal: str = ","
    log_nivel: str = "INFO"

    @classmethod
    def desde_entorno(cls, sobrescribir: dict[str, Any] | None = None) -> "Ajustes":
        a = cls()
        a.user_agent = os.getenv("SCRAPER_USER_AGENT") or a.user_agent
        a.demora_segundos = _env_num("SCRAPER_DEMORA_SEGUNDOS", a.demora_segundos)
        a.reintentos = _env_num("SCRAPER_REINTENTOS", a.reintentos, int)
        a.espera_reintento = _env_num("SCRAPER_ESPERA_REINTENTO", a.espera_reintento)
        a.timeout_segundos = _env_num("SCRAPER_TIMEOUT_SEGUNDOS", a.timeout_segundos)
        a.respetar_robots = _env_bool("SCRAPER_RESPETAR_ROBOTS", a.respetar_robots)
        a.cache_dir = os.getenv("SCRAPER_CACHE_DIR") or a.cache_dir
        a.cache_horas = _env_num("SCRAPER_CACHE_HORAS", a.cache_horas)
        a.salida_dir = os.getenv("SCRAPER_SALIDA_DIR") or a.salida_dir
        a.max_paginas = _env_num("SCRAPER_MAX_PAGINAS", a.max_paginas, int)
        a.csv_separador = os.getenv("SCRAPER_CSV_SEPARADOR") or a.csv_separador
        a.csv_decimal = os.getenv("SCRAPER_CSV_DECIMAL") or a.csv_decimal
        a.log_nivel = (os.getenv("SCRAPER_LOG_NIVEL") or a.log_nivel).upper()
        if sobrescribir:
            a.aplicar(sobrescribir)
        return a

    def aplicar(self, valores: dict[str, Any]) -> None:
        """Aplica la sección `opciones:` del YAML, validando nombres y tipos."""
        validos = {f.name: f for f in fields(self)}
        for clave, valor in valores.items():
            if clave not in validos:
                raise ErrorConfig(f"Opción desconocida en 'opciones': {clave!r}. Válidas: {', '.join(validos)}")
            actual = getattr(self, clave)
            try:
                if isinstance(actual, bool):
                    valor = valor if isinstance(valor, bool) else str(valor).lower() in {"1", "true", "si", "sí"}
                elif isinstance(actual, int):
                    valor = int(valor)
                elif isinstance(actual, float):
                    valor = float(valor)
                else:
                    valor = str(valor)
            except (TypeError, ValueError) as exc:
                raise ErrorConfig(f"La opción {clave!r} tiene un valor inválido: {valor!r}") from exc
            setattr(self, clave, valor)
        if not self.respetar_robots:
            log.warning("robots.txt DESACTIVADO: usar solo con permiso escrito del dueño del sitio")


# --------------------------------------------------------------------------- definición del sitio

@dataclass
class Campo:
    nombre: str
    selector: str | None = None      # None = el propio elemento de la lista (o la página en el detalle)
    atributo: str = "texto"          # "texto", "html" o un atributo HTML: href, src, data-id...
    tipo: str = "texto"              # texto | numero | precio | entero | fecha | url
    regex: str | None = None         # si tiene grupo, se usa el grupo 1
    formato_fecha: list[str] = field(default_factory=list)
    requerido: bool = False          # si falta, el registro se descarta
    por_defecto: Any = None
    todos: bool = False              # junta todos los elementos que coinciden, separados por " | "
    exportar: bool = True            # False = se usa internamente (p. ej. el enlace) pero no sale en el archivo


@dataclass
class Paginacion:
    tipo: str = "ninguna"            # siguiente | numero | ninguna
    selector: str | None = None      # para "siguiente": enlace a la próxima página
    plantilla: str | None = None     # para "numero": "pagina-{n}.html" o "?page={n}" (relativa a url_inicial)
    desde: int = 1
    hasta: int | None = None
    max_paginas: int | None = None


@dataclass
class Detalle:
    enlace: str                      # nombre del campo de la lista que tiene la URL del detalle
    campos: list[Campo]


@dataclass
class Sitio:
    nombre: str
    url_inicial: str
    selector_lista: str
    campos: list[Campo]
    paginacion: Paginacion = field(default_factory=Paginacion)
    detalle: Detalle | None = None
    deduplicar_por: list[str] = field(default_factory=list)
    max_registros: int = 0           # 0 = sin límite
    decimal: str = ","               # separador decimal del sitio ("," en Argentina, "." en sitios en inglés)
    javascript: bool = False         # True = renderiza con Playwright (instalar requirements-js.txt)
    esperar_selector: str | None = None
    opciones: dict[str, Any] = field(default_factory=dict)
    nombre_archivo: str = "resultado"
    titulo_informe: str | None = None
    archivo: Path | None = None

    def todos_los_campos(self) -> list[Campo]:
        return self.campos + (self.detalle.campos if self.detalle else [])

    def columnas(self) -> list[str]:
        return [c.nombre for c in self.todos_los_campos() if c.exportar]

    def tipos(self) -> dict[str, str]:
        return {c.nombre: c.tipo for c in self.todos_los_campos()}


def _leer_campos(datos: Any, donde: str) -> list[Campo]:
    if not isinstance(datos, dict) or not datos:
        raise ErrorConfig(f"'{donde}' debe ser un diccionario con al menos un campo")
    campos = []
    for nombre, definicion in datos.items():
        if isinstance(definicion, str) or definicion is None:
            definicion = {"selector": definicion}
        if not isinstance(definicion, dict):
            raise ErrorConfig(f"El campo {donde}.{nombre} debe ser un selector o un diccionario")
        desconocidas = set(definicion) - {f.name for f in fields(Campo)}
        if desconocidas:
            raise ErrorConfig(f"El campo {donde}.{nombre} tiene claves desconocidas: {sorted(desconocidas)}")
        formatos = definicion.get("formato_fecha") or []
        if isinstance(formatos, str):
            formatos = [formatos]
        campo = Campo(nombre=str(nombre), **{**definicion, "formato_fecha": list(formatos)})
        if campo.tipo not in TIPOS_VALIDOS:
            raise ErrorConfig(f"El campo {donde}.{nombre} tiene tipo {campo.tipo!r}; válidos: {sorted(TIPOS_VALIDOS)}")
        campos.append(campo)
    return campos


def cargar_sitio(ruta: str | Path) -> Sitio:
    """Lee un YAML de sitio y devuelve un `Sitio` validado. Lanza ErrorConfig con un mensaje claro."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorConfig(f"No existe el archivo de sitio: {ruta}")
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ErrorConfig(f"YAML inválido en {ruta}: {exc}") from exc
    if not isinstance(datos, dict):
        raise ErrorConfig(f"{ruta} debe contener un diccionario YAML")
    return sitio_desde_dict(datos, ruta)


def sitio_desde_dict(datos: dict[str, Any], ruta: Path | None = None) -> Sitio:
    for clave in ("url_inicial", "lista", "campos"):
        if clave not in datos:
            raise ErrorConfig(f"Falta la clave obligatoria '{clave}'")
    url = str(datos["url_inicial"])
    if not url.startswith(("http://", "https://")):
        raise ErrorConfig(f"url_inicial debe empezar con http:// o https:// (es {url!r})")

    lista = datos["lista"]
    selector_lista = lista.get("selector") if isinstance(lista, dict) else lista
    if not selector_lista:
        raise ErrorConfig("'lista.selector' es obligatorio (selector CSS de cada elemento de la lista)")

    campos = _leer_campos(datos["campos"], "campos")

    pag_datos = datos.get("paginacion") or {}
    desconocidas = set(pag_datos) - {f.name for f in fields(Paginacion)}
    if desconocidas:
        raise ErrorConfig(f"'paginacion' tiene claves desconocidas: {sorted(desconocidas)}")
    paginacion = Paginacion(**pag_datos)
    if paginacion.tipo not in PAGINACIONES_VALIDAS:
        raise ErrorConfig(f"paginacion.tipo debe ser uno de {sorted(PAGINACIONES_VALIDAS)}")
    if paginacion.tipo == "siguiente" and not paginacion.selector:
        raise ErrorConfig("paginacion.tipo 'siguiente' necesita 'selector' (el enlace a la próxima página)")
    if paginacion.tipo == "numero":
        if not paginacion.plantilla or "{n}" not in paginacion.plantilla:
            raise ErrorConfig("paginacion.tipo 'numero' necesita 'plantilla' con {n}, p. ej. 'pagina-{n}.html'")

    detalle = None
    if datos.get("detalle"):
        det = datos["detalle"]
        if not isinstance(det, dict) or "enlace" not in det:
            raise ErrorConfig("'detalle' necesita 'enlace' (nombre del campo con la URL) y 'campos'")
        if det["enlace"] not in {c.nombre for c in campos}:
            raise ErrorConfig(f"detalle.enlace={det['enlace']!r} no es un campo de la lista")
        detalle = Detalle(enlace=det["enlace"], campos=_leer_campos(det.get("campos"), "detalle.campos"))

    nombres = [c.nombre for c in campos] + ([c.nombre for c in detalle.campos] if detalle else [])
    repetidos = {n for n in nombres if nombres.count(n) > 1}
    if repetidos:
        raise ErrorConfig(f"Nombres de campo repetidos: {sorted(repetidos)}")

    dedup = datos.get("deduplicar_por") or []
    if isinstance(dedup, str):
        dedup = [dedup]
    faltan = set(dedup) - {c.nombre for c in campos}
    if faltan:
        raise ErrorConfig(f"deduplicar_por debe usar campos de la lista (no del detalle): {sorted(faltan)}")

    decimal = str(datos.get("decimal", ","))
    if decimal not in {",", "."}:
        raise ErrorConfig("'decimal' debe ser ',' o '.'")

    opciones = datos.get("opciones") or {}
    Ajustes().aplicar(dict(opciones))  # valida nombres y tipos ahora, no a mitad de la corrida

    salida = datos.get("salida") or {}
    return Sitio(
        nombre=str(datos.get("nombre") or (ruta.stem if ruta else "sitio")),
        url_inicial=url,
        selector_lista=selector_lista,
        campos=campos,
        paginacion=paginacion,
        detalle=detalle,
        deduplicar_por=list(dedup),
        max_registros=int(datos.get("max_registros") or 0),
        decimal=decimal,
        javascript=bool(datos.get("javascript", False)),
        esperar_selector=datos.get("esperar_selector"),
        opciones=dict(opciones),
        nombre_archivo=str(salida.get("nombre_archivo") or (ruta.stem if ruta else "resultado")),
        titulo_informe=salida.get("titulo_informe"),
        archivo=ruta,
    )
