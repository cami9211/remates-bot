#!/usr/bin/env python3
"""
find_remates_colombia.py
--------------------------
Fuente: Avisos Judiciales de El Espectador (judiciales.elespectador.com),
un sitio PHP clásico (no requiere JavaScript para mostrar resultados,
a diferencia del portal de la Rama Judicial).

LÉEME - MUY IMPORTANTE:
Este sitio bloquea el acceso automatizado en su robots.txt, así que no
se pudo inspeccionar su formulario de búsqueda desde el entorno donde
se generó este script (sin acceso a internet y respetando ese bloqueo).
Los nombres de parámetros de abajo (SEARCH_PARAMS_TEMPLATE) son
PLACEHOLDERS - tienes que confirmarlos tú mismo:

  1. Ve a https://judiciales.elespectador.com/ en tu navegador.
  2. Configura el rango de fechas y escribe "remate", dale a "Buscar".
  3. Mira la URL resultante en la barra de direcciones. Si cambió a algo
     como ".../resultados.php?buscar=remate&fecha_ini=2026-08-10&fecha_fin=2026-09-08",
     esos son los nombres reales de los parámetros - reemplázalos abajo.
  4. Si la URL no cambia (el formulario usa POST), abre F12 -> Network,
     repite la búsqueda, clic derecho sobre la petición que trae los
     resultados -> "Copy" -> "Copy as cURL", y pégamela para que te
     ajuste el script con los valores exactos.

IMPORTANTE - USO RESPONSABLE: este sitio pide explícitamente en su
robots.txt que no se acceda de forma automatizada. Este script consulta
contenido público (avisos judiciales, de interés general y sin
restricción de acceso para lectura humana normal), pero de todas formas
conviene: (a) NO aumentar la frecuencia más allá de 1 vez al día, (b)
revisar los Términos de Uso del sitio antes de dejarlo corriendo de
forma permanente, y (c) estar dispuesto a detenerlo si el sitio empieza
a bloquear la IP del runner de GitHub Actions.
"""

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIGURACIÓN - AJUSTA ESTOS VALORES DESPUÉS DE INSPECCIONAR LA BÚSQUEDA REAL
# ---------------------------------------------------------------------------

BASE_URL = "https://judiciales.elespectador.com"
SEARCH_PAGE_URL = f"{BASE_URL}/"

# PLACEHOLDER: reemplaza por la URL real a la que apunta el formulario de
# búsqueda cuando das clic en "Buscar" (revisa la barra de direcciones o
# la pestaña Network de DevTools). Puede ser distinta a la página inicial,
# p. ej. algo como f"{BASE_URL}/resultados.php".
SEARCH_URL = f"{BASE_URL}/resultados.php"

# Rango de días hacia atrás que se consulta cada vez que corre el script
# (equivalente al selector de fechas de la captura: "Aug 10,26 - Sep 8,26").
# Ajusta este número según qué tan seguido quieras revisar hacia atrás.
DIAS_HACIA_ATRAS = 30

# PLACEHOLDER: reemplaza las CLAVES por los nombres reales de parámetro
# que veas en la URL o en el payload del formulario. Los nombres de abajo
# (buscar, fecha_ini, fecha_fin) son una suposición razonable, no confirmada.
SEARCH_PARAMS_TEMPLATE = {
    "buscar": "remate",
    "fecha_ini": None,  # se rellena en tiempo de ejecución
    "fecha_fin": None,  # se rellena en tiempo de ejecución
}
FORMATO_FECHA = "%Y-%m-%d"  # ajusta si el sitio espera otro formato (ej. %d/%m/%Y)

