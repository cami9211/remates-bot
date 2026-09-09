import os
import re
import smtplib
import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from email.message import EmailMessage


# ============================================================
# CONFIGURACIÓN DE LA BÚSQUEDA
# ============================================================

URL = "https://judiciales.elespectador.com/"

FECHA_INICIAL = "10/08/2026"
FECHA_FINAL = "08/09/2026"

PALABRA_CLAVE = "remate"


# ============================================================
# VARIABLES DE GITHUB
# ============================================================
# Se obtienen desde GitHub Actions.
#
# El script intenta utilizar:
#
# EMAIL_DESTINO
# EMAIL_REMITENTE
# EMAIL_PASSWORD
#
# También acepta:
#
# EMAIL_TO
# EMAIL_FROM
# EMAIL_PASS
#
# para evitar problemas si tus Secrets tienen esos nombres.
# ============================================================

EMAIL_DESTINO = (
    os.getenv("EMAIL_DESTINO")
    or os.getenv("EMAIL_TO")
)

EMAIL_REMITENTE = (
    os.getenv("EMAIL_REMITENTE")
    or os.getenv("EMAIL_FROM")
)

EMAIL_PASSWORD = (
    os.getenv("EMAIL_PASSWORD")
    or os.getenv("EMAIL_PASS")
)


# ============================================================
# VALIDAR VARIABLES
# ============================================================

faltantes = []

if not EMAIL_DESTINO:
    faltantes.append("EMAIL_DESTINO")

if not EMAIL_REMITENTE:
    faltantes.append("EMAIL_REMITENTE")

if not EMAIL_PASSWORD:
    faltantes.append("EMAIL_PASSWORD")


if faltantes:

    raise RuntimeError(
        "Faltan variables de entorno en GitHub Actions: "
        + ", ".join(faltantes)
    )


# ============================================================
# CONFIGURAR SESIÓN HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),

    "Accept-Language": "es-CO,es;q=0.9",

    "Connection": "keep-alive"
})


# ============================================================
# FUNCIÓN PARA MOSTRAR INPUTS
# ============================================================

def mostrar_formulario(soup):

    print("\n" + "=" * 80)
    print("FORMULARIOS ENCONTRADOS")
    print("=" * 80)

    formularios = soup.find_all("form")

    for numero, form in enumerate(formularios):

        print(
            f"\nFormulario #{numero}"
        )

        print(
            "Action:",
            form.get("action")
        )

        print(
            "Method:",
            form.get("method")
        )

        for elemento in form.find_all(
            ["input", "select", "button"]
        ):

            print(
                elemento.name,
                "| name=",
                elemento.get("name"),
                "| id=",
                elemento.get("id"),
                "| type=",
                elemento.get("type"),
                "| value=",
                elemento.get("value"),
                "| placeholder=",
                elemento.get("placeholder")
            )


# ============================================================
# FUNCIÓN PARA IDENTIFICAR EL FORMULARIO
# ============================================================

def encontrar_formulario(soup):

    formularios = soup.find_all("form")

    for form in formularios:

        texto = form.get_text(
            " ",
            strip=True
        ).lower()

        if (
            "palabra clave" in texto
            or "palabra" in texto
            or "fecha inicio" in texto
            or "fecha fin" in texto
            or "buscar" in texto
        ):

            return form

    return None


# ============================================================
# FUNCIÓN PARA IDENTIFICAR CAMPOS
# ============================================================

def identificar_campos(form):

    campo_palabra = None
    campo_inicio = None
    campo_fin = None

    elementos = form.find_all(
        ["input", "select"]
    )

    for elemento in elementos:

        name = (
            elemento.get("name")
            or ""
        ).lower()

        id_ = (
            elemento.get("id")
            or ""
        ).lower()

        placeholder = (
            elemento.get("placeholder")
            or ""
        ).lower()

        aria = (
            elemento.get("aria-label")
            or ""
        ).lower()

        texto = (
            name
            + " "
            + id_
            + " "
            + placeholder
            + " "
            + aria
        )

        # ----------------------------------------
        # PALABRA CLAVE
        # ----------------------------------------

        if (
            "palabra" in texto
            or "keyword" in texto
            or "search" in texto
            or "busqueda" in texto
            or "búsqueda" in texto
        ):

            if not campo_palabra:
                campo_palabra = elemento.get("name")


        # ----------------------------------------
        # FECHA INICIAL
        # ----------------------------------------

        if (
            "fecha_inicio" in texto
            or "fecha-inicio" in texto
            or "fechainicio" in texto
            or "inicio" in texto
            or "desde" in texto
            or "start" in texto
        ):

            if not campo_inicio:
                campo_inicio = elemento.get("name")


        # ----------------------------------------
        # FECHA FINAL
        # ----------------------------------------

        if (
            "fecha_fin" in texto
            or "fecha-fin" in texto
            or "fechafin" in texto
            or "fin" in texto
            or "hasta" in texto
            or "end" in texto
        ):

            if not campo_fin:
                campo_fin = elemento.get("name")


    return (
        campo_palabra,
        campo_inicio,
        campo_fin
    )


# ============================================================
# OBTENER PÁGINA
# ============================================================

