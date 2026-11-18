"""Fixtures comunes. Ninguna prueba sale a internet: se usa un servidor local o httpx.MockTransport."""
from __future__ import annotations

from pathlib import Path

import pytest

from scraper.config import Ajustes, cargar_sitio
from scraper.servidor_local import SITIO_DEMO, cambiar_base, servir_carpeta

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch, tmp_path):
    """Que un .env o variables del sistema no cambien el resultado de las pruebas."""
    import os

    import dotenv
    for nombre in list(os.environ):
        if nombre.startswith("SCRAPER_"):
            monkeypatch.delenv(nombre)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    # que ninguna prueba escriba caché ni salidas dentro del proyecto
    monkeypatch.setenv("SCRAPER_CACHE_DIR", str(tmp_path / "cache_entorno"))
    monkeypatch.setenv("SCRAPER_SALIDA_DIR", str(tmp_path / "salidas_entorno"))


@pytest.fixture(scope="session")
def base_url():
    with servir_carpeta(SITIO_DEMO) as base:
        yield base


@pytest.fixture
def ajustes(tmp_path):
    return Ajustes(demora_segundos=0, reintentos=1, espera_reintento=0, cache_horas=0,
                   cache_dir=str(tmp_path / "cache"), salida_dir=str(tmp_path / "salidas"), timeout_segundos=5)


@pytest.fixture
def sitio_demo(base_url):
    sitio = cargar_sitio(RAIZ / "sitios" / "demo.yaml")
    sitio.url_inicial = cambiar_base(sitio.url_inicial, base_url)
    return sitio


@pytest.fixture
def sitio_noticias(base_url):
    sitio = cargar_sitio(RAIZ / "sitios" / "demo_noticias.yaml")
    sitio.url_inicial = cambiar_base(sitio.url_inicial, base_url)
    return sitio
