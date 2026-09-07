"""
Bot de avisos de Asuntos Legales (SIN IA, SIN filtros)
--------------------------------------------------------------------------------
Sigue los enlaces "Continuar leyendo" desde unas semillas en
https://www.asuntoslegales.com.co/edictos, toma los primeros
MAX_RESULTADOS avisos que logra leer (sin filtrar por categoría, por
palabra clave ni por fecha), los imprime en consola y los envía por
correo tal cual.

Variables de entorno requeridas: GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL
Opcionales: MAX_RESULTADOS (default 6), MAX_AVISOS_REVISADOS_AL (default 30)
"""

import os
import re
import smtplib
import datetime
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
MAX_RESULTADOS = int(os.environ.get("MAX_RESULTADOS", "6"))
MAX_AVISOS_REVISADOS_AL = int(os.environ.get("MAX_AVISOS_REVISADOS_AL", "30"))

HEADERS = {"User-Agent": "Mozilla/5.0 (edictos-bot; uso personal)"}
AL_BASE_URL = "https://www.asuntoslegales.com.co"
AL_DETALLE_ID_RE = re.compile(r"/edictos/detalle/([A-Za-z0-9_\-]+)")
AL_BLOQUE_RE = re.compile(
    r"Edictos y Avisos Legales\s*\n(?:[\s\-]*\n)*([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ]{2,25})\s*\n+"
    r"(\d{1,2} de [a-záéíóúñ]+ de \d{4})\s*\n+(.*?)"
    r"\n+\s*(?:¿Quiere publicar su edicto en línea\?|MÁS EDICTOS Y AVISOS LEGALES)",
    re.S,
)
AL_SEMILLAS = [
    "003_VEF_17306-1-1", "002_VEF_27226-1-1", "009_VEF_4557-6-1",
    "008_VEF_4071-2-1", "003_VEF_16383-11-1",
]


def descargar(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def html_a_texto(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<(br|p|div|li|tr|h[1-6])[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{2,}", "\n\n", re.sub(r"[ \t]+", " ", t)).strip()


def recolectar():
    resultados, visitados, cola, revisados = [], set(), list(AL_SEMILLAS), 0
    while cola and len(resultados) < MAX_RESULTADOS and revisados < MAX_AVISOS_REVISADOS_AL:
        id_aviso = cola.pop(0)
        if id_aviso in visitados:
            continue
        visitados.add(id_aviso)
        revisados += 1
        url = f"{AL_BASE_URL}/edictos/detalle/{id_aviso}"
        try:
            html = descargar(url)
        except Exception as e:
            print(f"Error abriendo {id_aviso}: {e}")
            continue
        for nuevo_id in AL_DETALLE_ID_RE.findall(html):
            if nuevo_id not in visitados and nuevo_id not in cola:
                cola.append(nuevo_id)
        m = AL_BLOQUE_RE.search(html_a_texto(html))
        if not m:
            continue
        resultados.append({
            "id": id_aviso,
            "categoria": m.group(1).strip(),
            "fecha": m.group(2).strip(),
            "texto": re.sub(r"\s+", " ", m.group(3)).strip(),
            "link": url,
        })
    return resultados


def construir_html(avisos):
    tarjetas = "".join(f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;margin-bottom:16px;">
      <tr><td style="padding:16px 20px;">
        <div style="font-size:12px;color:#fff;background:#1e3a5f;display:inline-block;
                    padding:4px 10px;border-radius:999px;font-weight:700;">{a['categoria']}</div>
        <div style="font-size:12px;color:#6b7280;margin-top:6px;">Fecha: {a['fecha']}</div>
        <div style="margin-top:10px;font-size:13px;color:#374151;background:#f9fafb;
                    padding:10px;border-radius:8px;">{a['texto']}</div>
        <div style="margin-top:10px;"><a href="{a['link']}" style="font-size:13px;color:#1e3a5f;">Ver aviso original →</a></div>
      </td></tr>
    </table>""" for a in avisos) or "<p>No se encontraron avisos.</p>"

    return f"""<html><body style="font-family:Arial;background:#f3f4f6;padding:20px;">
    <h2>Avisos de Asuntos Legales — {datetime.date.today().strftime('%d/%m/%Y')}</h2>
    {tarjetas}
    </body></html>"""


def enviar_correo(html, total):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Avisos Asuntos Legales — {total} resultado(s) — {datetime.date.today().isoformat()}"
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"Correo enviado a {RECIPIENT_EMAIL}")


def main():
    avisos = recolectar()
    for a in avisos:
        print(f"[{a['categoria']}] {a['fecha']} — {a['texto'][:150]}")
    enviar_correo(construir_html(avisos), len(avisos))


if __name__ == "__main__":
    main()
