"""Limpieza y conversión de valores extraídos: espacios, precios a número, fechas y URLs."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

_ESPACIOS = re.compile(r"\s+")
_NUMERO = re.compile(r"\d[\d.,]*")
_MESES = {
    "enero": 1, "ene": 1, "january": 1, "jan": 1,
    "febrero": 2, "feb": 2, "february": 2,
    "marzo": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "jun": 6, "june": 6,
    "julio": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "set": 9, "september": 9,
    "octubre": 10, "oct": 10, "october": 10,
    "noviembre": 11, "nov": 11, "november": 11,
    "diciembre": 12, "dic": 12, "december": 12, "dec": 12,
}
FORMATOS_FECHA = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%Y/%m/%d"]


def limpiar_texto(valor) -> str | None:
    """Colapsa espacios, saca espacios duros y devuelve None si queda vacío."""
    if valor is None:
        return None
    texto = str(valor).replace("\xa0", " ").replace("​", "").replace(" ", " ")
    texto = _ESPACIOS.sub(" ", texto).strip()
    return texto or None


def a_numero(valor, decimal: str = ",") -> float | None:
    """Convierte '$ 1.234,50', 'USD 1,234.50', '£51.77' o '-3,5 %' a float.

    Si aparecen '.' y ',' manda el último como decimal. Si aparece uno solo, se usa `decimal`
    (el separador decimal del sitio) para decidir si es decimal o de miles.
    """
    texto = limpiar_texto(valor)
    if not texto:
        return None
    # "1 234,50" -> "1234,50" (espacio como separador de miles)
    texto = re.sub(r"(?<=\d) (?=\d{3}\b)", "", texto)
    coincidencia = _NUMERO.search(texto)
    if not coincidencia:
        return None
    numero = coincidencia.group(0).rstrip(".,")
    prefijo = texto[: coincidencia.start()]
    negativo = bool(re.search(r"-\s*(?:[A-Za-z]{0,3}\s*[$€£]?)?\s*$", prefijo))

    tiene_punto, tiene_coma = "." in numero, "," in numero
    if tiene_punto and tiene_coma:
        sep_decimal = "." if numero.rfind(".") > numero.rfind(",") else ","
    elif tiene_punto or tiene_coma:
        sep = "." if tiene_punto else ","
        sep_decimal = sep if (numero.count(sep) == 1 and sep == decimal) else None
    else:
        sep_decimal = None

    if sep_decimal:
        sep_miles = "," if sep_decimal == "." else "."
        numero = numero.replace(sep_miles, "").replace(sep_decimal, ".")
    else:
        numero = numero.replace(".", "").replace(",", "")
    try:
        resultado = float(numero)
    except ValueError:
        return None
    return -resultado if negativo else resultado


def a_entero(valor, decimal: str = ",") -> int | None:
    """'Stock: 12 unidades' -> 12; '1.234' -> 1234."""
    numero = a_numero(valor, decimal)
    return None if numero is None else int(round(numero))


def a_fecha(valor, formatos: list[str] | tuple[str, ...] = (), hoy: date | None = None) -> date | None:
    """Interpreta fechas comunes: '15/03/2025', '2025-03-15', '3 de marzo de 2025', 'Mar 3, 2025',
    'hoy', 'ayer', 'hace 3 días'. Primero prueba los `formatos` del YAML (formato de strptime)."""
    texto = limpiar_texto(valor)
    if not texto:
        return None
    for formato in list(formatos) + FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass

    bajo = texto.lower()
    hoy = hoy or date.today()
    if bajo.startswith("hoy"):
        return hoy
    if bajo.startswith("ayer"):
        return hoy - timedelta(days=1)
    m = re.search(r"hace\s+(\d+)\s+d[ií]as?", bajo)
    if m:
        return hoy - timedelta(days=int(m.group(1)))

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", bajo)  # ISO con hora: 2025-03-15T10:00:00
    if m:
        return _fecha_segura(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-záéíóú]+)\.?,?\s*(?:de\s+|del\s+)?(\d{4})", bajo)
    if m and m.group(2) in _MESES:
        return _fecha_segura(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
    m = re.search(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", bajo)
    if m and m.group(1) in _MESES:
        return _fecha_segura(int(m.group(3)), _MESES[m.group(1)], int(m.group(2)))
    m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", bajo)  # orden argentino: día/mes/año
    if m:
        anio = int(m.group(3))
        anio += 2000 if anio < 100 else 0
        return _fecha_segura(anio, int(m.group(2)), int(m.group(1)))
    return None


def _fecha_segura(anio: int, mes: int, dia: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def a_url(valor, url_base: str) -> str | None:
    texto = limpiar_texto(valor)
    if not texto or texto.startswith(("javascript:", "mailto:", "#")):
        return None
    return urljoin(url_base, texto)


def convertir(valor, tipo: str, decimal: str = ",", formatos_fecha=(), url_base: str = ""):
    """Aplica la conversión que corresponde al `tipo` del campo."""
    if tipo in ("numero", "precio"):
        return a_numero(valor, decimal)
    if tipo == "entero":
        return a_entero(valor, decimal)
    if tipo == "fecha":
        return a_fecha(valor, formatos_fecha)
    if tipo == "url":
        return a_url(valor, url_base)
    return limpiar_texto(valor)
