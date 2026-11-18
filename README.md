# Scraper a Excel, Word y PDF

Plano (plantilla base) de **markbackend** para trabajos de extracción de datos web. Cada sitio se
describe en un archivo YAML (URL, selectores CSS, paginación, detalle) y el programa genera CSV, Excel
con formato, informe Word, PDF y JSON. No hace falta tocar código Python para un sitio nuevo: se escribe
un YAML.

```
python -m scraper correr sitios/ejemplo.yaml --formato excel,pdf
```

## Qué resuelve

- Recorre el listado de un sitio, página por página (enlace "Siguiente" o número de página).
- Saca de cada elemento los campos que se definan (texto, atributos, precios, fechas, enlaces, imágenes).
- Opcionalmente entra a la ficha de cada elemento y suma campos del detalle.
- Limpia los datos: espacios, `$ 1.234,50` → `1234.5`, `3 de marzo de 2025` → fecha, URLs absolutas.
- Quita duplicados y descarta elementos sin los campos obligatorios.
- Es "educado" con el sitio: respeta `robots.txt` (y su Crawl-delay), espera entre pedidos, reintenta con
  espera creciente ante 429/5xx, User-Agent configurable y caché local para no pedir dos veces lo mismo.
- Exporta a **CSV** (UTF-8 con BOM, `;`), **Excel** (encabezado con color, anchos, filtros, panel fijo,
  formato de moneda y fecha, enlaces clicables, hoja "Info"), **Word** (informe con título, fuente, fecha
  y tabla), **PDF** (tabla con encabezado repetido en cada página y número de página) y **JSON**.
- Páginas armadas con JavaScript: opcional con Playwright (`javascript: true`), desactivado por defecto.

### Pedidos reales de Workana que cubre

- "Necesito extraer datos de una web a Excel" (catálogo, directorio, listado de precios).
- "Automatizar la extracción de información a documentos Word/PDF" (informe periódico con tabla).
- "Scraping de comercios / tiendas online para comparar precios" (precio, stock, SKU, categoría).
- "Sacar los productos de un e-commerce con su ficha (descripción, marca, stock)" → listado + detalle.
- "Juntar noticias / publicaciones de un portal y mandarlas en PDF cada semana" → paginación por número
  + tarea programada.
- "Pasar un catálogo web a CSV para importarlo en mi tienda" → CSV con separador configurable.

## Estructura

```
scraper/
  cli.py             comandos: correr, muestra, robots, validar, demo
  config.py          lectura y validación del YAML + ajustes por variables de entorno
  cliente.py         HTTP: robots.txt, demora, reintentos, caché, User-Agent, Playwright opcional
  robots.py          interpreta robots.txt y muestra qué reglas aplican
  extractor.py       selectores CSS -> campos; enlace "siguiente" y URLs por número
  limpieza.py        textos, números/precios, enteros, fechas, URLs
  motor.py           recorre páginas, deduplica, entra al detalle, junta estadísticas
  exportar.py        CSV, Excel, Word, PDF y JSON
  servidor_local.py  servidor HTTP local para la demo y las pruebas
sitios/
  demo.yaml          sitio local de ejemplo (paginación "siguiente" + detalle)
  demo_noticias.yaml sitio local (paginación por número)
  ejemplo.yaml       books.toscrape.com, sitio público hecho para practicar scraping
tests/               pruebas (sin internet) y tests/sitio_demo/ con el HTML del sitio de ejemplo
```

## Instalación (Windows, Python 3.12)

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
copy .env.example .env        # opcional
```

En Linux/Mac: `python3.12 -m venv .venv` y `.venv/bin/python` en lugar de `.venv/Scripts/python.exe`.

Solo si el sitio necesita JavaScript:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-js.txt
.venv/Scripts/python.exe -m playwright install chromium
```

## Probarlo en 1 minuto (demo, sin internet ni cuentas)

```powershell
.venv/Scripts/python.exe -m scraper demo
```

Levanta un sitio de ferretería de prueba en `127.0.0.1` (3 páginas, fichas de detalle, un producto
repetido, uno sin título y una ficha en `/privado/` que `robots.txt` bloquea), lo scrapea, muestra la
tabla en consola y deja en `salidas/demo/` los archivos `ferreteria_demo.csv/.xlsx/.docx/.pdf/.json`.

## Uso

```powershell
# 1) validar el YAML sin hacer pedidos
.venv/Scripts/python.exe -m scraper validar sitios/ejemplo.yaml

# 2) ver qué permite robots.txt (y probar URLs puntuales)
.venv/Scripts/python.exe -m scraper robots sitios/ejemplo.yaml --probar https://books.toscrape.com/catalogue/x.html

# 3) probar los selectores en la primera página (muestra una tabla y avisa campos vacíos)
.venv/Scripts/python.exe -m scraper muestra sitios/ejemplo.yaml

# 4) correr y exportar
.venv/Scripts/python.exe -m scraper correr sitios/ejemplo.yaml --formato excel,pdf
.venv/Scripts/python.exe -m scraper correr sitios/ejemplo.yaml --formato todos --salida informes/ --max-paginas 5
```