print("\n")
print("=" * 80)
print("AVISOS JUDICIALES - BÚSQUEDA DE REMATES")
print("=" * 80)

print(
    f"\nFecha inicial : {FECHA_INICIAL}"
)

print(
    f"Fecha final   : {FECHA_FINAL}"
)

print(
    f"Palabra clave : {PALABRA_CLAVE}"
)

print(
    "\nAbriendo:",
    URL
)


response = session.get(
    URL,
    timeout=30
)

response.raise_for_status()


print(
    "Página cargada correctamente."
)


# ============================================================
# ANALIZAR HTML
# ============================================================

soup = BeautifulSoup(
    response.text,
    "html.parser"
)


# ============================================================
# ENCONTRAR FORMULARIO
# ============================================================

form = encontrar_formulario(
    soup
)


if form is None:

    mostrar_formulario(
        soup
    )

    raise RuntimeError(
        "No fue posible identificar "
        "el formulario de búsqueda."
    )


print(
    "\nFormulario de búsqueda identificado."
)


# ============================================================
# IDENTIFICAR CAMPOS
# ============================================================

(
    campo_palabra,
    campo_inicio,
    campo_fin
) = identificar_campos(
    form
)


print("\nCampos identificados:")

print(
    "Palabra clave:",
    campo_palabra
)

print(
    "Fecha inicial:",
    campo_inicio
)

print(
    "Fecha final:",
    campo_fin
)


# ============================================================
# VALIDAR CAMPOS
# ============================================================

if not campo_palabra:

    mostrar_formulario(
        soup
    )

    raise RuntimeError(
        "No se encontró el campo "
        "de palabra clave."
    )


if not campo_inicio:

    mostrar_formulario(
        soup
    )

    raise RuntimeError(
        "No se encontró el campo "
        "de fecha inicial."
    )


if not campo_fin:

    mostrar_formulario(
        soup
    )

    raise RuntimeError(
        "No se encontró el campo "
        "de fecha final."
    )


# ============================================================
# CONSTRUIR DATOS
# ============================================================

datos = {}


# Recuperar campos existentes
for elemento in form.find_all("input"):

    name = elemento.get("name")

    if not name:
        continue

    tipo = (
        elemento.get("type")
        or "text"
    ).lower()

    if tipo in (
        "submit",
        "button",
        "reset"
    ):
        continue

    datos[name] = (
        elemento.get("value")
        or ""
    )


# ============================================================
# APLICAR FILTROS
# ============================================================

datos[campo_palabra] = PALABRA_CLAVE

datos[campo_inicio] = FECHA_INICIAL

datos[campo_fin] = FECHA_FINAL


print("\n")
print("=" * 80)
print("FILTROS APLICADOS")
print("=" * 80)

print(
    "Desde:",
    datos[campo_inicio]
)

print(
    "Hasta:",
    datos[campo_fin]
)

print(
    "Texto:",
    datos[campo_palabra]
)


# ============================================================
# ENDPOINT
# ============================================================

action = form.get(
    "action"
)

if not action:

    action = URL


endpoint = urljoin(
    URL,
    action
)


method = (
    form.get("method")
    or "GET"
).upper()


print(
    "\nMétodo:",
    method
)

print(
    "Endpoint:",
    endpoint
)


# ============================================================
# EJECUTAR BÚSQUEDA
# ============================================================

print(
    "\nEjecutando búsqueda..."
)


if method == "POST":

    resultado = session.post(
        endpoint,
        data=datos,
        timeout=30
    )

else:

    resultado = session.get(
        endpoint,
        params=datos,
        timeout=30
    )


resultado.raise_for_status()


print(
    "Búsqueda ejecutada correctamente."
)


print(
    "URL final:",
    resultado.url
)


# ============================================================
# ANALIZAR RESULTADOS
# ============================================================

resultado_soup = BeautifulSoup(
    resultado.text,
    "html.parser"
)


# ============================================================
# EXTRAER ENLACES
# ============================================================

resultados = []


for enlace in resultado_soup.find_all(
    "a",
    href=True
):

    href = enlace.get(
        "href"
    )

    texto = enlace.get_text(
        " ",
        strip=True
    )

    if not texto:
        continue

    url_resultado = urljoin(
        resultado.url,
        href
    )


    # Ignorar enlaces internos
    if (
        url_resultado == resultado.url
    ):
        continue


    # Evitar enlaces vacíos
    if (
        href.startswith("#")
        or href.startswith("javascript:")
    ):
        continue


    resultados.append({
        "titulo": texto,
        "url": url_resultado
    })


# ============================================================
# ELIMINAR DUPLICADOS
# ============================================================

resultados_unicos = {}

for item in resultados:

    resultados_unicos[
        item["url"]
    ] = item


resultados = list(
    resultados_unicos.values()
)


print(
    "\nCantidad de enlaces encontrados:",
    len(resultados)
)


# ============================================================
# FILTRAR POSIBLES RESULTADOS
# ============================================================

resultados_filtrados = []


