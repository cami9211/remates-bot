import time
import smtplib
from email.message import EmailMessage
from datetime import datetime

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL = "https://judiciales.elespectador.com/"

FECHA_INICIAL = "10/08/2026"
FECHA_FINAL = "08/09/2026"

PALABRA_CLAVE = "remate"

# Correo que recibirá el reporte
CORREO_DESTINO = "TU_CORREO@gmail.com"

# Correo desde el cual se enviará
CORREO_REMITENTE = "TU_CORREO@gmail.com"

# Para Gmail se recomienda utilizar una contraseña de aplicación
CONTRASENA = "TU_CONTRASENA_DE_APLICACION"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

ARCHIVO_REPORTE = "resultados_remates.txt"


# ============================================================
# CONFIGURAR CHROME
# ============================================================

options = webdriver.ChromeOptions()

# Si quieres ver el navegador, deja esto comentado.
# Si quieres que funcione en segundo plano, descoméntalo.
# options.add_argument("--headless=new")

options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

wait = WebDriverWait(driver, 20)


# ============================================================
# ABRIR PÁGINA
# ============================================================

print("Abriendo Avisos Judiciales...")

driver.get(URL)

time.sleep(3)


# ============================================================
# MOSTRAR ELEMENTOS PARA DEBUG
# ============================================================

print("Página cargada.")

print("Título:", driver.title)


# ============================================================
# BUSCAR INPUTS
# ============================================================

inputs = driver.find_elements(By.TAG_NAME, "input")

print("\nInputs encontrados:")

for i, elemento in enumerate(inputs):
    try:
        print(
            i,
            "type=", elemento.get_attribute("type"),
            "name=", elemento.get_attribute("name"),
            "id=", elemento.get_attribute("id"),
            "placeholder=", elemento.get_attribute("placeholder")
        )
    except:
        pass


# ============================================================
# IDENTIFICAR CAMPOS
# ============================================================

# Buscamos el campo de palabra clave.
# La página muestra un input para "Palabra clave".

campo_busqueda = None

for elemento in inputs:

    placeholder = (
        elemento.get_attribute("placeholder") or ""
    ).lower()

    name = (
        elemento.get_attribute("name") or ""
    ).lower()

    elemento_id = (
        elemento.get_attribute("id") or ""
    ).lower()

    if (
        "palabra" in placeholder
        or "keyword" in name
        or "buscar" in name
        or "search" in elemento_id
    ):
        campo_busqueda = elemento
        break


if campo_busqueda is None:

    # Intento alternativo:
    # buscar inputs de texto.

    for elemento in inputs:

        tipo = elemento.get_attribute("type")

        if tipo == "text":
            campo_busqueda = elemento
            break


if campo_busqueda is None:
    driver.quit()
    raise Exception(
        "No se encontró el campo de búsqueda."
    )


# ============================================================
# ESCRIBIR "REMATE"
# ============================================================

print("Escribiendo palabra clave:", PALABRA_CLAVE)

campo_busqueda.click()

campo_busqueda.clear()

campo_busqueda.send_keys(PALABRA_CLAVE)


# ============================================================
# PRESIONAR ENTER
# ============================================================

print("Presionando ENTER...")

campo_busqueda.send_keys(Keys.ENTER)

time.sleep(5)


# ============================================================
# OBTENER RESULTADOS
# ============================================================

print("\nResultados cargados.")

html = driver.page_source

soup = BeautifulSoup(html, "html.parser")


# ============================================================
# EXTRAER TEXTO DE RESULTADOS
# ============================================================

texto_pagina = soup.get_text(
    "\n",
    strip=True
)


# Guardamos todo el texto visible
with open(
    ARCHIVO_REPORTE,
    "w",
    encoding="utf-8"
) as archivo:

    archivo.write(
        "RESULTADOS AVISOS JUDICIALES\n"
    )

    archivo.write(
        "====================================\n\n"
    )

    archivo.write(
        f"Fecha inicial: {FECHA_INICIAL}\n"
    )

    archivo.write(
        f"Fecha final: {FECHA_FINAL}\n"
    )

    archivo.write(
        f"Palabra clave: {PALABRA_CLAVE}\n\n"
    )

    archivo.write(
        "====================================\n\n"
    )

    archivo.write(
        texto_pagina
    )


# ============================================================
# IMPRIMIR RESULTADOS
# ============================================================

print("\n")
print("=" * 70)
print("RESULTADOS")
print("=" * 70)

print(texto_pagina)

print("=" * 70)


# ============================================================
# ENVIAR CORREO
# ============================================================

print("\nEnviando reporte por correo...")


mensaje = EmailMessage()

mensaje["Subject"] = (
    f"Avisos judiciales - {PALABRA_CLAVE} "
    f"{FECHA_INICIAL} al {FECHA_FINAL}"
)

mensaje["From"] = CORREO_REMITENTE

mensaje["To"] = CORREO_DESTINO


mensaje.set_content(
    f"""
Resultado de búsqueda de Avisos Judiciales.

Palabra clave:
{PALABRA_CLAVE}

Rango:
{FECHA_INICIAL} - {FECHA_FINAL}

El reporte completo se encuentra
adjunto en este correo.
"""
)


# Adjuntar reporte

with open(
    ARCHIVO_REPORTE,
    "rb"
) as archivo:

    datos = archivo.read()

    mensaje.add_attachment(
        datos,
        maintype="text",
        subtype="plain",
        filename=ARCHIVO_REPORTE
    )


# ============================================================
# CONEXIÓN SMTP
# ============================================================

try:

    with smtplib.SMTP(
        SMTP_SERVER,
        SMTP_PORT
    ) as servidor:

        servidor.starttls()

        servidor.login(
            CORREO_REMITENTE,
            CONTRASENA
        )

        servidor.send_message(
            mensaje
        )

    print("Correo enviado correctamente.")

except Exception as error:

    print(
        "Error enviando correo:",
        error
    )


# ============================================================
# FINALIZAR
# ============================================================

print("\nProceso terminado.")

driver.quit()