Opciones de `correr`: `--formato` (`csv,excel,word,pdf,json` o `todos`), `--salida`, `--nombre`,
`--url` (pisa `url_inicial`), `--max-paginas`, `--max-registros`, `--sin-cache`.
Códigos de salida: `0` bien, `1` error de configuración, `2` error de red/exportación.

### El archivo YAML de un sitio

```yaml
nombre: Mi tienda
url_inicial: https://tienda.com/productos?page=1
decimal: ","                 # separador decimal del sitio ("," Argentina, "." sitios en inglés)
javascript: false            # true = Playwright (requirements-js.txt)
# esperar_selector: div.producto   # con javascript: espera a que aparezca

lista:
  selector: div.producto     # un elemento por registro

campos:
  titulo: {selector: h2, requerido: true}       # si falta, se descarta el elemento
  precio: {selector: .precio, tipo: precio}     # texto | numero | precio | entero | fecha | url
  sku:    {atributo: data-sku}                  # sin selector = atributo del propio elemento
  imagen: {selector: img, atributo: src, tipo: url}
  fecha:  {selector: .fecha, tipo: fecha, formato_fecha: "%d/%m/%Y"}
  metros: {selector: .info, regex: '(\d+)\s*m²', tipo: entero}
  etiquetas: {selector: .tag, todos: true}      # junta todos: "a | b | c"
  enlace: {selector: a, atributo: href, tipo: url, exportar: false}   # se usa pero no se exporta
  categoria: span.categoria                     # forma corta

paginacion:
  tipo: siguiente            # siguiente | numero | ninguna
  selector: a.next           # para "siguiente"
  # plantilla: "?page={n}"   # para "numero" (relativa a url_inicial), con desde/hasta opcionales
  max_paginas: 20

detalle:                     # opcional: entra a la ficha de cada elemento
  enlace: enlace
  campos:
    descripcion: div.descripcion
    stock: {selector: .stock, tipo: entero}

deduplicar_por: [enlace]     # si no se indica, se usan todos los campos de la lista
max_registros: 0             # 0 = sin límite

opciones:                    # pisa las variables de entorno solo para este sitio
  demora_segundos: 2

salida:
  nombre_archivo: productos_tienda
  titulo_informe: Relevamiento de precios
```

Los errores del YAML se explican en español (campo, clave mal escrita, tipo inválido, etc.).

## Configuración (variables de entorno)

Ver `.env.example`. Precedencia: valores por defecto < `.env`/entorno < `opciones:` del YAML.

| Variable | Defecto | Para qué |
|---|---|---|
| `SCRAPER_USER_AGENT` | `MarkScraper/1.0 (...)` | identificación del bot |
| `SCRAPER_DEMORA_SEGUNDOS` | `1.0` | pausa mínima entre pedidos |
| `SCRAPER_REINTENTOS` / `SCRAPER_ESPERA_REINTENTO` | `3` / `2.0` | reintentos con espera que se duplica (respeta `Retry-After`) |
| `SCRAPER_TIMEOUT_SEGUNDOS` | `20` | tiempo máximo por pedido |
| `SCRAPER_RESPETAR_ROBOTS` | `1` | `0` solo con permiso del dueño del sitio |
| `SCRAPER_CACHE_DIR` / `SCRAPER_CACHE_HORAS` | `.cache` / `24` | caché local (`0` = sin caché) |
| `SCRAPER_SALIDA_DIR` | `salidas` | carpeta de archivos generados |
| `SCRAPER_MAX_PAGINAS` | `50` | tope de páginas de listado |
| `SCRAPER_CSV_SEPARADOR` / `SCRAPER_CSV_DECIMAL` | `;` / `,` | formato del CSV |
| `SCRAPER_LOG_NIVEL` | `INFO` | `DEBUG` muestra cada pedido |

## Pruebas

```powershell
.venv/Scripts/python.exe -m pytest
```

90 pruebas, sin internet ni claves: las del cliente HTTP usan `httpx.MockTransport` (reintentos, 429 con
`Retry-After`, errores de red, demora con reloj falso, caché, robots.txt con 200/403/404/500, User-Agent);
las de punta a punta levantan `tests/sitio_demo/` en un servidor local (paginación "siguiente" y por número,
detalle, duplicados, descartados, bloqueo por robots, bucles de paginación, errores a mitad de camino) y
verifican el contenido de los Excel/Word/CSV/PDF/JSON generados y los comandos de la CLI.

## Despliegue

Es un programa de línea de comandos; "desplegar" es dejarlo corriendo solo cada tanto.

- **Windows (PC del cliente)**: Programador de tareas → Crear tarea básica → Programa:
  `C:\ruta\.venv\Scripts\python.exe`, argumentos `-m scraper correr sitios\cliente.yaml --formato excel,pdf`,
  "Iniciar en": la carpeta del proyecto.