for item in resultados:

    titulo = item["titulo"].lower()

    url = item["url"].lower()

    if (
        PALABRA_CLAVE.lower()
        in titulo
        or "judicial" in url
        or "remate" in url
    ):

        resultados_filtrados.append(
            item
        )


# Si no encontramos enlaces específicos,
# utilizamos todos los enlaces obtenidos.

if not resultados_filtrados:

    resultados_filtrados = resultados


# ============================================================
# OBTENER DETALLE
# ============================================================

resultados_completos = []


for numero, item in enumerate(
    resultados_filtrados,
    start=1
):

    print(
        f"\nProcesando resultado "
        f"{numero}/{len(resultados_filtrados)}"
    )

    try:

        detalle = session.get(
            item["url"],
            timeout=30
        )

        detalle.raise_for_status()

        detalle_soup = BeautifulSoup(
            detalle.text,
            "html.parser"
        )


        # Eliminar scripts y estilos
        for elemento in detalle_soup(
            ["script", "style", "noscript"]
        ):

            elemento.decompose()


        texto = detalle_soup.get_text(
            "\n",
            strip=True
        )


        resultados_completos.append({
            "titulo": item["titulo"],
            "url": item["url"],
            "texto": texto
        })


    except Exception as error:

        print(
            "No se pudo procesar:",
            item["url"]
        )

        print(
            "Error:",
            error
        )


# ============================================================
# IMPRIMIR RESULTADOS
# ============================================================

print("\n")
print("=" * 80)
print("RESULTADOS")
print("=" * 80)


if not resultados_completos:

    print(
        "\nNo se encontraron resultados."
    )

else:

    for numero, item in enumerate(
        resultados_completos,
        start=1
    ):

        print("\n")
        print("-" * 80)

        print(
            f"RESULTADO #{numero}"
        )

        print("-" * 80)

        print(
            "TÍTULO:",
            item["titulo"]
        )

        print(
            "URL:",
            item["url"]
        )

        print("\n")

        print(
            item["texto"]
        )


# ============================================================
# GENERAR ARCHIVO
# ============================================================

ARCHIVO = "resultados_remates.txt"


with open(
    ARCHIVO,
    "w",
    encoding="utf-8"
) as archivo:

    archivo.write(
        "REPORTE DE AVISOS JUDICIALES\n"
    )

    archivo.write(
        "=" * 80
        + "\n\n"
    )

    archivo.write(
        f"Fecha inicial: "
        f"{FECHA_INICIAL}\n"
    )

    archivo.write(
        f"Fecha final: "
        f"{FECHA_FINAL}\n"
    )

    archivo.write(
        f"Palabra clave: "
        f"{PALABRA_CLAVE}\n"
    )

    archivo.write(
        f"Total resultados: "
        f"{len(resultados_completos)}\n"
    )

    archivo.write(
        "\n"
    )

    archivo.write(
        "=" * 80
        + "\n"
    )


    for numero, item in enumerate(
        resultados_completos,
        start=1
    ):

        archivo.write(
            f"\n\nRESULTADO #{numero}\n"
        )

        archivo.write(
            "-" * 80
            + "\n"
        )

        archivo.write(
            f"TÍTULO: "
            f"{item['titulo']}\n"
        )

        archivo.write(
            f"URL: "
            f"{item['url']}\n\n"
        )

        archivo.write(
            item["texto"]
        )

        archivo.write(
            "\n"
        )


print(
    f"\nReporte generado: {ARCHIVO}"
)


# ============================================================
# ENVIAR CORREO
# ============================================================

print(
    "\nEnviando correo..."
)


mensaje = EmailMessage()


mensaje["Subject"] = (
    "Remates Colombia | "
    f"{FECHA_INICIAL} - "
    f"{FECHA_FINAL}"
)


mensaje["From"] = (
    EMAIL_REMITENTE
)


mensaje["To"] = (
    EMAIL_DESTINO
)


mensaje.set_content(
    f"""
REPORTE DE AVISOS JUDICIALES

Palabra clave:
{PALABRA_CLAVE}

Rango de fechas:
{FECHA_INICIAL} al {FECHA_FINAL}

Resultados encontrados:
{len(resultados_completos)}

El reporte completo se encuentra
adjunto en este correo.
"""
)


# ============================================================
# ADJUNTAR REPORTE
# ============================================================

with open(
    ARCHIVO,
    "rb"
) as archivo:

    mensaje.add_attachment(
        archivo.read(),
        maintype="text",
        subtype="plain",
        filename=ARCHIVO
    )


# ============================================================
# ENVIAR CON GMAIL
# ============================================================

try:

    with smtplib.SMTP(
        "smtp.gmail.com",
        587
    ) as servidor:

        servidor.ehlo()

        servidor.starttls()

        servidor.ehlo()

        servidor.login(
            EMAIL_REMITENTE,
            EMAIL_PASSWORD
        )

        servidor.send_message(
            mensaje
        )


    print(
        "\nCorreo enviado correctamente."
    )


except Exception as error:

    print(
        "\nERROR ENVIANDO CORREO:"
    )

    print(
        error
    )

    raise


# ============================================================
# FIN
# ============================================================

print("\n")
print("=" * 80)
print("PROCESO TERMINADO")
print("=" * 80)
