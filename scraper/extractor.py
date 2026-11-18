"""Extrae campos de un HTML usando los selectores CSS definidos en el YAML del sitio."""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import Campo, Paginacion, Sitio
from .limpieza import convertir, limpiar_texto

log = logging.getLogger(__name__)


def sopa(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _texto_crudo(elemento: Tag, atributo: str) -> str | None:
    if atributo == "texto":
        return elemento.get_text(" ", strip=True)
    if atributo == "html":
        return str(elemento)
    valor = elemento.get(atributo)
    if isinstance(valor, list):  # p. ej. class
        valor = " ".join(valor)
    return valor


def valor_campo(elemento: Tag, campo: Campo, url_base: str, decimal: str) -> Any:
    """Busca el campo dentro de `elemento`, aplica regex y conversión de tipo."""
    try:
        if not campo.selector:
            encontrados = [elemento]
        elif campo.todos:
            encontrados = elemento.select(campo.selector)
        else:
            uno = elemento.select_one(campo.selector)
            encontrados = [uno] if uno is not None else []
    except Exception as exc:  # noqa: BLE001 - soupsieve lanza SelectorSyntaxError
        raise ValueError(f"Selector CSS inválido en el campo {campo.nombre!r}: {campo.selector!r} ({exc})") from exc

    crudos = [t for t in (_texto_crudo(e, campo.atributo) for e in encontrados) if t is not None]
    if campo.regex:
        filtrados = []
        for texto in crudos:
            m = re.search(campo.regex, texto)
            if m:
                filtrados.append(m.group(1) if m.groups() else m.group(0))
        crudos = filtrados

    valores = [convertir(t, campo.tipo, decimal, campo.formato_fecha, url_base) for t in crudos]
    valores = [v for v in valores if v is not None]
    if not valores:
        return campo.por_defecto
    if campo.todos:
        return " | ".join(str(v) for v in valores)
    return valores[0]


def extraer_campos(elemento: Tag, campos: list[Campo], url_base: str, decimal: str) -> dict[str, Any]:
    return {c.nombre: valor_campo(elemento, c, url_base, decimal) for c in campos}


def extraer_items(html: str, url_pagina: str, sitio: Sitio) -> tuple[list[dict[str, Any]], int]:
    """Devuelve (registros válidos, cantidad descartada por faltar campos requeridos)."""
    documento = sopa(html)
    elementos = documento.select(sitio.selector_lista)
    requeridos = [c.nombre for c in sitio.campos if c.requerido]
    registros, descartados = [], 0
    for elemento in elementos:
        registro = extraer_campos(elemento, sitio.campos, url_pagina, sitio.decimal)
        faltan = [n for n in requeridos if registro.get(n) in (None, "")]
        if faltan:
            descartados += 1
            log.debug("Elemento descartado en %s: faltan %s", url_pagina, faltan)
            continue
        registros.append(registro)
    log.info("%s: %d elementos, %d válidos", url_pagina, len(elementos), len(registros))
    return registros, descartados


def extraer_detalle(html: str, url: str, sitio: Sitio) -> dict[str, Any]:
    assert sitio.detalle is not None
    return extraer_campos(sopa(html), sitio.detalle.campos, url, sitio.decimal)


def url_siguiente(html: str, url_pagina: str, paginacion: Paginacion) -> str | None:
    """Para paginación 'siguiente': la URL del enlace a la próxima página, o None si no hay."""
    enlace = sopa(html).select_one(paginacion.selector or "")
    if enlace is None:
        return None
    href = limpiar_texto(enlace.get("href"))
    if not href or href.startswith(("javascript:", "#")):
        return None
    return urljoin(url_pagina, href)


def url_numero(sitio: Sitio, n: int) -> str:
    """Para paginación 'numero': arma la URL de la página n a partir de la plantilla."""
    plantilla = sitio.paginacion.plantilla or ""
    return urljoin(sitio.url_inicial, plantilla.format(n=n))
