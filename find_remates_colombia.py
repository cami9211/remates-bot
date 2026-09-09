#!/usr/bin/env python3
"""
monitor_remate.py
------------------
Versión SIN Selenium (solo `requests` + `BeautifulSoup`) pensada para
correr en GitHub Actions como tarea diaria programada.

LÉEME - MUY IMPORTANTE:
Este script asume que el formulario de "Otras consultas" del portal
https://publicacionesprocesales.ramajudicial.gov.co puede enviarse como
una petición HTTP normal (GET o POST) sin necesitar que un navegador
ejecute JavaScript. Muchos portales Liferay funcionan así por debajo
(el JS solo mejora la experiencia visual), pero esto NO se pudo verificar
en el entorno donde se generó este script, porque no tiene acceso a
internet.

CÓMO CONFIRMARLO Y AJUSTAR ESTE SCRIPT (hazlo una sola vez, tú mismo):
  1. Abre el portal en Chrome: la URL de arriba.
  2. Pulsa F12 -> pestaña "Network" (Red) -> marca "Preserve log".
  3. Selecciona los filtros (Departamento, Despacho, Mes, Año) y haz clic
     en "Consultar".
  4. Busca en la lista de peticiones la que trae los resultados (normalmente
     un XHR/Fetch, o el propio documento HTML si recarga la página).
  5. Haz clic derecho sobre esa petición -> "Copy" -> "Copy as cURL".
  6. Pégame ese cURL (o el Request URL + Form Data / Payload que veas en
     la pestaña "Headers") y te ajusto los valores de FORM_DATA y
     SEARCH_URL de abajo para que coincidan exactamente.

Si la petición que trae los resultados es un XHR que devuelve JSON o HTML
parcial, este script funcionará prácticamente igual, solo cambiando la
URL y el payload. Si en cambio los resultados solo se generan corriendo
JavaScript en el navegador (SPA real), este enfoque sin Selenium
lamentablemente NO es viable y tocaría usar el otro script con Selenium
en un runner que sí soporte navegador (GitHub Actions también puede
correr Selenium con `browser-actions/setup-chrome`, si prefieres esa vía).

DEPENDENCIAS (ver requirements.txt):
    pip install requests beautifulsoup4
"""

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.text import MIMEText


from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIGURACIÓN - AJUSTA ESTOS VALORES DESPUÉS DE INSPECCIONAR LA PETICIÓN REAL
# ---------------------------------------------------------------------------

BASE_URL = "https://publicacionesprocesales.ramajudicial.gov.co"
SEARCH_PAGE_URL = f"{BASE_URL}/web/publicaciones-procesales/otras-consultas"

# PLACEHOLDER: reemplaza esta URL por la que veas en DevTools como
# destino real del formulario (puede ser la misma SEARCH_PAGE_URL con
# parámetros, o una URL de portlet tipo
# ".../otras-consultas?p_p_id=...&p_p_lifecycle=2&...")
SEARCH_URL = SEARCH_PAGE_URL

# PLACEHOLDER: estos son los nombres de campo típicos, pero Liferay suele
# usar nombres largos con namespace de portlet, algo como:
# "_com_liferay_..._departamento" en vez de simplemente "departamento".
# Reemplaza las CLAVES (a la izquierda de los ":") por los nombres reales
# que veas en la pestaña "Payload"/"Form Data" de DevTools.
FORM_DATA_TEMPLATE = {
    "departamento": "ANTIOQUIA",
    "despacho": "050013403000",   # Oficina de Apoyo Juzgados Civiles Circuito Ejecución Medellín
    "mes": None,   # se rellena en tiempo de ejecución con el mes actual
    "anio": None,  # se rellena en tiempo de ejecución con el año actual
}

MESES_NUM_A_TEXTO = {
    1: "01. Enero", 2: "02. Febrero", 3: "03. Marzo", 4: "04. Abril",
    5: "05. Mayo", 6: "06. Junio", 7: "07. Julio", 8: "08. Agosto",
    9: "09. Septiembre", 10: "10. Octubre", 11: "11. Noviembre", 12: "12. Diciembre",
}

# Palabras clave que buscamos en el HTML/JSON de resultados
PALABRAS_CLAVE = ["850221", "CALLE 5 SUR", "22-290"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE CORREO (usa GitHub Secrets, ver workflow .yml adjunto)
# ---------------------------------------------------------------------------

EMAIL_REMITENTE = os.environ.get("REMATE_BOT_EMAIL", "")
EMAIL_PASSWORD = os.environ.get("REMATE_BOT_EMAIL_PASSWORD", "")
EMAIL_DESTINATARIO = os.environ.get("REMATE_BOT_DESTINO", "")
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
    # (algunos portales Liferay requieren un token CSRF que viaja como
    # input oculto en el HTML; si es el caso, habrá que extraerlo aquí
    # con BeautifulSoup antes del POST).
    resp_inicial = session.get(SEARCH_PAGE_URL, timeout=30)
    resp_inicial.raise_for_status()

    # Si el portal requiere un token oculto, descomenta y ajusta esto:
    # sopa_inicial = BeautifulSoup(resp_inicial.text, "html.parser")
    # token = sopa_inicial.find("input", {"name": "p_auth"})
    # if token:
    #     FORM_DATA_TEMPLATE["p_auth"] = token["value"]

    form_data = construir_form_data()

    # Paso 2: enviar la consulta. Prueba primero con POST; si no funciona,
    # intenta cambiar a session.get(SEARCH_URL, params=form_data, ...)
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
              "(REMATE_BOT_EMAIL / REMATE_BOT_EMAIL_PASSWORD / REMATE_BOT_DESTINO). "
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
            "JavaScript para mostrar resultados y una petición HTTP simple "
            "no basta, o cambiaron los nombres de los campos del formulario. "
            "Revisa las instrucciones del encabezado del script (inspección "
            "con DevTools) para ajustar SEARCH_URL y FORM_DATA_TEMPLATE."
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
