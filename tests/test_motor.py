"""Corridas completas contra el sitio de ejemplo LOCAL (servidor HTTP en 127.0.0.1)."""
from datetime import date

import httpx
import pytest

from scraper.cliente import ClienteWeb, ErrorDescarga
from scraper.config import sitio_desde_dict
from scraper.motor import Scraper


def test_demo_completo_paginacion_detalle_duplicados_y_robots(sitio_demo, ajustes):
    resultado = Scraper(sitio_demo, ajustes).correr()
    e = resultado.estadisticas
    assert len(resultado.registros) == 11
    assert e["paginas"] == 3
    assert e["duplicados"] == 1            # el taladro aparece en la página 1 y en la 3
    assert e["descartados"] == 1           # producto sin título
    assert e["bloqueados_robots"] == 1     # el detalle de p8 está en /privado/
    assert e["detalles"] == 10
    assert len(resultado.errores) == 1 and "robots" in resultado.errores[0]

    por_sku = {r["sku"]: r for r in resultado.registros}
    taladro = por_sku["SKU-001"]
    assert taladro["titulo"] == "Taladro percutor 650 W"
    assert taladro["precio"] == 45999.90
    assert taladro["publicado"] == date(2025, 3, 15)
    assert taladro["marca"] == "Fuerte" and taladro["stock"] == 12 and taladro["garantia_meses"] == 12
    assert taladro["enlace"].endswith("/productos/detalle/p1.html")
    assert por_sku["SKU-003"]["titulo"] == "Set de destornilladores x12"   # espacios limpiados
    assert por_sku["SKU-004"]["stock"] == 1250
    assert por_sku["SKU-004"]["garantia_meses"] is None                    # "Sin garantía"
    assert por_sku["SKU-007"]["precio"] is None                            # "Consultar"
    assert por_sku["SKU-008"]["marca"] is None                             # detalle bloqueado
    assert list(taladro) == resultado.columnas


def test_paginacion_por_numero_termina_en_404(sitio_noticias, ajustes):
    resultado = Scraper(sitio_noticias, ajustes).correr()
    assert [r["titulo"] for r in resultado.registros][:2] == ["Nuevo local en Rosario", "Horario de feriados"]
    assert len(resultado.registros) == 5
    assert resultado.estadisticas["paginas"] == 2
    assert resultado.registros[0]["fecha"] == date(2025, 3, 3)
    assert resultado.registros[0]["autor"] == "Ana Gómez"
    assert resultado.errores == []


def test_max_registros_y_max_paginas(sitio_demo, ajustes):
    sitio_demo.max_registros = 3
    assert len(Scraper(sitio_demo, ajustes).correr().registros) == 3
    sitio_demo.max_registros = 0
    sitio_demo.paginacion.max_paginas = 1
    resultado = Scraper(sitio_demo, ajustes).correr()
    assert resultado.estadisticas["paginas"] == 1 and len(resultado.registros) == 4


def test_sin_robots_entra_al_detalle_privado(sitio_demo, ajustes):
    ajustes.respetar_robots = False
    resultado = Scraper(sitio_demo, ajustes).correr()
    assert resultado.estadisticas["detalles"] == 11
    assert {r["sku"]: r for r in resultado.registros}["SKU-008"]["marca"] == "Acerox"


def test_primera_pagina_inexistente_corta_la_corrida(sitio_demo, ajustes, base_url):
    sitio_demo.url_inicial = base_url + "no-existe.html"
    with pytest.raises(ErrorDescarga, match="404"):
        Scraper(sitio_demo, ajustes).correr()


def _sitio_falso(**extra):
    return sitio_desde_dict({
        "url_inicial": "https://falso.com/1", "lista": "p.item",
        "campos": {"nombre": {"selector": None, "requerido": True}},
        "paginacion": {"tipo": "siguiente", "selector": "a.sig"}, **extra})


def test_paginacion_en_bucle_se_corta(ajustes):
    paginas = {"/1": '<p class="item">a</p><a class="sig" href="/2">></a>',
               "/2": '<p class="item">b</p><a class="sig" href="/1">></a>'}   # la 2 vuelve a la 1
    ajustes.respetar_robots = False
    cliente = ClienteWeb(ajustes, transporte=httpx.MockTransport(
        lambda pedido: httpx.Response(200, text=paginas[pedido.url.path])))
    resultado = Scraper(_sitio_falso(), ajustes, cliente).correr()
    assert [r["nombre"] for r in resultado.registros] == ["a", "b"]
    assert resultado.estadisticas["paginas"] == 2


def test_error_en_pagina_intermedia_no_pierde_lo_ya_extraido(ajustes):
    def manejador(pedido):
        if pedido.url.path == "/1":
            return httpx.Response(200, text='<p class="item">a</p><a class="sig" href="/2">></a>')
        return httpx.Response(500)

    ajustes.respetar_robots = False
    cliente = ClienteWeb(ajustes, transporte=httpx.MockTransport(manejador), dormir=lambda s: None)
    resultado = Scraper(_sitio_falso(), ajustes, cliente).correr()
    assert [r["nombre"] for r in resultado.registros] == ["a"]
    assert len(resultado.errores) == 1 and "500" in resultado.errores[0]
