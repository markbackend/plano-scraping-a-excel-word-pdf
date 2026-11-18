"""Exporta un Resultado a CSV, Excel (con formato), Word (informe con tabla), PDF y JSON."""
from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from .config import Ajustes
from .motor import Resultado

log = logging.getLogger(__name__)

ALIAS = {"csv": "csv", "excel": "excel", "xlsx": "excel", "word": "word", "docx": "word",
         "pdf": "pdf", "json": "json"}
EXTENSION = {"csv": ".csv", "excel": ".xlsx", "word": ".docx", "pdf": ".pdf", "json": ".json"}


class ErrorExportacion(Exception):
    pass


def normalizar_formatos(texto: str) -> list[str]:
    formatos = []
    for parte in re.split(r"[,\s]+", texto.strip().lower()):
        if not parte:
            continue
        if parte == "todos":
            return list(EXTENSION)
        if parte not in ALIAS:
            raise ErrorExportacion(f"Formato desconocido: {parte!r}. Válidos: csv, excel, word, pdf, json, todos")
        if ALIAS[parte] not in formatos:
            formatos.append(ALIAS[parte])
    if not formatos:
        raise ErrorExportacion("No se indicó ningún formato")
    return formatos


def exportar(resultado: Resultado, formatos: list[str], carpeta: str | Path, ajustes: Ajustes,
             nombre_base: str | None = None) -> list[Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = _nombre_seguro(nombre_base or resultado.sitio.nombre_archivo)
    funciones: dict[str, Callable[[Resultado, Path, Ajustes], None]] = {
        "csv": a_csv, "excel": a_excel, "word": a_word, "pdf": a_pdf, "json": a_json}
    archivos = []
    for formato in formatos:
        ruta = carpeta / f"{nombre}{EXTENSION[formato]}"
        try:
            funciones[formato](resultado, ruta, ajustes)
        except PermissionError as exc:
            raise ErrorExportacion(f"No se pudo escribir {ruta}: ¿está abierto en Excel/Word? ({exc})") from exc
        log.info("Generado %s", ruta)
        archivos.append(ruta)
    return archivos


# --------------------------------------------------------------------------- formato de valores

def _nombre_seguro(nombre: str) -> str:
    return re.sub(r"[^\w\-]+", "_", nombre, flags=re.UNICODE).strip("_") or "resultado"


def formato_ar(numero: float, decimales: int = 2) -> str:
    """1234.5 -> '1.234,50' (formato argentino)."""
    texto = f"{numero:,.{decimales}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def valor_legible(valor: Any, tipo: str) -> str:
    """Texto para Word/PDF: números con formato argentino y fechas dd/mm/aaaa."""
    if valor is None:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, int):
        return formato_ar(valor, 0)
    if isinstance(valor, float):
        if tipo == "precio":
            return "$ " + formato_ar(valor, 2)
        return formato_ar(valor, 0 if valor.is_integer() else 2)
    return str(valor)


def _encabezado(columna: str) -> str:
    return columna.replace("_", " ").capitalize()


def _metadatos(resultado: Resultado) -> list[str]:
    fin = resultado.fin or datetime.now()
    return [
        f"Fuente: {resultado.sitio.url_inicial}",
        f"Fecha de extracción: {fin.strftime('%d/%m/%Y %H:%M')}",
        f"Registros: {len(resultado.registros)}",
    ]


# --------------------------------------------------------------------------- CSV y JSON

def a_csv(resultado: Resultado, ruta: Path, ajustes: Ajustes) -> None:
    """CSV en UTF-8 con BOM (Excel lo abre bien) y separador/decimal configurables."""
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=ajustes.csv_separador)
        escritor.writerow(resultado.columnas)
        for registro in resultado.registros:
            fila = []
            for columna in resultado.columnas:
                valor = registro.get(columna)
                if isinstance(valor, float):
                    valor = repr(valor).replace(".", ajustes.csv_decimal) if valor % 1 else str(int(valor))
                elif isinstance(valor, date):
                    valor = valor.isoformat()
                fila.append("" if valor is None else valor)
            escritor.writerow(fila)


