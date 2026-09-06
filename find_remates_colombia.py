"""
Bot de oportunidades de remates judiciales en Colombia (SIN IA, 100% gratis)
--------------------------------------------------------------------------------
Combina dos fuentes, ambas leídas directamente sin ninguna API de IA:

  1. Banco Agrario de Colombia (bancoagrario.gov.co/remates-judiciales)
     -> Datos estructurados: avalúo, postura, fecha, juzgado, bien.

  2. Avisos Masificados de El Colombiano - Judiciales / Edictos
     (masificados.com/otros/avisos/judiciales/edictos)
     -> Listado de edictos, emplazamientos, avisos de remate, avisos de
     liquidación patrimonial, etc. publicados por juzgados y notarías,
     mayoritariamente de Antioquia. Solo se conservan los avisos
     recientes (por defecto, publicados desde el día anterior).

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

Opcional:
  MAX_PAGES_BANCO_AGRARIO   -> páginas del Banco Agrario a revisar (default 5)
  MAX_PAGES_MASIFICADOS     -> páginas de Masificados a revisar (default 5)
  MASIFICADOS_DIAS_ATRAS    -> qué tan "reciente" es reciente, en días (default 1)
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
MAX_PAGES_MASIFICADOS = int(os.environ.get("MAX_PAGES_MASIFICADOS", "5"))
MASIFICADOS_DIAS_ATRAS = int(os.environ.get("MASIFICADOS_DIAS_ATRAS", "1"))

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


def parse_fecha(s):
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        dia, mes, anio = m.groups()
        try:
            return datetime.date(int(anio), int(mes), int(dia))
        except ValueError:
            return None
    return None


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


def parse_fecha_larga(s):
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
    return parse_fecha(s)


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
            "fecha_remate": parse_fecha_larga(fecha_txt),
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
# FUENTE 2: AVISOS MASIFICADOS (El Colombiano) - Judiciales / Edictos
# =========================================================================

BASE_URL_MASIFICADOS = "https://www.masificados.com/otros/avisos/judiciales/edictos"


def construir_url_masificados(pagina: int) -> str:
    return f"{BASE_URL_MASIFICADOS}?max_per_page=50&search_results_view=lineal&page={pagina}"


def extraer_avisos_masificados(html: str, texto: str, url_pagina: str):
    """
    Cada aviso enlaza a una URL del tipo:
      https://www.masificados.com/otros/ocasional/<id_anunciante>/aviso/<id_aviso>/
    Esa misma URL aparece repetida más de una vez en la página (una vez
    envolviendo la miniatura, otra con el texto del edicto), así que
    deduplicamos por <id_aviso> y nos quedamos con el texto de ancla más
    largo como título/resumen.
    """
    detalle_pattern = re.compile(
        r'href="(https://www\.masificados\.com/otros/ocasional/\d+/aviso/(\d+)/)"', re.I
    )
    enlaces = {}
    for m in detalle_pattern.finditer(html):
        href, aviso_id = m.group(1), m.group(2)
        enlaces.setdefault(aviso_id, href)

    resultados = []
    for aviso_id, href in enlaces.items():
        textos_ancla = re.findall(rf'href="{re.escape(href)}"[^>]*>([^<]{{10,400}})</a>', html, re.I)
        candidatos = [t.strip() for t in textos_ancla if t.strip() and href not in t]
        titulo = max(candidatos, key=len) if candidatos else "Ver aviso completo en el enlace"
        titulo = re.sub(r"\s+", " ", titulo)

        idx = texto.find(aviso_id)
        ventana = texto[max(0, idx - 50): idx + 400] if idx != -1 else ""
        fecha_m = re.search(r"Publicado:\s*(\d{1,2}/\d{1,2}/\d{4})", ventana, re.I)
        fecha_texto = fecha_m.group(1) if fecha_m else None

        resultados.append({
            "id": aviso_id,
            "titulo": titulo,
            "fecha_texto": fecha_texto or "No especificada",
            "fecha": parse_fecha(fecha_texto),
            "enlace": href,
            "fuente": url_pagina,
        })
    return resultados


def recolectar_masificados():
    hoy = datetime.date.today()
    fecha_limite = hoy - datetime.timedelta(days=MASIFICADOS_DIAS_ATRAS)

    resultados = []
    for pagina in range(1, MAX_PAGES_MASIFICADOS + 1):
        url = construir_url_masificados(pagina)
        try:
            html = descargar(url)
        except Exception as e:
            print(f"[Masificados] Error en página {pagina}: {e}")
            break

        texto = html_a_texto(html)
        avisos_pagina = extraer_avisos_masificados(html, texto, url)
        if not avisos_pagina:
            break

        # El listado viene ordenado del más nuevo al más antiguo, así que
        # en cuanto una página ya no trae nada dentro de la ventana de
        # "reciente", dejamos de paginar.
        recientes_pagina = [a for a in avisos_pagina if a["fecha"] and a["fecha"] >= fecha_limite]
        resultados.extend(recientes_pagina)

        if not recientes_pagina:
            break

    vistos, unicos = set(), []
    for a in resultados:
        if a["id"] not in vistos:
            vistos.add(a["id"])
            unicos.append(a)
    unicos.sort(key=lambda a: a["fecha"] or hoy, reverse=True)
    return unicos


# =========================================================================
# CORREO
# =========================================================================

def construir_html(remates_banagrario, avisos_masificados):
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

    if avisos_masificados:
        filas_ma = ""
        for a in avisos_masificados:
            filas_ma += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Aviso:</b> {a.get('titulo')}</p>
              <p style="margin:2px 0;"><b>Publicado:</b> {a.get('fecha_texto')}</p>
              <p style="margin:6px 0;"><a href="{a.get('enlace')}">Ver aviso completo</a></p>
            </div>
            """
        seccion_ma = (
            f"<h3>Avisos Masificados (El Colombiano) — Judiciales/Edictos recientes ({len(avisos_masificados)} aviso(s))</h3>"
            f"{filas_ma}"
        )
    else:
        seccion_ma = "<h3>Avisos Masificados (El Colombiano) — Judiciales/Edictos</h3><p>No se encontraron avisos recientes en esta revisión.</p>"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Remates judiciales en Colombia — {hoy}</h2>
        {seccion_ba}
        <hr>
        {seccion_ma}
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

    avisos_masificados = recolectar_masificados()
    print(f"Masificados: {len(avisos_masificados)} aviso(s) reciente(s) encontrado(s)")

    html = construir_html(remates_banagrario, avisos_masificados)
    enviar_correo(html, len(remates_banagrario) + len(avisos_masificados))


if __name__ == "__main__":
    main()
