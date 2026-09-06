"""
Bot de oportunidades de remates judiciales en Colombia (versión SIN IA, 100% gratis)
--------------------------------------------------------------------------------------
A diferencia de las otras versiones, este script NO usa ninguna API de IA
(ni Anthropic ni Gemini). En su lugar, descarga directamente el portal
público de remates judiciales del Banco Agrario de Colombia y extrae los
datos con expresiones regulares. Esto significa:

  - Cero costo, cero cuotas, cero riesgo de "429 quota exceeded".
  - No necesitas ninguna API key de IA ni tarjeta de crédito.
  - Solo necesitas los datos de Gmail para el envío del correo.

Fuente: https://www.bancoagrario.gov.co/remates-judiciales

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER          -> correo de Gmail que envía el mensaje
  GMAIL_APP_PASSWORD  -> "contraseña de aplicación" de Gmail (16 caracteres)
  RECIPIENT_EMAIL     -> correo que RECIBE el resumen

Opcional:
  MAX_PAGES           -> cuántas páginas del portal revisar (default: 5)
"""

import os
import re
import sys
import smtplib
import datetime
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
MAX_PAGES = int(os.environ.get("MAX_PAGES", "5"))

BASE_URL = "https://www.bancoagrario.gov.co/remates-judiciales"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

LISTING_SPLIT = re.compile(r"PERMITE INFORMAR A QUIEN INTERESE", re.I)