def a_json(resultado: Resultado, ruta: Path, ajustes: Ajustes) -> None:
    datos = {
        "sitio": resultado.sitio.nombre,
        "fuente": resultado.sitio.url_inicial,
        "generado": (resultado.fin or datetime.now()).isoformat(timespec="seconds"),
        "estadisticas": dict(resultado.estadisticas),
        "registros": resultado.registros,
    }
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- Excel

def a_excel(resultado: Resultado, ruta: Path, ajustes: Ajustes) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    hoja = libro.active
    hoja.title = (_nombre_seguro(resultado.sitio.nombre)[:31]) or "Datos"
    columnas, tipos = resultado.columnas, resultado.tipos

    hoja.append([_encabezado(c) for c in columnas])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E78")
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for registro in resultado.registros:
        hoja.append([registro.get(c) for c in columnas])

    formatos = {"precio": '"$" #,##0.00', "numero": "#,##0.##", "entero": "#,##0", "fecha": "DD/MM/YYYY"}
    for indice, columna in enumerate(columnas, start=1):
        letra = get_column_letter(indice)
        tipo = tipos.get(columna, "texto")
        largo = len(_encabezado(columna))
        for (celda,) in hoja.iter_rows(min_row=2, min_col=indice, max_col=indice):
            if celda.value is None:
                continue
            if tipo in formatos:
                celda.number_format = formatos[tipo]
            if tipo == "url":
                celda.hyperlink = str(celda.value)
                celda.font = Font(color="0563C1", underline="single")
            largo = max(largo, len(valor_legible(celda.value, tipo)))
        hoja.column_dimensions[letra].width = min(max(largo + 2, 10), 60)

    hoja.freeze_panes = "A2"
    if columnas:
        hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{max(hoja.max_row, 1)}"

    info = libro.create_sheet("Info")
    for fila in [[resultado.titulo], *[[m] for m in _metadatos(resultado)],
                 [f"Resumen: {resultado.resumen()}"]]:
        info.append(fila)
    info["A1"].font = Font(bold=True, size=13)
    info.column_dimensions["A"].width = 100
    libro.save(ruta)


# --------------------------------------------------------------------------- Word

def a_word(resultado: Resultado, ruta: Path, ajustes: Ajustes) -> None:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt, RGBColor

    documento = Document()
    columnas, tipos = resultado.columnas, resultado.tipos
    seccion = documento.sections[0]
    if len(columnas) > 5:  # muchas columnas: hoja apaisada
        seccion.orientation = WD_ORIENT.LANDSCAPE
        seccion.page_width, seccion.page_height = seccion.page_height, seccion.page_width
    for margen in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(seccion, margen, Cm(1.5))

    documento.add_heading(resultado.titulo, level=1)
    for linea in _metadatos(resultado):
        documento.add_paragraph(linea).paragraph_format.space_after = Pt(0)
    documento.add_paragraph()

    if not resultado.registros:
        documento.add_paragraph("No se encontraron registros.")
    else:
        tabla = documento.add_table(rows=1, cols=len(columnas))
        tabla.style = "Light Grid Accent 1"
        for celda, columna in zip(tabla.rows[0].cells, columnas):
            celda.text = _encabezado(columna)
            for run in celda.paragraphs[0].runs:
                run.font.bold = True
        for registro in resultado.registros:
            celdas = tabla.add_row().cells
            for celda, columna in zip(celdas, columnas):
                celda.text = valor_legible(registro.get(columna), tipos.get(columna, "texto"))
        for fila in tabla.rows:
            for celda in fila.cells:
                for parrafo in celda.paragraphs:
                    for run in parrafo.runs:
                        run.font.size = Pt(8)

    pie = documento.add_paragraph(f"Resumen técnico: {resultado.resumen()}")
    for run in pie.runs:
        run.font.size = Pt(7)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    documento.save(ruta)


