"""Cliente HTTP con transporte falso (httpx.MockTransport): reintentos, demora, caché, robots y User-Agent."""
import json

import httpx
import pytest

from scraper.cliente import BloqueadoPorRobots, ClienteWeb, ErrorDescarga
from scraper.config import Ajustes


class Reloj:
    """Reloj falso: dormir() avanza el tiempo en vez de esperar de verdad."""

    def __init__(self):
        self.ahora = 0.0
        self.esperas = []

    def __call__(self):
        return self.ahora

    def dormir(self, segundos):
        self.esperas.append(round(segundos, 3))
        self.ahora += segundos


def cliente_con(manejador, reloj=None, **ajustes):
    base = dict(demora_segundos=0, reintentos=3, espera_reintento=1, cache_horas=0, respetar_robots=False)
    base.update(ajustes)
    reloj = reloj or Reloj()
    return ClienteWeb(Ajustes(**base), transporte=httpx.MockTransport(manejador), dormir=reloj.dormir, reloj=reloj)


def test_reintenta_ante_503_con_espera_exponencial():
    llamadas = []

    def manejador(pedido):
        llamadas.append(pedido.url)
        return httpx.Response(503) if len(llamadas) < 3 else httpx.Response(200, text="<p>ok</p>")

    reloj = Reloj()
    cliente = cliente_con(manejador, reloj)
    respuesta = cliente.obtener("https://sitio.com/a")
    assert respuesta.texto == "<p>ok</p>"
    assert len(llamadas) == 3
    assert reloj.esperas == [1, 2]                     # 1 s, 2 s (se duplica)
    assert cliente.estadisticas["reintentos"] == 2


def test_respeta_retry_after_en_429():
    estados = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")])
    reloj = Reloj()
    cliente = cliente_con(lambda pedido: next(estados), reloj)
    assert cliente.obtener("https://sitio.com/").texto == "ok"
    assert reloj.esperas == [7]


def test_reintenta_errores_de_red_y_se_rinde():
    def manejador(pedido):
        raise httpx.ConnectError("conexión rechazada", request=pedido)

    cliente = cliente_con(manejador, reintentos=2)
    with pytest.raises(ErrorDescarga, match="3 intentos.*ConnectError"):
        cliente.obtener("https://sitio.com/")
    assert cliente.estadisticas["pedidos_red"] == 3


def test_404_no_se_reintenta():
    llamadas = []

    def manejador(pedido):
        llamadas.append(1)
        return httpx.Response(404)

    cliente = cliente_con(manejador)
    with pytest.raises(ErrorDescarga) as error:
        cliente.obtener("https://sitio.com/no-existe")
    assert error.value.estado == 404 and len(llamadas) == 1


def test_demora_entre_pedidos():
    reloj = Reloj()
    cliente = cliente_con(lambda p: httpx.Response(200, text="x"), reloj, demora_segundos=2)
    for i in range(3):
        cliente.obtener(f"https://sitio.com/{i}")
    assert reloj.esperas == [2, 2]                     # el primer pedido no espera


def test_envia_user_agent_configurado():
    vistos = []

    def manejador(pedido):
        vistos.append(pedido.headers["User-Agent"])
        return httpx.Response(200, text="x")

    cliente_con(manejador, user_agent="ClienteBot/1.0 (+mail@ejemplo.com)").obtener("https://sitio.com/")
    assert vistos == ["ClienteBot/1.0 (+mail@ejemplo.com)"]


def test_cache_local_evita_pedir_dos_veces(tmp_path):
    llamadas = []

    def manejador(pedido):
        llamadas.append(1)
        return httpx.Response(200, text="<b>hola</b>")

    opciones = dict(cache_horas=1, cache_dir=str(tmp_path))
    primero = cliente_con(manejador, **opciones).obtener("https://sitio.com/p")
    segundo = cliente_con(manejador, **opciones).obtener("https://sitio.com/p")   # otro cliente, misma caché
    assert not primero.desde_cache and segundo.desde_cache
    assert segundo.texto == "<b>hola</b>" and len(llamadas) == 1


def test_cache_vencida_se_vuelve_a_pedir(tmp_path):
    llamadas = []

    def manejador(pedido):
        llamadas.append(1)
        return httpx.Response(200, text="x")

    cliente_con(manejador, cache_horas=1, cache_dir=str(tmp_path)).obtener("https://sitio.com/p")
    for archivo in tmp_path.glob("*.json"):            # simula que pasaron 2 horas
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        datos["guardado"] -= 7200
        archivo.write_text(json.dumps(datos), encoding="utf-8")
    cliente_con(manejador, cache_horas=1, cache_dir=str(tmp_path)).obtener("https://sitio.com/p")
    assert len(llamadas) == 2


ROBOTS = "User-agent: *\nDisallow: /privado/\nCrawl-delay: 5\n\nUser-agent: MarkScraper\nDisallow: /admin/\n"


def manejador_con_robots(robots_texto=ROBOTS, estado_robots=200):
    def manejador(pedido):
        if pedido.url.path == "/robots.txt":
            return httpx.Response(estado_robots, text=robots_texto)
        return httpx.Response(200, text="contenido")
    return manejador


def test_robots_bloquea_y_permite():
    cliente = cliente_con(manejador_con_robots("User-agent: *\nDisallow: /privado/\nCrawl-delay: 5\n"),
                          respetar_robots=True)
    assert cliente.obtener("https://sitio.com/publico").texto == "contenido"
    with pytest.raises(BloqueadoPorRobots):
        cliente.obtener("https://sitio.com/privado/datos")
    assert cliente.estadisticas["bloqueados_robots"] == 1
    info = cliente.robots.info("https://sitio.com/")
    assert info.reglas == [("Disallow", "/privado/")] and info.crawl_delay == 5


def test_crawl_delay_aumenta_la_demora():
    reloj = Reloj()
    cliente = cliente_con(manejador_con_robots("User-agent: *\nCrawl-delay: 5\n"), reloj,
                          respetar_robots=True, demora_segundos=1)
    cliente.obtener("https://sitio.com/a")
    cliente.obtener("https://sitio.com/b")
    assert 5 in reloj.esperas


def test_robots_usa_el_grupo_de_nuestro_user_agent():
    cliente = cliente_con(manejador_con_robots(), respetar_robots=True, user_agent="MarkScraper/1.0")
    assert cliente.robots.permitido("https://sitio.com/privado/x")       # el grupo propio no lo bloquea
    assert not cliente.robots.permitido("https://sitio.com/admin/")
    assert cliente.robots.info("https://sitio.com").reglas == [("Disallow", "/admin/")]


@pytest.mark.parametrize("estado, permitido, descripcion", [
    (404, True, "no_existe"), (403, False, "prohibido"), (500, False, "error")])
def test_robots_segun_estado(estado, permitido, descripcion):
    cliente = cliente_con(manejador_con_robots("", estado), respetar_robots=True, reintentos=0)
    assert cliente.robots.permitido("https://sitio.com/x") is permitido
    assert cliente.robots.info("https://sitio.com").estado == descripcion


def test_javascript_sin_playwright_da_error_claro(monkeypatch):
    import builtins
    original = builtins.__import__

    def importar(nombre, *args, **kwargs):
        if nombre.startswith("playwright"):
            raise ImportError("no instalado")
        return original(nombre, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importar)
    cliente = cliente_con(lambda p: httpx.Response(200, text="x"))
    with pytest.raises(ErrorDescarga, match="Playwright no está instalado"):
        cliente.obtener("https://sitio.com/", javascript=True)
