from pathlib import Path

import pytest

from scraper.config import Ajustes, ErrorConfig, cargar_sitio, sitio_desde_dict

RAIZ = Path(__file__).resolve().parent.parent

BASE = {
    "url_inicial": "https://ejemplo.com/lista",
    "lista": {"selector": "div.item"},
    "campos": {"titulo": "h2", "enlace": {"selector": "a", "atributo": "href", "tipo": "url"}},
}


@pytest.mark.parametrize("archivo", ["demo.yaml", "demo_noticias.yaml", "ejemplo.yaml"])
def test_los_yaml_incluidos_son_validos(archivo):
    sitio = cargar_sitio(RAIZ / "sitios" / archivo)
    assert sitio.campos and sitio.url_inicial.startswith("http")


def test_demo_yaml_tiene_detalle_y_columnas():
    sitio = cargar_sitio(RAIZ / "sitios" / "demo.yaml")
    assert sitio.paginacion.tipo == "siguiente"
    assert sitio.detalle.enlace == "enlace"
    assert sitio.columnas()[-4:] == ["marca", "stock", "garantia_meses", "descripcion"]
    assert sitio.tipos()["precio"] == "precio"


def test_forma_corta_de_campo():
    sitio = sitio_desde_dict(BASE)
    assert sitio.campos[0].selector == "h2" and sitio.campos[0].tipo == "texto"


@pytest.mark.parametrize("cambio, mensaje", [
    ({"url_inicial": "ftp://x"}, "http"),
    ({"lista": {}}, "lista.selector"),
    ({"campos": {"x": {"selector": "a", "tipo": "moneda"}}}, "tipo"),
    ({"campos": {"x": {"selector": "a", "selectr": "b"}}}, "desconocidas"),
    ({"paginacion": {"tipo": "siguiente"}}, "selector"),
    ({"paginacion": {"tipo": "numero", "plantilla": "pagina.html"}}, "{n}"),
    ({"paginacion": {"tipo": "infinita"}}, "paginacion.tipo"),
    ({"detalle": {"enlace": "no_existe", "campos": {"a": "p"}}}, "detalle.enlace"),
    ({"deduplicar_por": ["precio"]}, "deduplicar_por"),
    ({"decimal": ";"}, "decimal"),
    ({"opciones": {"demora": 1}}, "Opción desconocida"),
    ({"opciones": {"demora_segundos": "rápido"}}, "inválido"),
])
def test_errores_de_configuracion_claros(cambio, mensaje):
    with pytest.raises(ErrorConfig, match=mensaje.replace("{", r"\{").replace("}", r"\}")):
        sitio_desde_dict({**BASE, **cambio})


def test_falta_clave_obligatoria():
    with pytest.raises(ErrorConfig, match="campos"):
        sitio_desde_dict({"url_inicial": "https://x.com", "lista": "div"})


def test_archivo_inexistente_y_yaml_roto(tmp_path):
    with pytest.raises(ErrorConfig, match="No existe"):
        cargar_sitio(tmp_path / "nada.yaml")
    roto = tmp_path / "roto.yaml"
    roto.write_text("campos: [a, b\n", encoding="utf-8")
    with pytest.raises(ErrorConfig, match="YAML inválido"):
        cargar_sitio(roto)


def test_ajustes_desde_entorno_y_opciones_del_yaml(monkeypatch):
    monkeypatch.setenv("SCRAPER_USER_AGENT", "ClienteBot/2.0")
    monkeypatch.setenv("SCRAPER_DEMORA_SEGUNDOS", "3")
    monkeypatch.setenv("SCRAPER_RESPETAR_ROBOTS", "no")
    ajustes = Ajustes.desde_entorno({"demora_segundos": 0.5})
    assert ajustes.user_agent == "ClienteBot/2.0"
    assert ajustes.demora_segundos == 0.5          # el YAML gana sobre el entorno
    assert ajustes.respetar_robots is False


def test_variable_de_entorno_invalida(monkeypatch):
    monkeypatch.setenv("SCRAPER_REINTENTOS", "muchos")
    with pytest.raises(ErrorConfig, match="SCRAPER_REINTENTOS"):
        Ajustes.desde_entorno()