# --------------------------------------------------------------------------- PDF

def a_pdf(resultado: Resultado, ruta: Path, ajustes: Ajustes) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    columnas, tipos = resultado.columnas, resultado.tipos
    tamano = landscape(A4) if len(columnas) > 5 else A4
    doc = SimpleDocTemplate(str(ruta), pagesize=tamano, leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm, title=resultado.titulo,
                            author="markbackend scraper")
    estilos = getSampleStyleSheet()
    celda = estilos["BodyText"].clone("celda", fontSize=7, leading=8.5)
    cabecera = celda.clone("cabecera", fontName="Helvetica-Bold", textColor=colors.white)

    historia: list[Any] = [Paragraph(escape(resultado.titulo), estilos["Title"])]
    for linea in _metadatos(resultado):
        historia.append(Paragraph(escape(linea), estilos["Normal"]))
    historia.append(Spacer(1, 0.4 * cm))

    if not resultado.registros:
        historia.append(Paragraph("No se encontraron registros.", estilos["Normal"]))
    else:
        filas = [[Paragraph(escape(_encabezado(c)), cabecera) for c in columnas]]
        for registro in resultado.registros:
            filas.append([Paragraph(escape(valor_legible(registro.get(c), tipos.get(c, "texto"))), celda)
                          for c in columnas])
        disponible = tamano[0] - doc.leftMargin - doc.rightMargin
        anchos = _anchos_pdf(columnas, tipos, resultado.registros, disponible, celda.fontSize)
        tabla = Table(filas, colWidths=anchos, repeatRows=1)
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF3F8")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B0B7C3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        historia.append(tabla)

    def numerar(lienzo, documento):
        lienzo.setFont("Helvetica", 7)
        lienzo.drawRightString(tamano[0] - 1.2 * cm, 0.7 * cm, f"Página {documento.page}")

    doc.build(historia, onFirstPage=numerar, onLaterPages=numerar)


def _anchos_pdf(columnas: list[str], tipos: dict[str, str], registros: list[dict[str, Any]],
                disponible: float, tamano_fuente: float) -> list[float]:
    """Anchos de columna en puntos, midiendo el texto real.

    Mínimo de cada columna: que no se partan los valores cortos (precios, fechas, códigos) ni las
    palabras del encabezado. El espacio sobrante se reparte según lo que pediría el texto completo."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    relleno = 6 * 2  # padding izquierdo + derecho de cada celda de Table
    minimos, deseados = [], []
    for columna in columnas:
        textos = [valor_legible(r.get(columna), tipos.get(columna, "texto")) for r in registros]
        cortos = [t for t in textos if len(t) <= 16] + _encabezado(columna).split()
        palabras = [p[:30] for t in textos for p in t.split()]
        minimo = max(stringWidth(t, "Helvetica-Bold", tamano_fuente) for t in cortos + palabras + ["0000"])
        anchos_texto = sorted(stringWidth(t, "Helvetica", tamano_fuente) for t in textos) or [0]
        deseado = max(anchos_texto[len(anchos_texto) * 9 // 10], minimo)
        minimos.append(minimo + relleno)
        deseados.append(min(deseado, disponible * 0.4) + relleno)

    if sum(deseados) <= disponible:  # entra todo: se agranda proporcionalmente
        return [d * disponible / sum(deseados) for d in deseados]
    if sum(minimos) >= disponible:  # ni los mínimos entran: proporcional a los mínimos
        return [m * disponible / sum(minimos) for m in minimos]
    sobrante = disponible - sum(minimos)
    extras = [d - m for d, m in zip(deseados, minimos)]
    return [m + sobrante * e / sum(extras) for m, e in zip(minimos, extras)]
