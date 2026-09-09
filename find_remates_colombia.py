import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime
import smtplib
from email.message import EmailMessage
import os
import re


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL = "https://judiciales.elespectador.com/"

FECHA_INICIAL = "10/08/2026"
FECHA_FINAL = "08/09/2026"

PALABRA_CLAVE = "remate"

# Correo destino
EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]

# Correo desde el cual se envía
EMAIL_REMITENTE = os.environ["EMAIL_REMITENTE"]

# Contraseña de aplicación
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]


# ============================================================
# SESIÓN HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
})


# ============================================================
# OBTENER PÁGINA
# ============================================================

print("Abriendo página...")

response = session.get(
    URL,
    timeout=30
)

response.raise_for_status()

print("Página cargada correctamente.")

soup = BeautifulSoup(
    response.text,
    "html.parser"
)


# ============================================================
# MOSTRAR FORMULARIOS
# ============================================================

print("\nFormularios encontrados:")

for i, form in enumerate(soup.find_all("form")):

    print(
        i,
        "action=",
        form.get("action"),
        "method=",
        form.get("method")
    )


# ============================================================
# BUSCAR FORMULARIO PRINCIPAL
# ============================================================

form = None

for f in soup.find_all("form"):

    texto = f.get_text(
        " ",
        strip=True
    ).lower()

    if (
        "palabra" in texto
        or "buscar" in texto
        or "fecha" in texto
    ):
        form = f
        break


if form is None:

    raise Exception(
        "No se encontró el formulario de búsqueda."
    )


print("\nFormulario seleccionado.")


# ============================================================
# MOSTRAR INPUTS
# ============================================================

print("\nCampos encontrados:")

for inp in form.find_all(
    ["input", "select", "button"]
):

    print(
        inp.name,
        "name=",
        inp.get("name"),
        "id=",
        inp.get("id"),
        "type=",
        inp.get("type"),
        "value=",
        inp.get("value")
    )


# ============================================================
# OBTENER ACTION
# ============================================================

action = form.get("action")

if not action:
    action = URL

endpoint = urljoin(
    URL,
    action
)

print("\nEndpoint:", endpoint)


# ============================================================
# CONSTRUIR DATOS DEL FORMULARIO
# ============================================================

data = {}

for inp in form.find_all("input"):

    name = inp.get("name")

    if not name:
        continue

    input_type = (
        inp.get("type") or "text"
    ).lower()

    value = inp.get("value", "")

    if input_type in [
        "submit",
        "button",
        "reset"
    ]:
        continue

    data[name] = value


# ============================================================
# IDENTIFICAR CAMPOS
# ============================================================

campo_palabra = None
campo_inicio = None
campo_fin = None


for inp in form.find_all("input"):

    name = (
        inp.get("name") or ""
    ).lower()

    id_ = (
        inp.get("id") or ""
    ).lower()

    placeholder = (
        inp.get("placeholder") or ""
    ).lower()

    identificador = (
        name + " " +
        id_ + " " +
        placeholder
    )

    # Palabra clave
    if (
        "palabra" in identificador
        or "keyword" in identificador
        or "buscar" in identificador
        or "search" in identificador
    ):
        campo_palabra = inp.get("name")

    # Fecha inicial
    if (
        "inicio" in identificador
        or "desde" in identificador
        or "start" in identificador
    ):
        campo_inicio = inp.get("name")

    # Fecha final
    if (
        "fin" in identificador
        or "hasta" in identificador
        or "end" in identificador
    ):
        campo_fin = inp.get("name")


print("\nCampos identificados:")

print(
    "Palabra:",
    campo_palabra
)

print(
    "Fecha inicio:",
    campo_inicio
)

print(
    "Fecha fin:",
    campo_fin
)


# ============================================================
# SI NO SE IDENTIFICAN AUTOMÁTICAMENTE
# MOSTRAR ERROR PARA AJUSTAR
# ============================================================

if campo_palabra is None:

    raise Exception(
        "No se pudo identificar el campo de palabra clave."
    )

if campo_inicio is None:

    raise Exception(
        "No se pudo identificar el campo de fecha inicial."
    )

if campo_fin is None:

    raise Exception(
        "No se pudo identificar el campo de fecha final."
    )


# ============================================================
# COLOCAR VALORES
# ============================================================

data[campo_palabra] = PALABRA_CLAVE

data[campo_inicio] = FECHA_INICIAL

data[campo_fin] = FECHA_FINAL


print("\nDatos de búsqueda:")

print(
    f"Fecha inicial: {FECHA_INICIAL}"
)

print(
    f"Fecha final: {FECHA_FINAL}"
)

print(
    f"Palabra clave: {PALABRA_CLAVE}"
)