def descargar_pagina(page_num: int) -> str:
    url = f"{BASE_URL}?page={page_num}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (remates-bot; +para uso personal)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def html_a_texto(html: str) -> str:
    texto = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    texto = re.sub(r"<style.*?</style>", " ", texto, flags=re.S | re.I)
    texto = re.sub(r"<(br|p|div|li|tr|h[1-6])[^>]*>", "\n", texto, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = texto.replace("&nbsp;", " ").replace("&amp;", "&")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{2,}", "\n\n", texto)
    return texto


def parse_fecha(s):
    if not s:
        return None
    s = s.strip().lower()
    m = re.search(r"(\d{1,2})\s*(?:de)?\s*([a-záéíóú]+)\s*(?:de)?\s*(\d{4})", s)
    if m:
        dia, mes_txt, anio = m.groups()
        mes = MESES.get(mes_txt.strip())
        if mes:
            try:
                return datetime.date(int(anio), mes, int(dia))
            except ValueError:
                return None
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        dia, mes, anio = m.groups()
        try:
            return datetime.date(int(anio), int(mes), int(dia))
        except ValueError:
            return None
    return None


def campo(label: str, texto: str):
    m = re.search(rf"{label}\**[ \t]*:[ \t\*]*([^\n]+)", texto, re.I)
    return m.group(1).strip() if m else None


def campo_multilinea(label: str, texto: str, maxlen=350):
    m = re.search(rf"{label}\**[ \t]*:?[ \t\*]*\n*(.+)", texto, re.I | re.S)
    if not m:
        return None
    resto = m.group(1)
    parrafo = re.split(r"\n\s*\n", resto.strip())[0]
    parrafo = re.sub(r"\s+", " ", parrafo).strip(" *")
    return parrafo[:maxlen]


def extraer_listados(texto: str, page_num: int):
    bloques = LISTING_SPLIT.split(texto)[1:]
    listados = []
    for bloque in bloques:
        avaluo_m = re.search(r"avalúo[:\s]*\$?\s*([\d\.,]+)", bloque, re.I)
        postura_m = re.search(r"postura[:\s]*\$?\s*([\d\.,]+)", bloque, re.I)

        fecha_txt = campo(r"FECHA\s*(?:DE)?\s*REMATE", bloque)
        juzgado = campo("JUZGADO", bloque)
        radicacion = campo(r"RADICACI[OÓ]N", bloque)
        bien = campo_multilinea(r"BIEN A REMATAR", bloque)

        listados.append({
            "avaluo": avaluo_m.group(1).strip() if avaluo_m else None,
            "postura": postura_m.group(1).strip() if postura_m else None,
            "fecha_remate_texto": fecha_txt or "No especificada",
            "fecha_remate": parse_fecha(fecha_txt),
            "juzgado": juzgado or "No especificado",
            "radicacion": radicacion or "No especificada",
            "bien": bien or "Descripción no disponible",
            "link": f"{BASE_URL}?page={page_num}",
        })
    return listados


def calcular_descuento(avaluo_str, postura_str):
    """Devuelve el % que representa la postura mínima frente al avalúo, si se puede calcular."""
    def a_numero(s):
        if not s:
            return None
        try:
            return float(s.replace(".", "").replace(",", "."))
        except ValueError:
            return None
    a = a_numero(avaluo_str)
    p = a_numero(postura_str)
    if a and p and a > 0:
        return round((p / a) * 100, 1)
    return None


def recolectar_remates():
    todos = []
    for page_num in range(MAX_PAGES):
        try:
            html = descargar_pagina(page_num)
        except urllib.error.HTTPError as e:
            print(f"No se pudo descargar la página {page_num}: {e}")
            break
        except Exception as e:
            print(f"Error inesperado en la página {page_num}: {e}")
            break
        texto = html_a_texto(html)
        listados = extraer_listados(texto, page_num)
        if not listados:
            break
        todos.extend(listados)

    hoy = datetime.date.today()
    vigentes = [r for r in todos if r["fecha_remate"] is None or r["fecha_remate"] >= hoy]

    vistos = set()
    unicos = []
    for r in vigentes:
        clave = r["radicacion"]
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(r)

    unicos.sort(key=lambda r: (r["fecha_remate"] is None, r["fecha_remate"] or hoy))
    return unicos


def construir_html(remates):
    hoy = datetime.date.today().isoformat()

    if not remates:
        cuerpo = "<p>No se encontraron remates vigentes en esta revisión del portal del Banco Agrario.</p>"
    else:
        filas = ""
        for r in remates:
            descuento = calcular_descuento(r.get("avaluo"), r.get("postura"))
            descuento_txt = f"{descuento}% del avalúo" if descuento else "No calculable"
            filas += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Bien:</b> {r.get('bien')}</p>
              <p style="margin:2px 0;"><b>Avalúo:</b> ${r.get('avaluo') or '-'} &nbsp; | &nbsp; <b>Postura mínima:</b> ${r.get('postura') or '-'} &nbsp; | &nbsp; <b>Postura frente al avalúo:</b> {descuento_txt}</p>
              <p style="margin:2px 0;"><b>Fecha del remate:</b> {r.get('fecha_remate_texto')} &nbsp; | &nbsp; <b>Juzgado:</b> {r.get('juzgado')}</p>
              <p style="margin:2px 0;"><b>Radicación:</b> {r.get('radicacion')}</p>
              <p style="margin:6px 0;"><a href="{r.get('link')}">Ver en el portal del Banco Agrario</a></p>
            </div>
            """
        cuerpo = f"<p>Se encontraron {len(remates)} remate(s) vigente(s) (fecha igual o posterior a hoy, o sin fecha clara para verificar manualmente).</p>{filas}"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Remates judiciales — Banco Agrario Colombia — {hoy}</h2>
        {cuerpo}
        <hr>
        <p style="font-size:12px;color:#888;">
          Fuente: {BASE_URL}. La "postura frente al avalúo" es simplemente el
          cálculo matemático postura/avalúo, no un juicio de qué tan buena es
          la oportunidad. Verifica siempre la información directamente en el
          portal y con el juzgado antes de tomar cualquier decisión de
          inversión. Este resumen no constituye asesoría legal ni financiera.
          También puedes revisar otras fuentes manualmente: CISA (cisa.gov.co),
          SAE (sae.gov.co), remates DIAN (rematesvirtuales.dian.gov.co) y
          rematandobienes.com.
        </p>
      </body>
    </html>
    """


def enviar_correo(html: str, num_remates: int):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return

    asunto = f"Remates judiciales Colombia — {num_remates} remate(s) vigente(s) — {datetime.date.today().isoformat()}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())

    print(f"Correo enviado a {RECIPIENT_EMAIL}")


def main():
    remates = recolectar_remates()
    print(f"Remates vigentes encontrados: {len(remates)}")
    html = construir_html(remates)
    enviar_correo(html, len(remates))


if __name__ == "__main__":
    main()
