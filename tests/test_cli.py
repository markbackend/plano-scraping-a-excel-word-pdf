"""La línea de comandos de punta a punta (contra el sitio local)."""
from pathlib import Path

from scraper.cli import main

RAIZ = Path(__file__).resolve().parent.parent
DEMO = str(RAIZ / "sitios" / "demo.yaml")


def test_demo(tmp_path, capsys):
    assert main(["demo", "--salida", str(tmp_path)]) == 0
    salida = capsys.readouterr().out
    assert "11 registros" in salida and "bloquea: /privado/" in salida
    assert {p.suffix for p in tmp_path.iterdir()} == {".csv", ".xlsx", ".docx", ".pdf", ".json"}


def test_correr_con_url_y_formatos(tmp_path, base_url, capsys, monkeypatch):
    monkeypatch.setenv("SCRAPER_CACHE_DIR", str(tmp_path / "cache"))
    codigo = main(["correr", DEMO, "--url", base_url + "productos/pagina-1.html",
                   "--formato", "excel,pdf", "--salida", str(tmp_path), "--max-paginas", "1"])
    assert codigo == 0
    assert sorted(p.name for p in tmp_path.glob("ferreteria_demo.*")) == ["ferreteria_demo.pdf",
                                                                          "ferreteria_demo.xlsx"]
    assert "4 registros" in capsys.readouterr().out


def test_muestra(base_url, capsys):
    assert main(["muestra", DEMO, "--url", base_url + "productos/pagina-2.html"]) == 0
    salida = capsys.readouterr().out
    assert "Llave inglesa" in salida and "Elementos válidos: 4" in salida


def test_muestra_con_selector_que_no_coincide(tmp_path, base_url, capsys):
    yaml = tmp_path / "malo.yaml"
    yaml.write_text(f"url_inicial: {base_url}productos/pagina-1.html\nlista: div.nada\ncampos:\n  t: h2\n",
                    encoding="utf-8")
    assert main(["muestra", str(yaml)]) == 2
    assert "Ningún elemento coincide" in capsys.readouterr().out


def test_robots(base_url, capsys):
    url = base_url + "productos/pagina-1.html"
    assert main(["robots", DEMO, "--url", url, "--probar", base_url + "privado/p8.html"]) == 0
    salida = capsys.readouterr().out
    assert "Disallow: /privado/" in salida
    assert f"PERMITIDA  {url}" in salida and "BLOQUEADA" in salida


def test_validar(capsys):
    assert main(["validar", DEMO]) == 0
    assert "OK: Ferretería Demo" in capsys.readouterr().out


def test_errores_devuelven_codigo(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPER_REINTENTOS", "0")
    monkeypatch.setenv("SCRAPER_TIMEOUT_SEGUNDOS", "2")
    assert main(["validar", str(tmp_path / "no-existe.yaml")]) == 1
    assert main(["correr", DEMO, "--url", "http://127.0.0.1:9/", "--formato", "excel"]) == 2  # puerto cerrado
    assert main(["correr", DEMO, "--formato", "odt"]) == 2