- **Linux / VPS** (cron, todos los días 7:00):
  `0 7 * * * cd /opt/scraper && .venv/bin/python -m scraper correr sitios/cliente.yaml --formato excel,pdf >> scraper.log 2>&1`
- **Entregar archivos**: apuntar `SCRAPER_SALIDA_DIR` a una carpeta sincronizada (OneDrive, Google Drive,
  Dropbox) es lo más simple. Si piden mail o Google Sheets, es una adaptación aparte (ver abajo).
- Con Playwright en servidor Linux: `python -m playwright install --with-deps chromium`.

## CÓMO ADAPTARLO A UN CLIENTE

| # | Qué cambiar | Archivo | Tiempo |
|---|---|---|---|
| 1 | Confirmar que el sitio se puede scrapear: términos de uso, `python -m scraper robots ...`, si hay datos personales | — | 15 min |
| 2 | Copiar `sitios/ejemplo.yaml` a `sitios/<cliente>.yaml`, poner `url_inicial`, `decimal` y `lista.selector` (F12 → Inspeccionar en el navegador) | `sitios/<cliente>.yaml` | 15-30 min |
| 3 | Definir los campos que pidió el cliente con su `tipo`; iterar con `python -m scraper muestra` hasta que no queden vacíos | `sitios/<cliente>.yaml` | 30-60 min |
| 4 | Paginación (`siguiente` o `numero`) y `max_paginas`; probar con `--max-paginas 2` | `sitios/<cliente>.yaml` | 15 min |
| 5 | Detalle (si pide datos de la ficha) y `deduplicar_por` | `sitios/<cliente>.yaml` | 20-40 min |
| 6 | Si el listado no aparece en `muestra` pero sí en el navegador: `javascript: true` + `esperar_selector` | `sitios/<cliente>.yaml`, `requirements-js.txt` | 30-60 min |
| 7 | Título del informe, nombre de archivos, User-Agent con contacto, demora | YAML (`salida`, `opciones`) y `.env` | 10 min |
| 8 | Formato especial de Excel/Word/PDF (logo, columnas renombradas, totales, otra hoja) | `scraper/exportar.py` | 30-90 min |
| 9 | Fechas o precios con formatos raros: `formato_fecha` o `regex` en el campo; si no alcanza, `scraper/limpieza.py` | YAML / `limpieza.py` | 10-30 min |
| 10 | Programar la corrida y la carpeta de salida | Programador de tareas / cron, `.env` | 20 min |
| 11 | Sumar 2-3 pruebas con HTML guardado del sitio del cliente (copiar el patrón de `tests/test_extractor.py`) | `tests/` | 30 min |

Total típico: **2 a 6 horas** según cantidad de campos, si hay detalle y si hace falta JavaScript.

Extras que suelen pedir (cotizar aparte): envío por mail, subir a Google Sheets, guardar histórico en
base de datos para comparar precios entre corridas, login en el sitio (solo con cuenta y permiso del cliente).

## Qué preguntarle al cliente

1. ¿Cuál es la URL exacta y qué datos (columnas) necesitás? ¿Me pasás un ejemplo de cómo querés el Excel/informe?
2. ¿Cuántos registros/páginas son aproximadamente? ¿Todo el sitio o una categoría?
3. ¿Hace falta entrar a la ficha de cada producto/aviso o alcanza con lo que se ve en el listado?
4. ¿Es una sola vez o tiene que correr periódicamente? ¿Con qué frecuencia y dónde querés recibir los archivos?
5. ¿El sitio pide usuario y contraseña para ver los datos? ¿Tenés permiso del dueño del sitio o es tuyo?
6. ¿Qué formato preferís (Excel, Word, PDF, CSV para importar en otro sistema)? ¿Con logo o formato especial?
7. ¿Los datos incluyen información de personas (nombres, teléfonos, mails)? ¿Para qué se van a usar?
8. ¿Qué hacemos si el sitio cambia el diseño? (mantenimiento mensual o ajuste por pedido)

## Aviso legal

- Usá este programa solo en sitios donde esté permitido: leé los **términos y condiciones** del sitio y
  respetá `robots.txt` (el programa lo hace por defecto). Algunos sitios prohíben expresamente la extracción
  automática; en ese caso no se hace o se pide permiso por escrito.
- **Ley 25.326 de Protección de Datos Personales (Argentina)**: no juntar datos personales (nombres, DNI,
  teléfonos, mails, domicilios) sin una base legal (consentimiento del titular, fuente de acceso público
  irrestricto con finalidad compatible, etc.). Si el trabajo incluye datos de personas, el cliente es
  responsable de la base de datos y de su inscripción/uso conforme a la ley; recomendamos limitarse a datos
  de comercios/productos o anonimizar.
- No sobrecargar los servidores: mantener la demora entre pedidos (1 s o más) y no correr en paralelo
  contra el mismo sitio.
- No saltear logins, captchas ni medidas técnicas de protección.
- Este plano se entrega "tal cual" bajo licencia MIT (ver `LICENSE`); el uso que se haga con cada sitio es
  responsabilidad de quien lo ejecuta.
