import os
import smtplib
import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from email.message import EmailMessage


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL = "https://judiciales.elespectador.com/"

FECHA_INICIAL = "10/08/2026"
FECHA_FINAL = "08/09/2026"
PALABRA_CLAVE = "remate"

ARCHIVO_REPORTE = "resultados_remates.txt"


# ============================================================
# GITHUB SECRETS
# ============================================================

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")


# ============================================================
# VALIDAR SECRETS
# ============================================================

faltantes = []

if not GMAIL_USER:
    faltantes.append("GMAIL_USER")

if not GMAIL_APP_PASSWORD:
    faltantes.append("GMAIL_APP_PASSWORD")

if not RECIPIENT_EMAIL:
    faltantes.append("RECIPIENT_EMAIL")

if faltantes:
    raise RuntimeError(
        "Faltan Secrets en GitHub Actions: "
        + ", ".join(faltantes)
    )


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
    "Accept-Language": "es-CO,es;q=0.9",
})


# ============================================================
# ABRIR PÁGINA
# ============================================================

print("=" * 80)
print("AVISOS JUDICIALES - EL ESPECTADOR")
print("=" * 80)

print(f"Fecha inicial : {FECHA_INICIAL}")
print(f"Fecha final   : {FECHA_FINAL}")
print(f"Palabra clave : {PALABRA_CLAVE}")
print()

response = session.get(
    URL,
    timeout=30
)

response.raise_for_status()

soup = BeautifulSoup(
    response.text,
    "html.parser"
)

print("Página cargada correctamente.")


# ============================================================
# BUSCAR FORMULARIO
# ============================================================

formularios = soup.find_all("form")

if not formularios:
    raise RuntimeError(
        "La página no contiene formularios."
    )


form = None

for formulario in formularios:

    texto = formulario.get_text(
        " ",
        strip=True
    ).lower()

    if (
        "palabra clave" in texto
        or "buscar" in texto
        or "rango de fecha" in texto
    ):
        form = formulario
        break


if form is None:
    raise RuntimeError(
        "No se encontró el formulario de búsqueda."
    )


print("Formulario encontrado.")


# ============================================================
# MOSTRAR CAMPOS DEL FORMULARIO
# ============================================================

print("\nCampos del formulario:")

for elemento in form.find_all(
    ["input", "select", "button"]
):

    print(
        f"  {elemento.name}"
        f" | name={elemento.get('name')}"
        f" | id={elemento.get('id')}"
        f" | type={elemento.get('type')}"
        f" | value={elemento.get('value')}"
        f" | placeholder={elemento.get('placeholder')}"
    )


# ============================================================
# RECOPILAR CAMPOS
# ============================================================

datos = {}

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
# IDENTIFICAR CAMPOS
# ============================================================

campo_palabra = None
campo_fecha_inicio = None
campo_fecha_fin = None


for elemento in form.find_all(
    ["input", "select"]
):

    name = elemento.get("name")

    if not name:
        continue

    identificador = " ".join([
        str(elemento.get("name") or ""),
        str(elemento.get("id") or ""),
        str(elemento.get("placeholder") or ""),
        str(elemento.get("aria-label") or "")
    ]).lower()


    # -----------------------------------------
    # PALABRA CLAVE
    # -----------------------------------------

    if (
        "palabra" in identificador
        or "keyword" in identificador
        or "search" in identificador
    ):
        campo_palabra = name


    # -----------------------------------------
    # FECHA INICIAL
    # -----------------------------------------

    if (
        "inicio" in identificador
        or "desde" in identificador
        or "start" in identificador
    ):
        campo_fecha_inicio = name


    # -----------------------------------------
    # FECHA FINAL
    # -----------------------------------------

    if (
        "fin" in identificador
        or "hasta" in identificador
        or "end" in identificador
    ):
        campo_fecha_fin = name


# ============================================================
# COMPROBAR CAMPOS
# ============================================================

print("\nCampos identificados:")

print(
    "Palabra clave:",
    campo_palabra
)

print(
    "Fecha inicial:",
    campo_fecha_inicio
)

print(
    "Fecha final:",
    campo_fecha_fin
)


# ============================================================
# SI EL SITIO UTILIZA NOMBRES DIFERENTES,
# INTENTAR IDENTIFICAR INPUTS POR ORDEN
# ============================================================

inputs_texto = []

for elemento in form.find_all("input"):

    tipo = (
        elemento.get("type")
        or "text"
    ).lower()

    if tipo in ("text", "date"):

        inputs_texto.append(
            elemento
        )


# Si no se encontró palabra clave,
# buscar el input de texto que no sea fecha.

if campo_palabra is None:

    for elemento in inputs_texto:

        tipo = (
            elemento.get("type")
            or "text"
        ).lower()

        if tipo == "text":

            campo_palabra = elemento.get(
                "name"
            )

            if campo_palabra:
                break


# ============================================================
# VALIDACIÓN
# ============================================================

if not campo_palabra:

    raise RuntimeError(
        "No fue posible identificar "
        "el campo de palabra clave."
    )

if not campo_fecha_inicio:

    raise RuntimeError(
        "No fue posible identificar "
        "el campo de fecha inicial."
    )

if not campo_fecha_fin:

    raise RuntimeError(
        "No fue posible identificar "
        "el campo de fecha final."
    )


# ============================================================
# COLOCAR FILTROS
# ============================================================

datos[campo_palabra] = PALABRA_CLAVE

datos[campo_fecha_inicio] = FECHA_INICIAL

datos[campo_fecha_fin] = FECHA_FINAL


