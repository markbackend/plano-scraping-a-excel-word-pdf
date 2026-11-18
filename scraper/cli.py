"""Línea de comandos.

    python -m scraper correr sitios/ejemplo.yaml --formato excel,pdf
    python -m scraper muestra sitios/ejemplo.yaml         # prueba los selectores en la primera página
    python -m scraper robots sitios/ejemplo.yaml          # muestra qué bloquea robots.txt
    python -m scraper validar sitios/ejemplo.yaml
    python -m scraper demo                                # todo de punta a punta con un sitio local

Códigos de salida: 0 bien, 1 error de configuración, 2 error durante la ejecución.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .cliente import ClienteWeb, ErrorDescarga
from .config import Ajustes, ErrorConfig, Sitio, cargar_sitio
from .exportar import ErrorExportacion, exportar, normalizar_formatos, valor_legible
from .extractor import extraer_items
from .motor import Scraper
from .servidor_local import SITIO_DEMO, cambiar_base, servir_carpeta

log = logging.getLogger("scraper")
RAIZ = Path(__file__).resolve().parent.parent


def _configurar_logs(nivel: str) -> None:
    logging.basicConfig(level=getattr(logging, nivel.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S",
                        force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _preparar(args) -> tuple[Sitio, Ajustes]:
    sitio = cargar_sitio(args.sitio)
    if getattr(args, "url", None):
        sitio.url_inicial = args.url
    ajustes = Ajustes.desde_entorno(sitio.opciones)
    if getattr(args, "max_paginas", None):
        sitio.paginacion.max_paginas = args.max_paginas
    if getattr(args, "max_registros", None):
        sitio.max_registros = args.max_registros
    return sitio, ajustes


def _tabla_consola(registros, columnas, tipos, limite=10) -> str:
    if not registros:
        return "(sin registros)"
    filas = [[valor_legible(r.get(c), tipos.get(c, "texto"))[:40] for c in columnas] for r in registros[:limite]]
    anchos = [max(len(c), *(len(f[i]) for f in filas)) for i, c in enumerate(columnas)]
    lineas = [" | ".join(c.ljust(a) for c, a in zip(columnas, anchos)),
              "-+-".join("-" * a for a in anchos)]
    lineas += [" | ".join(v.ljust(a) for v, a in zip(f, anchos)) for f in filas]
    if len(registros) > limite:
        lineas.append(f"... y {len(registros) - limite} más")
    return "\n".join(lineas)


# --------------------------------------------------------------------------- comandos

def cmd_correr(args) -> int:
    sitio, ajustes = _preparar(args)
    formatos = normalizar_formatos(args.formato)
    if args.sin_cache:
        ajustes.cache_horas = 0
    resultado = Scraper(sitio, ajustes).correr()
    archivos = exportar(resultado, formatos, args.salida or ajustes.salida_dir, ajustes, args.nombre)
    print(f"\n{resultado.resumen()}")
    for error in resultado.errores[:10]:
        print(f"  ! {error}")
    print("Archivos generados:")
    for archivo in archivos:
        print(f"  - {archivo}")
    return 0


def cmd_muestra(args) -> int:
    sitio, ajustes = _preparar(args)
    with ClienteWeb(ajustes) as cliente:
        respuesta = cliente.obtener(sitio.url_inicial, sitio.javascript, sitio.esperar_selector)
    registros, descartados = extraer_items(respuesta.texto, respuesta.url, sitio)
    columnas = [c.nombre for c in sitio.campos]
    print(f"Página: {respuesta.url}\nElementos válidos: {len(registros)} | descartados: {descartados}\n")
    print(_tabla_consola(registros, columnas, sitio.tipos(), limite=args.cantidad))
    vacios = [c for c in columnas if registros and all(r.get(c) in (None, "") for r in registros)]
    if not registros:
        print(f"\nNingún elemento coincide con lista.selector = {sitio.selector_lista!r}")
        return 2
    if vacios:
        print(f"\nAtención: estos campos salieron vacíos en todos los elementos: {', '.join(vacios)}")
    return 0


def cmd_robots(args) -> int:
    sitio, ajustes = _preparar(args)
    ajustes.respetar_robots = True
    with ClienteWeb(ajustes, usar_cache=False) as cliente:
        info = cliente.robots.info(sitio.url_inicial)
        print(f"robots.txt: {info.url}  (estado: {info.estado})")
        print(f"User-Agent: {ajustes.user_agent}")
        if info.crawl_delay:
            print(f"Crawl-delay pedido por el sitio: {info.crawl_delay} s (se respeta)")
        if info.reglas:
            print("Reglas que aplican a nuestro User-Agent:")
            for tipo, ruta in info.reglas:
                print(f"  {tipo}: {ruta or '(vacío = permite todo)'}")
        elif info.estado == "ok":
            print("No hay reglas Allow/Disallow para nuestro User-Agent.")
        print("\nVerificación de URLs:")
        for url in [sitio.url_inicial, *(args.probar or [])]:
            permitido = cliente.robots.permitido(url)
            print(f"  {'PERMITIDA' if permitido else 'BLOQUEADA'}  {url}")
    return 0


def cmd_validar(args) -> int:
    sitio, ajustes = _preparar(args)
    print(f"OK: {sitio.nombre}")
    print(f"  URL inicial: {sitio.url_inicial}")
    print(f"  Lista: {sitio.selector_lista} | campos: {', '.join(c.nombre for c in sitio.campos)}")
    print(f"  Paginación: {sitio.paginacion.tipo} | detalle: "
          f"{', '.join(c.nombre for c in sitio.detalle.campos) if sitio.detalle else 'no'}")
    print(f"  Columnas a exportar: {', '.join(sitio.columnas())}")
    print(f"  Demora: {ajustes.demora_segundos} s | robots.txt: {'sí' if ajustes.respetar_robots else 'NO'} | "
          f"caché: {ajustes.cache_horas} h | JavaScript: {'sí' if sitio.javascript else 'no'}")
    return 0


def cmd_demo(args) -> int:
    """Levanta el sitio de ejemplo local, lo scrapea con sitios/demo.yaml y exporta todo."""
    sitio = cargar_sitio(RAIZ / "sitios" / "demo.yaml")
    ajustes = Ajustes.desde_entorno(sitio.opciones)
    formatos = normalizar_formatos(args.formato)
    with servir_carpeta(SITIO_DEMO) as base:
        sitio.url_inicial = cambiar_base(sitio.url_inicial, base)
        print(f"Sitio de demo levantado en {base}\n")
        with ClienteWeb(ajustes, usar_cache=False) as cliente:
            info = cliente.robots.info(sitio.url_inicial) if cliente.robots else None
            if info:
                print("robots.txt del sitio demo bloquea: "
                      + (", ".join(r for t, r in info.reglas if t == "Disallow") or "nada"))
            resultado = Scraper(sitio, ajustes, cliente).correr()
    print()
    print(_tabla_consola(resultado.registros, resultado.columnas, resultado.tipos, limite=args.cantidad))
    print(f"\n{resultado.resumen()}")
    for error in resultado.errores:
        print(f"  ! {error}")
    archivos = exportar(resultado, formatos, args.salida or Path(ajustes.salida_dir) / "demo", ajustes)
    print("\nArchivos generados:")
    for archivo in archivos:
        print(f"  - {archivo}")
    return 0


# --------------------------------------------------------------------------- argparse

def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scraper",
                                     description="Scraper configurable por YAML que exporta a CSV/Excel/Word/PDF.")
    sub = parser.add_subparsers(dest="comando", required=True)

    def con_sitio(p):
        p.add_argument("sitio", help="archivo YAML del sitio (ver sitios/)")
        p.add_argument("--url", help="reemplaza url_inicial del YAML")
        return p

    p = con_sitio(sub.add_parser("correr", help="extrae los datos y genera los archivos"))
    p.add_argument("--formato", default="excel", help="csv,excel,word,pdf,json o 'todos' (por defecto: excel)")
    p.add_argument("--salida", help="carpeta de salida (por defecto SCRAPER_SALIDA_DIR o 'salidas')")
    p.add_argument("--nombre", help="nombre base de los archivos (por defecto salida.nombre_archivo del YAML)")
    p.add_argument("--max-paginas", type=int)
    p.add_argument("--max-registros", type=int)
    p.add_argument("--sin-cache", action="store_true", help="ignora la caché local")
    p.set_defaults(funcion=cmd_correr)

    p = con_sitio(sub.add_parser("muestra", help="prueba los selectores en la primera página"))
    p.add_argument("--cantidad", type=int, default=5)
    p.set_defaults(funcion=cmd_muestra)

    p = con_sitio(sub.add_parser("robots", help="muestra qué permite y qué bloquea robots.txt"))
    p.add_argument("--probar", nargs="*", help="URLs extra para verificar")
    p.set_defaults(funcion=cmd_robots)

    p = con_sitio(sub.add_parser("validar", help="valida el YAML sin hacer pedidos"))
    p.set_defaults(funcion=cmd_validar)

    p = sub.add_parser("demo", help="demo completa con un sitio local (sin internet)")
    p.add_argument("--formato", default="todos")
    p.add_argument("--salida")
    p.add_argument("--cantidad", type=int, default=15)
    p.set_defaults(funcion=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = crear_parser().parse_args(argv)
    try:
        _configurar_logs(Ajustes.desde_entorno().log_nivel)
        return args.funcion(args)
    except ErrorConfig as exc:
        log.error("Configuración: %s", exc)
        return 1
    except (ErrorDescarga, ErrorExportacion, ValueError) as exc:
        log.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        log.warning("Cancelado por el usuario")
        return 130


if __name__ == "__main__":
    sys.exit(main())
