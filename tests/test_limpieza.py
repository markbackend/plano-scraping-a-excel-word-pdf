from datetime import date

import pytest

from scraper.limpieza import a_entero, a_fecha, a_numero, a_url, convertir, limpiar_texto


def test_limpiar_texto_colapsa_espacios_y_nbsp():
    assert limpiar_texto("  Set de\n   destornilladores\xa0x12 ") == "Set de destornilladores x12"
    assert limpiar_texto("   ") is None
    assert limpiar_texto(None) is None


@pytest.mark.parametrize("texto, decimal, esperado", [
    ("$ 45.999,90", ",", 45999.90),
    ("$ 38.500", ",", 38500.0),
    ("$\xa012.750,00", ",", 12750.0),
    ("$ 1.999,5", ",", 1999.5),
    ("USD 1,234.56", ",", 1234.56),        # los dos separadores: manda el último
    ("£51.77", ".", 51.77),
    ("1,234", ".", 1234.0),                 # sitio en inglés: la coma es de miles
    ("1,5 kg", ",", 1.5),
    ("1.234.567", ",", 1234567.0),
    ("1 234,50 €", ",", 1234.50),
    ("- $ 300", ",", -300.0),
    ("-3,5 %", ",", -3.5),
    ("Consultar", ",", None),
    ("", ",", None),
])
def test_a_numero(texto, decimal, esperado):
    assert a_numero(texto, decimal) == esperado


def test_a_entero():
    assert a_entero("Stock: 1.250 unidades") == 1250
    assert a_entero("Garantía: 12 meses") == 12
    assert a_entero("sin dato") is None


@pytest.mark.parametrize("texto, esperado", [
    ("15/03/2025", date(2025, 3, 15)),
    ("2025-03-15", date(2025, 3, 15)),
    ("2025-03-15T10:30:00-03:00", date(2025, 3, 15)),
    ("3 de marzo de 2025", date(2025, 3, 3)),
    ("Publicado el 18 de setiembre del 2024", date(2024, 9, 18)),
    ("Mar 3, 2025", date(2025, 3, 3)),
    ("15/03/25", date(2025, 3, 15)),
    ("15/03/2025 18:40", date(2025, 3, 15)),
    ("31/02/2025", None),                   # fecha imposible
    ("cualquier cosa", None),
])
def test_a_fecha(texto, esperado):
    assert a_fecha(texto) == esperado


def test_a_fecha_relativa_y_formato_propio():
    hoy = date(2025, 5, 10)
    assert a_fecha("Hoy", hoy=hoy) == hoy
    assert a_fecha("ayer 14:00", hoy=hoy) == date(2025, 5, 9)
    assert a_fecha("hace 3 días", hoy=hoy) == date(2025, 5, 7)
    assert a_fecha("20250315", formatos=["%Y%m%d"]) == date(2025, 3, 15)


def test_a_url_y_convertir():
    base = "https://tienda.com/productos/pagina-1.html"
    assert a_url("detalle/p1.html", base) == "https://tienda.com/productos/detalle/p1.html"
    assert a_url("/x", base) == "https://tienda.com/x"
    assert a_url("javascript:void(0)", base) is None
    assert convertir(" hola ", "texto") == "hola"
    assert convertir("$ 10", "precio") == 10.0
