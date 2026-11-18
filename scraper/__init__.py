"""Scraper configurable por YAML que exporta a CSV, Excel, Word, PDF y JSON (plano de markbackend)."""
from .cliente import BloqueadoPorRobots, ClienteWeb, ErrorDescarga
from .config import Ajustes, ErrorConfig, cargar_sitio
from .exportar import exportar
from .motor import Resultado, Scraper

__all__ = ["Ajustes", "BloqueadoPorRobots", "ClienteWeb", "ErrorConfig", "ErrorDescarga", "Resultado",
           "Scraper", "cargar_sitio", "exportar"]
__version__ = "1.0.0"