# Dirección del inmueble/proceso que te interesa resaltar dentro del
# listado general de remates (no filtra la búsqueda, solo resalta el
# resultado en el correo si aparece)
PALABRAS_CLAVE = ["850221", "CALLE 5 SUR", "22-290"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE CORREO (viene de GitHub Secrets, ver workflow .yml)
# ---------------------------------------------------------------------------

EMAIL_REMITENTE = os.environ.get("GMAIL_USER", "")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_DESTINATARIO = os.environ.get("RECIPIENT_EMAIL", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


# ---------------------------------------------------------------------------
# LÓGICA DE CONSULTA
# ---------------------------------------------------------------------------

def construir_form_data():
    ahora = datetime.now()
    data = dict(FORM_DATA_TEMPLATE)
    data["mes"] = MESES_NUM_A_TEXTO[ahora.month]
    data["anio"] = str(ahora.year)
    return data


def consultar_portal():
    """
    Intenta reproducir la consulta del portal como una petición HTTP.
    Devuelve el texto plano de la respuesta para poder buscar palabras
    clave en él.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    # Paso 1: cargar la página para obtener cookies de sesión / tokens
    resp_inicial = session.get(SEARCH_PAGE_URL, timeout=30)
    resp_inicial.raise_for_status()

    # Si el portal requiere un token oculto (CSRF), descomenta y ajusta:
    # sopa_inicial = BeautifulSoup(resp_inicial.text, "html.parser")
    # token = sopa_inicial.find("input", {"name": "p_auth"})
    # if token:
    #     FORM_DATA_TEMPLATE["p_auth"] = token["value"]

    form_data = construir_form_data()

    # Paso 2: enviar la consulta. Si POST no funciona, prueba GET:
    # resp = session.get(SEARCH_URL, params=form_data, timeout=30)
    resp = session.post(SEARCH_URL, data=form_data, timeout=30)
    resp.raise_for_status()

    sopa = BeautifulSoup(resp.text, "html.parser")
    return sopa.get_text(separator="\n")


def buscar_coincidencias(texto_pagina):
    encontrados = []
    texto_lower = texto_pagina.lower()
    for palabra in PALABRAS_CLAVE:
        idx = texto_lower.find(palabra.lower())
        if idx != -1:
            inicio = max(0, idx - 200)
            fin = min(len(texto_pagina), idx + 200)
            fragmento = texto_pagina[inicio:fin].strip()
            encontrados.append(f"Coincidencia con '{palabra}':\n...{fragmento}...")
    return encontrados


# ---------------------------------------------------------------------------
# ENVÍO DE CORREO
# ---------------------------------------------------------------------------

def enviar_correo(asunto, cuerpo):
    if not (EMAIL_REMITENTE and EMAIL_PASSWORD and EMAIL_DESTINATARIO):
        print("[AVISO] Faltan variables de entorno de correo "
              "(GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). "
              "Se imprime el resultado en consola en su lugar.\n")
        print(asunto)
        print(cuerpo)
        return

    mensaje = MIMEText(cuerpo, "plain", "utf-8")
    mensaje["Subject"] = asunto
    mensaje["From"] = EMAIL_REMITENTE
    mensaje["To"] = EMAIL_DESTINATARIO

    contexto = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as servidor:
        servidor.starttls(context=contexto)
        servidor.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
        servidor.sendmail(EMAIL_REMITENTE, EMAIL_DESTINATARIO, mensaje.as_string())

    print(f"Correo enviado a {EMAIL_DESTINATARIO}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{fecha}] Consultando publicaciones procesales (modo sin navegador)...")

    try:
        texto_pagina = consultar_portal()
        coincidencias = buscar_coincidencias(texto_pagina)
    except Exception as exc:  # noqa: BLE001
        asunto = "⚠️ Error en el monitor de remates - Rama Judicial"
        cuerpo = (
            f"La consulta automática falló el {fecha}.\n\n"
            f"Detalle del error:\n{exc}\n\n"
            "Causa más probable: el formulario del portal necesita "
            "JavaScript para mostrar resultados, o cambiaron los nombres "
            "de los campos del formulario. Revisa las instrucciones del "
            "encabezado del script (inspección con DevTools) para ajustar "
            "SEARCH_URL y FORM_DATA_TEMPLATE."
        )
        print(cuerpo)
        enviar_correo(asunto, cuerpo)
        sys.exit(1)

    if coincidencias:
        asunto = "🔔 Novedad encontrada - Remate F.M.I. 001-850221"
        cuerpo = (
            f"Consulta del {fecha}\n\n"
            "Se encontraron coincidencias en el portal de Publicaciones "
            "Procesales de la Rama Judicial:\n\n"
            + "\n\n---\n\n".join(coincidencias)
            + f"\n\nRevisa directamente en:\n{SEARCH_PAGE_URL}"
        )
    else:
        asunto = "Sin novedades - Remate F.M.I. 001-850221"
        cuerpo = (
            f"Consulta del {fecha}\n\n"
            f"No se encontraron coincidencias con {PALABRAS_CLAVE} en la "
            "respuesta del portal para el mes y año actuales."
        )

    print(cuerpo)
    enviar_correo(asunto, cuerpo)


if __name__ == "__main__":
    main()