# ============================================================
# EJECUTAR BÚSQUEDA
# ============================================================

print("\nEjecutando búsqueda...")


method = (
    form.get("method") or "GET"
).upper()


if method == "POST":

    resultado = session.post(
        endpoint,
        data=data,
        timeout=30
    )

else:

    resultado = session.get(
        endpoint,
        params=data,
        timeout=30
    )


resultado.raise_for_status()


print(
    "Búsqueda ejecutada:",
    resultado.url
)


# ============================================================
# PROCESAR RESULTADOS
# ============================================================

resultado_soup = BeautifulSoup(
    resultado.text,
    "html.parser"
)


# ============================================================
# EXTRAER RESULTADOS
# ============================================================

resultados = []


# Buscar enlaces a detalle
for enlace in resultado_soup.find_all(
    "a",
    href=True
):

    href = enlace.get("href")

    texto = enlace.get_text(
        " ",
        strip=True
    )

    if not texto:
        continue

    if (
        "detalle.php" in href.lower()
        or "detalle" in href.lower()
    ):

        url_detalle = urljoin(
            endpoint,
            href
        )

        resultados.append({
            "titulo": texto,
            "url": url_detalle
        })


# Eliminar duplicados
unicos = {}

for resultado_item in resultados:

    unicos[
        resultado_item["url"]
    ] = resultado_item


resultados = list(
    unicos.values()
)


print(
    f"\nResultados encontrados: {len(resultados)}"
)


# ============================================================
# OBTENER CONTENIDO DE CADA RESULTADO
# ============================================================

resultados_completos = []


for numero, item in enumerate(
    resultados,
    start=1
):

    print(
        f"Procesando {numero}/{len(resultados)}..."
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
            "Error:",
            item["url"],
            error
        )


# ============================================================
# IMPRIMIR RESULTADOS
# ============================================================

print("\n")
print("=" * 80)
print("RESULTADOS DE REMATES")
print("=" * 80)

for i, item in enumerate(
    resultados_completos,
    start=1
):

    print("\n")
    print("=" * 80)

    print(
        f"RESULTADO #{i}"
    )

    print("=" * 80)

    print(
        "Título:",
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
# GENERAR REPORTE
# ============================================================

archivo = "resultados_remates.txt"


with open(
    archivo,
    "w",
    encoding="utf-8"
) as f:

    f.write(
        "REPORTE DE AVISOS JUDICIALES\n"
    )

    f.write(
        "=" * 80 + "\n\n"
    )

    f.write(
        f"Fecha inicial: {FECHA_INICIAL}\n"
    )

    f.write(
        f"Fecha final: {FECHA_FINAL}\n"
    )

    f.write(
        f"Palabra clave: {PALABRA_CLAVE}\n"
    )

    f.write(
        f"Total resultados: "
        f"{len(resultados_completos)}\n\n"
    )

    f.write(
        "=" * 80 + "\n"
    )

    for i, item in enumerate(
        resultados_completos,
        start=1
    ):

        f.write(
            f"\nRESULTADO #{i}\n"
        )

        f.write(
            "-" * 80 + "\n"
        )

        f.write(
            f"Título: {item['titulo']}\n"
        )

        f.write(
            f"URL: {item['url']}\n\n"
        )

        f.write(
            item["texto"]
        )

        f.write(
            "\n\n"
        )


print(
    f"\nReporte generado: {archivo}"
)


# ============================================================
# ENVIAR CORREO
# ============================================================

print("\nEnviando correo...")


mensaje = EmailMessage()

mensaje["Subject"] = (
    f"Remates Colombia | "
    f"{FECHA_INICIAL} - {FECHA_FINAL}"
)

mensaje["From"] = EMAIL_REMITENTE

mensaje["To"] = EMAIL_DESTINO


mensaje.set_content(
    f"""
Se encontraron {len(resultados_completos)}
avisos judiciales relacionados con "{PALABRA_CLAVE}".

Rango consultado:

Desde: {FECHA_INICIAL}
Hasta: {FECHA_FINAL}

El reporte completo se encuentra
adjunto en este correo.
"""
)


with open(
    archivo,
    "rb"
) as f:

    mensaje.add_attachment(
        f.read(),
        maintype="text",
        subtype="plain",
        filename=archivo
    )


# ============================================================
# SMTP GMAIL
# ============================================================

with smtplib.SMTP(
    "smtp.gmail.com",
    587
) as servidor:

    servidor.starttls()

    servidor.login(
        EMAIL_REMITENTE,
        EMAIL_PASSWORD
    )

    servidor.send_message(
        mensaje
    )


print(
    "Correo enviado correctamente."
)

print("\nProceso terminado.")
