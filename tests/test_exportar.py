import csv
import json

import pytest
from docx import Document
from openpyxl import load_workbook

from scraper.exportar import ErrorExportacion, exportar, formato_ar, normalizar_formatos, valor_legible
from scraper.motor import Scraper


@pytest.fixture
def resultado(sitio_demo, ajustes):
    return Scraper(sitio_demo, ajustes).correr()


def test_normalizar_formatos():
    assert normalizar_formatos("excel, PDF,xlsx") == ["excel", "pdf"]
    assert normalizar_formatos("todos") == ["csv", "excel", "word", "pdf", "json"]
    with pytest.raises(ErrorExportacion, match="desconocido"):
        normalizar_formatos("excel,odt")


def test_formato_argentino():
    assert formato_ar(1234567.891) == "1.234.567,89"
    assert valor_legible(45999.9, "precio") == "$ 45.999,90"
    assert valor_legible(1250, "entero") == "1.250"
    assert valor_legible(None, "texto") == ""


def test_exporta_todos_los_formatos(resultado, ajustes, tmp_path):
    archivos = exportar(resultado, normalizar_formatos("todos"), tmp_path, ajustes)
    assert sorted(a.suffix for a in archivos) == [".csv", ".docx", ".json", ".pdf", ".xlsx"]
    assert all(a.stat().st_size > 0 for a in archivos)
    assert archivos[0].name == "ferreteria_demo.csv"


def test_excel_con_formato(resultado, ajustes, tmp_path):
    (ruta,) = exportar(resultado, ["excel"], tmp_path, ajustes)
    libro = load_workbook(ruta)
    hoja = libro.worksheets[0]
    assert [c.value for c in hoja[1]][:3] == ["Titulo", "Sku", "Precio"]
    assert hoja["A1"].font.bold
    assert hoja.freeze_panes == "A2"
    assert hoja.auto_filter.ref == "A1:J12"                 # 10 columnas, 11 registros + encabezado
    assert hoja.max_row == 12
    assert hoja["C2"].value == 45999.9 and "#,##0.00" in hoja["C2"].number_format
    assert hoja["E2"].number_format == "DD/MM/YYYY"
    assert hoja["F2"].hyperlink is not None
    assert hoja.column_dimensions["A"].width > 10
    assert "Info" in libro.sheetnames


def test_csv_utf8_con_separador_configurable(resultado, ajustes, tmp_path):
    (ruta,) = exportar(resultado, ["csv"], tmp_path, ajustes)
    assert ruta.read_bytes().startswith(b"\xef\xbb\xbf")     # BOM para que Excel respete los acentos
    filas = list(csv.reader(ruta.open(encoding="utf-8-sig"), delimiter=";"))
    assert filas[0][:3] == ["titulo", "sku", "precio"]
    assert filas[1][2] == "45999,9" and filas[1][4] == "2025-03-15"
    assert len(filas) == 12
    ajustes.csv_separador, ajustes.csv_decimal = ",", "."
    (ruta,) = exportar(resultado, ["csv"], tmp_path / "otro", ajustes)
    assert list(csv.reader(ruta.open(encoding="utf-8-sig")))[1][2] == "45999.9"


def test_word_con_tabla(resultado, ajustes, tmp_path):
    (ruta,) = exportar(resultado, ["word"], tmp_path, ajustes)
    doc = Document(ruta)
    assert doc.paragraphs[0].text == "Relevamiento de precios - Ferretería Demo"
    tabla = doc.tables[0]
    assert len(tabla.rows) == 12
    assert tabla.rows[0].cells[0].text == "Titulo"
    assert tabla.rows[1].cells[2].text == "$ 45.999,90"


def test_pdf_valido(resultado, ajustes, tmp_path):
    (ruta,) = exportar(resultado, ["pdf"], tmp_path, ajustes)
    contenido = ruta.read_bytes()
    assert contenido.startswith(b"%PDF") and b"%%EOF" in contenido[-1024:]


def test_json(resultado, ajustes, tmp_path):
    (ruta,) = exportar(resultado, ["json"], tmp_path, ajustes, nombre_base="mi salida/2025")
    assert ruta.name == "mi_salida_2025.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(datos["registros"]) == 11 and datos["estadisticas"]["paginas"] == 3


def test_sin_registros_igual_genera_archivos(sitio_demo, ajustes, tmp_path):
    sitio_demo.selector_lista = "div.no-existe"
    vacio = Scraper(sitio_demo, ajustes).correr()
    archivos = exportar(vacio, normalizar_formatos("todos"), tmp_path, ajustes)
    assert len(archivos) == 5
    assert "No se encontraron registros." in [p.text for p in Document(tmp_path / "ferreteria_demo.docx").paragraphs]
