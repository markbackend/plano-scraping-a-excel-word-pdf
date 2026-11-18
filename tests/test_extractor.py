import pytest

from scraper.config import Paginacion, sitio_desde_dict
from scraper.extractor import extraer_items, url_numero, url_siguiente, valor_campo, sopa
from scraper.config import Campo

HTML = """
<ul>
  <li class="aviso" data-id="A1">
    <a class="titulo" href="/aviso/1">  Depto 2 ambientes  </a>
    <span class="precio">USD 85.000</span>
    <span class="tag">balcón</span><span class="tag">cochera</span>
    <span class="info">Publicado: 05/06/2025 - 45 m²</span>
    <img src="img/1.jpg">
  </li>
  <li class="aviso" data-id="A2">
    <a class="titulo" href="https://otro.com/aviso/2">Casa 4 ambientes</a>
    <span class="precio">Consultar</span>
  </li>
  <li class="aviso" data-id="A3">
    <span class="precio">USD 10</span>
  </li>
</ul>
<a class="sig" href="?pagina=2">Siguiente</a>
"""

SITIO = sitio_desde_dict({
    "url_inicial": "https://inmo.com/avisos/lista.html",
    "lista": "li.aviso",
    "campos": {
        "id": {"atributo": "data-id"},
        "titulo": {"selector": "a.titulo", "requerido": True},
        "enlace": {"selector": "a.titulo", "atributo": "href", "tipo": "url"},
        "precio": {"selector": ".precio", "tipo": "precio", "por_defecto": 0},
        "etiquetas": {"selector": ".tag", "todos": True},
        "publicado": {"selector": ".info", "regex": r"(\d{2}/\d{2}/\d{4})", "tipo": "fecha"},
        "metros": {"selector": ".info", "regex": r"(\d+)\s*m²", "tipo": "entero"},
        "imagen": {"selector": "img", "atributo": "src", "tipo": "url"},
    },
})


def test_extrae_items_con_atributos_regex_y_tipos():
    registros, descartados = extraer_items(HTML, SITIO.url_inicial, SITIO)
    assert descartados == 1                                  # A3 no tiene título (requerido)
    primero, segundo = registros
    assert primero["id"] == "A1"
    assert primero["titulo"] == "Depto 2 ambientes"
    assert primero["enlace"] == "https://inmo.com/aviso/1"
    assert primero["precio"] == 85000.0
    assert primero["etiquetas"] == "balcón | cochera"
    assert str(primero["publicado"]) == "2025-06-05"
    assert primero["metros"] == 45
    assert primero["imagen"] == "https://inmo.com/avisos/img/1.jpg"
    assert segundo["enlace"] == "https://otro.com/aviso/2"
    assert segundo["precio"] == 0                            # "Consultar" -> por_defecto
    assert segundo["etiquetas"] is None and segundo["imagen"] is None


def test_url_siguiente_y_por_numero():
    assert url_siguiente(HTML, SITIO.url_inicial, Paginacion("siguiente", "a.sig")) == \
        "https://inmo.com/avisos/lista.html?pagina=2"
    assert url_siguiente("<p>sin enlace</p>", SITIO.url_inicial, Paginacion("siguiente", "a.sig")) is None
    assert url_siguiente('<a class="sig" href="#">x</a>', SITIO.url_inicial, Paginacion("siguiente", "a.sig")) is None
    SITIO.paginacion = Paginacion("numero", plantilla="?page={n}")
    assert url_numero(SITIO, 3) == "https://inmo.com/avisos/lista.html?page=3"


def test_selector_invalido_da_error_claro():
    elemento = sopa("<div><p>x</p></div>")
    with pytest.raises(ValueError, match="Selector CSS inválido"):
        valor_campo(elemento, Campo("malo", selector="p[["), "https://x.com", ",")