print("\n" + "=" * 80)
print("FILTROS")
print("=" * 80)

print(
    f"Fecha inicial: {FECHA_INICIAL}"
)

print(
    f"Fecha final:   {FECHA_FINAL}"
)

print(
    f"Palabra:       {PALABRA_CLAVE}"
)


# ============================================================
# ENDPOINT DEL FORMULARIO
# ============================================================

action = form.get("action")

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


print()
print("Método:", method)
print("Endpoint:", endpoint)


# ============================================================
# REALIZAR BÚSQUEDA
# ============================================================

print("\nEjecutando búsqueda...")


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
    "Búsqueda realizada correctamente."
)

print(
    "URL resultante:",
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
# EXTRAER RESULTADOS VISIBLES
# ============================================================

resultados = []


# Buscar bloques que contengan "remate".
# Esto permite trabajar incluso si el sitio
# no utiliza enlaces con nombres predecibles.

bloques = resultado_soup.find_all(
    ["article", "div", "li"]
)


for bloque in bloques:

    texto = bloque.get_text(
        " ",
        strip=True
    )

    if not texto:
        continue

    if PALABRA_CLAVE.lower() not in texto.lower():
        continue

    enlace = bloque.find(
        "a",
        href=True
    )

    if enlace:

        titulo = enlace.get_text(
            " ",
            strip=True
        )

        url = urljoin(
            resultado.url,
            enlace["href"]
        )

    else:

        titulo = texto[:300]
        url = resultado.url


    resultados.append({
        "titulo": titulo,
        "url": url,
        "texto": texto
    })


# ============================================================
# ELIMINAR DUPLICADOS
# ============================================================

unicos = {}

for resultado_item in resultados:

    clave = (
        resultado_item["titulo"],
        resultado_item["url"]
    )

    unicos[clave] = resultado_item


resultados = list(
    unicos.values()
)


# ============================================================
# IMPRIMIR RESULTADOS
# ============================================================

print("\n" + "=" * 80)
print("RESULTADOS ENCONTRADOS")
print("=" * 80)

print(
    f"Total: {len(resultados)}"
)


if not resultados:

    print(
        "\nNo se encontraron resultados."
    )

else:

    for numero, item in enumerate(
        resultados,
        start=1
    ):

        print("\n")
        print("-" * 80)

        print(
            f"RESULTADO #{numero}"
        )

        print("-" * 80)

        print(
            "Título:",
            item["titulo"]
        )

        print(
            "URL:",
            item["url"]
        )

        print(
            "Texto:",
            item["texto"]
        )


# ============================================================
# CREAR REPORTE
# ============================================================

with open(
    ARCHIVO_REPORTE,
    "w",
    encoding="utf-8"
) as archivo:

    archivo.write(
        "REPORTE DE AVISOS JUDICIALES\n"
    )

    archivo.write(
        "=" * 80 + "\n\n"
    )

    archivo.write(
        f"Fecha inicial: {FECHA_INICIAL}\n"
    )

    archivo.write(
        f"Fecha final: {FECHA_FINAL}\n"
    )

    archivo.write(
        f"Palabra clave: {PALABRA_CLAVE}\n"
    )

    archivo.write(
        f"Total resultados: {len(resultados)}\n\n"
    )

    archivo.write(
        "=" * 80 + "\n"
    )


    for numero, item in enumerate(
        resultados,
        start=1
    ):

        archivo.write(
            f"\n\nRESULTADO #{numero}\n"
        )

        archivo.write(
            "-" * 80 + "\n"
        )

        archivo.write(
            f"TÍTULO:\n"
            f"{item['titulo']}\n\n"
        )

        archivo.write(
            f"URL:\n"
            f"{item['url']}\n\n"
        )

        archivo.write(
            "TEXTO:\n"
        )

        archivo.write(
            item["texto"]
        )

        archivo.write(
            "\n"
        )


print(
    f"\nReporte creado: {ARCHIVO_REPORTE}"
)


# ============================================================
# ENVIAR CORREO
# ============================================================

print("\nEnviando correo...")


mensaje = EmailMessage()

mensaje["Subject"] = (
    "Avisos Judiciales - Remates "
    f"{FECHA_INICIAL} al {FECHA_FINAL}"
)

mensaje["From"] = GMAIL_USER

mensaje["To"] = RECIPIENT_EMAIL


mensaje.set_content(
    f"""
Reporte de Avisos Judiciales de El Espectador.

Palabra clave:
{PALABRA_CLAVE}

Rango de fechas:
{FECHA_INICIAL} al {FECHA_FINAL}

Total de resultados:
{len(resultados)}

El reporte completo se encuentra
adjunto en este correo.
"""
)


# ============================================================
# ADJUNTAR REPORTE
# ============================================================

with open(
    ARCHIVO_REPORTE,
    "rb"
) as archivo:

    mensaje.add_attachment(
        archivo.read(),
        maintype="text",
        subtype="plain",
        filename=ARCHIVO_REPORTE
    )


# ============================================================
# GMAIL SMTP
# ============================================================

with smtplib.SMTP(
    "smtp.gmail.com",
    587,
    timeout=30
) as servidor:

    servidor.ehlo()

    servidor.starttls()

    servidor.ehlo()

    servidor.login(
        GMAIL_USER,
        GMAIL_APP_PASSWORD
    )

    servidor.send_message(
        mensaje
    )


print(
    "\nCorreo enviado correctamente."
)


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 80)
print("PROCESO TERMINADO CORRECTAMENTE")
print("=" * 80)
