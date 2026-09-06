"""
Bot de oportunidades de remates judiciales en Colombia (SIN IA, 100% gratis)
--------------------------------------------------------------------------------
Combina dos fuentes, ambas leídas directamente sin ninguna API de IA:

  1. Banco Agrario de Colombia (bancoagrario.gov.co/remates-judiciales)
     -> Datos estructurados: avalúo, postura, fecha, juzgado, bien.

  2. Rama Judicial (ramajudicial.gov.co) - juzgados civiles configurados
     abajo en JUZGADOS_A_REVISAR (por defecto: Medellín)
     -> Menos estructurado: cada juzgado publica el radicado, una
     descripción libre y un enlace al PDF/aviso oficial. Debes abrir el
     PDF para ver avalúo/postura/bien, ya que el sitio no los expone en
     texto plano. Esta parte es más experimental que la del Banco
     Agrario porque depende de la estructura HTML de cada micrositio.

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

Opcional:
  MAX_PAGES_BANCO_AGRARIO -> páginas del Banco Agrario a revisar (default 5)
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
MAX_PAGES_BANCO_AGRARIO = int(os.environ.get("MAX_PAGES_BANCO_AGRARIO", "5"))

HEADERS = {"User-Agent": "Mozilla/5.0 (remates-bot; uso personal)"}


def descargar(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
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


# =========================================================================
# FUENTE 1: BANCO AGRARIO
# =========================================================================

BASE_URL_BANAGRARIO = "https://www.bancoagrario.gov.co/remates-judiciales"

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

LISTING_SPLIT = re.compile(r"PERMITE INFORMAR A QUIEN INTERESE", re.I)


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


def extraer_listados_banagrario(texto: str, page_num: int):
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
            "link": f"{BASE_URL_BANAGRARIO}?page={page_num}",
        })
    return listados


def calcular_descuento(avaluo_str, postura_str):
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


def recolectar_banagrario():
    todos = []
    for page_num in range(MAX_PAGES_BANCO_AGRARIO):
        try:
            html = descargar(f"{BASE_URL_BANAGRARIO}?page={page_num}")
        except Exception as e:
            print(f"[Banco Agrario] Error en página {page_num}: {e}")
            break
        texto = html_a_texto(html)
        listados = extraer_listados_banagrario(texto, page_num)
        if not listados:
            break
        todos.extend(listados)

    hoy = datetime.date.today()
    vigentes = [r for r in todos if r["fecha_remate"] is None or r["fecha_remate"] >= hoy]
    vistos, unicos = set(), []
    for r in vigentes:
        if r["radicacion"] not in vistos:
            vistos.add(r["radicacion"])
            unicos.append(r)
    unicos.sort(key=lambda r: (r["fecha_remate"] is None, r["fecha_remate"] or hoy))
    return unicos


# =========================================================================
# FUENTE 2: RAMA JUDICIAL (juzgados configurados)
# =========================================================================

RAMA_JUDICIAL_BASE = "https://www.ramajudicial.gov.co"

# Agrega aquí más juzgados si quieres cubrir otras ciudades.
# El "slug" es la parte de la URL después de /web/ en el micrositio del juzgado.
JUZGADOS_A_REVISAR = [
    ("Juzgado 001 Civil del Circuito de Medellín", "juzgado-001-civil-del-circuito-de-medellin"),
    ("Juzgado 02 de Ejecución Civil del Circuito de Medellín", "juzgado-02-de-ejecucion-civil-del-circuito-de-medellin"),
    ("Juzgado 03 de Ejecución Civil del Circuito de Medellín", "juzgado-03-de-ejecucion-civil-del-circuito-de-medellin"),
]


def encontrar_url_remates_reciente(html: str):
    m = re.search(r'>Remates<.*?(?=>Sentencias<|>Traslados)', html, re.S | re.I)
    if not m:
        return None, None
    bloque = m.group(0)
    pares = re.findall(r'href="([^"]+)"[^>]*>\s*(\d{4})\s*<', bloque)
    if not pares:
        return None, None
    pares_ordenados = sorted(pares, key=lambda p: int(p[1]), reverse=True)
    url_relativa, anio = pares_ordenados[0]
    url_final = url_relativa if url_relativa.startswith("http") else RAMA_JUDICIAL_BASE + url_relativa
    return url_final, anio


def extraer_avisos_remate(html: str, url_pagina: str):
    enlaces = re.findall(r'href="([^"]+)">\s*(\d{15,25})\s*<', html)
    texto = html_a_texto(html)
    avisos = []
    for enlace, radicado in enlaces:
        idx = texto.find(radicado)
        contexto = texto[idx:idx + 400] if idx != -1 else ""
        contexto = re.sub(r"\s+", " ", contexto).strip()
        avisos.append({
            "radicado": radicado,
            "detalle": contexto[:300] or "Sin descripción disponible, revisa el documento.",
            "documento": enlace,
            "fuente": url_pagina,
        })
    return avisos


def recolectar_rama_judicial():
    resultados = []
    for nombre, slug in JUZGADOS_A_REVISAR:
        base_url = f"{RAMA_JUDICIAL_BASE}/web/{slug}"
        try:
            html_base = descargar(base_url)
        except Exception as e:
            print(f"[Rama Judicial] No se pudo abrir {nombre}: {e}")
            continue

        url_remates, anio = encontrar_url_remates_reciente(html_base)
        if not url_remates:
            print(f"[Rama Judicial] No se encontró sección de Remates para {nombre}")
            continue

        try:
            html_remates = descargar(url_remates)
        except Exception as e:
            print(f"[Rama Judicial] Error descargando remates de {nombre}: {e}")
            continue

        avisos = extraer_avisos_remate(html_remates, url_remates)
        for a in avisos:
            a["juzgado"] = nombre
            a["anio"] = anio
        resultados.extend(avisos)

    # deduplicar por radicado
    vistos, unicos = set(), []
    for a in resultados:
        if a["radicado"] not in vistos:
            vistos.add(a["radicado"])
            unicos.append(a)
    return unicos


# =========================================================================
# CORREO
# =========================================================================

def construir_html(remates_banagrario, avisos_rama):
    hoy = datetime.date.today().isoformat()

    if remates_banagrario:
        filas_ba = ""
        for r in remates_banagrario:
            descuento = calcular_descuento(r.get("avaluo"), r.get("postura"))
            descuento_txt = f"{descuento}% del avalúo" if descuento else "No calculable"
            filas_ba += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Bien:</b> {r.get('bien')}</p>
              <p style="margin:2px 0;"><b>Avalúo:</b> ${r.get('avaluo') or '-'} &nbsp; | &nbsp; <b>Postura mínima:</b> ${r.get('postura') or '-'} &nbsp; | &nbsp; <b>Postura frente al avalúo:</b> {descuento_txt}</p>
              <p style="margin:2px 0;"><b>Fecha del remate:</b> {r.get('fecha_remate_texto')} &nbsp; | &nbsp; <b>Juzgado:</b> {r.get('juzgado')}</p>
              <p style="margin:2px 0;"><b>Radicación:</b> {r.get('radicacion')}</p>
              <p style="margin:6px 0;"><a href="{r.get('link')}">Ver en el portal del Banco Agrario</a></p>
            </div>
            """
        seccion_ba = f"<h3>Banco Agrario ({len(remates_banagrario)} remate(s) vigente(s))</h3>{filas_ba}"
    else:
        seccion_ba = "<h3>Banco Agrario</h3><p>No se encontraron remates vigentes en esta revisión.</p>"

    if avisos_rama:
        filas_rj = ""
        for a in avisos_rama:
            filas_rj += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Juzgado:</b> {a.get('juzgado')} ({a.get('anio')})</p>
              <p style="margin:2px 0;"><b>Radicado:</b> {a.get('radicado')}</p>
              <p style="margin:2px 0;"><b>Detalle:</b> {a.get('detalle')}</p>
              <p style="margin:6px 0;"><a href="{a.get('documento')}">Ver documento/aviso oficial (PDF)</a> &nbsp;|&nbsp; <a href="{a.get('fuente')}">Ver página del juzgado</a></p>
            </div>
            """
        seccion_rj = f"<h3>Rama Judicial — juzgados de Medellín ({len(avisos_rama)} aviso(s))</h3><p style='font-size:12px;color:#888;'>Esta fuente no expone avalúo ni postura en texto plano: ábrelo el PDF del aviso para ver los detalles completos del remate.</p>{filas_rj}"
    else:
        seccion_rj = "<h3>Rama Judicial — juzgados de Medellín</h3><p>No se encontraron avisos de remate en esta revisión.</p>"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Remates judiciales en Colombia — {hoy}</h2>
        {seccion_ba}
        <hr>
        {seccion_rj}
        <hr>
        <p style="font-size:12px;color:#888;">
          Verifica siempre la información directamente en el portal/juzgado
          correspondiente antes de tomar cualquier decisión de inversión.
          Este resumen no constituye asesoría legal ni financiera.
        </p>
      </body>
    </html>
    """


def enviar_correo(html: str, total: int):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return

    asunto = f"Remates judiciales Colombia — {total} resultado(s) — {datetime.date.today().isoformat()}"
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
    remates_banagrario = recolectar_banagrario()
    print(f"Banco Agrario: {len(remates_banagrario)} remate(s) vigente(s)")

    avisos_rama = recolectar_rama_judicial()
    print(f"Rama Judicial: {len(avisos_rama)} aviso(s) encontrado(s)")

    html = construir_html(remates_banagrario, avisos_rama)
    enviar_correo(html, len(remates_banagrario) + len(avisos_rama))


if __name__ == "__main__":
    main()
