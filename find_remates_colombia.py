"""
Bot de oportunidades de remates judiciales en Colombia (SIN IA, 100% gratis)
--------------------------------------------------------------------------------
Combina dos fuentes, ambas leídas directamente sin ninguna API de IA:

  1. Banco Agrario de Colombia (bancoagrario.gov.co/remates-judiciales)
     -> Datos estructurados: avalúo, postura, fecha, juzgado, bien.

  2. Publicaciones Procesales - Rama Judicial
     (publicacionesprocesales.ramajudicial.gov.co)
     -> Portal nuevo (reemplaza los micrositios individuales de cada
     juzgado) que permite filtrar por Departamento, Municipio, Entidad,
     Especialidad, Despacho y rango de fechas. Aquí se usa preconfigurado
     para traer publicaciones de tipo "Remates" (idStructure=6098997) en
     Antioquia / Medellín.

     ADVERTENCIA / LIMITACIÓN CONOCIDA: este portal es un portlet Liferay
     que carga resultados de forma dinámica y cuyo filtro de Municipio
     parece depender del estado de sesión (no viaja en la URL). Además,
     su robots.txt bloquea el acceso automatizado de algunas herramientas,
     así que antes de dejar esto corriendo de forma recurrente, confirma
     que el uso que le vas a dar respeta los términos de uso del portal.
     La extracción de campos (radicado, fecha, despacho, enlace) usa
     heurísticas genéricas porque no fue posible inspeccionar el HTML/JSON
     real que devuelve el portal al aplicar el filtro. Si al correr el
     script ves que no trae nada o trae basura, activa DEBUG_DUMP_PP=1,
     revisa los archivos HTML que se guardan y ajusta la función
     `extraer_publicaciones()` (o compárteme un fragmento del HTML real y
     te dejo el parser calibrado).

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

Opcional:
  MAX_PAGES_BANCO_AGRARIO   -> páginas del Banco Agrario a revisar (default 5)
  MAX_PAGES_PUBLICACIONES   -> páginas de Publicaciones Procesales (default 5)
  DEBUG_DUMP_PP=1           -> guarda el HTML crudo de cada página de
                               Publicaciones Procesales para calibrar el parser
"""

import os
import re
import sys
import smtplib
import datetime
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
MAX_PAGES_BANCO_AGRARIO = int(os.environ.get("MAX_PAGES_BANCO_AGRARIO", "5"))
MAX_PAGES_PUBLICACIONES = int(os.environ.get("MAX_PAGES_PUBLICACIONES", "5"))
DEBUG_DUMP_PP = os.environ.get("DEBUG_DUMP_PP", "0") == "1"

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
# FUENTE 2: PUBLICACIONES PROCESALES - RAMA JUDICIAL (portal nuevo)
# =========================================================================

# Cookiejar/opener propio para esta fuente: el portlet de Liferay suele
# necesitar conservar la sesión (JSESSIONID) entre la carga de la página y
# la llamada de filtro, así que reutilizamos el mismo "opener" en todas las
# páginas en vez de usar urllib.request.urlopen directo.
_pp_cookie_jar = http.cookiejar.CookieJar()
_pp_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_pp_cookie_jar))

PP_BASE_URL = "https://publicacionesprocesales.ramajudicial.gov.co/web/publicaciones-procesales/inicio"
PP_PORTLET_ID = "co_com_avanti_efectosProcesales_PublicacionesEfectosProcesalesPortletV2_INSTANCE_BIyXQFHVaYaq"
PP_NS = f"_{PP_PORTLET_ID}_"

# "Remates" según el idStructure que trae el link que compartiste.
PP_ID_STRUCTURE_REMATES = "6098997"

# No tenemos confirmado el código numérico interno de Antioquia/Medellín en
# los combos del portal (no pude inspeccionar el sitio). Por ahora se deja
# el departamento en blanco (equivalente a "Todos", igual que en tu link:
# idDepto=" ") y el filtro real de ciudad se hace en Python sobre el texto
# de cada resultado (ver `es_de_interes`). Si consigues el código exacto de
# Antioquia/Medellín (por ejemplo mirando el <select> del filtro en el
# navegador), ponlo aquí para que el portal ya venga pre-filtrado.
PP_ID_DEPTO = " "
PP_ID_MUNICIPIO = None  # ej: "05001" si llegas a confirmar el código de Medellín

PP_DEPARTAMENTO_OBJETIVO = "ANTIOQUIA"
PP_MUNICIPIO_OBJETIVO = "MEDELLÍN"


def construir_url_publicaciones(pagina: int) -> str:
    params = {
        "p_p_id": PP_PORTLET_ID,
        "p_p_lifecycle": "0",
        "p_p_state": "normal",
        "p_p_mode": "view",
        PP_NS + "idStructure": PP_ID_STRUCTURE_REMATES,
        PP_NS + "action": "filterStructures",
        PP_NS + "idDepto": PP_ID_DEPTO,
        PP_NS + "verTotales": "true",
        PP_NS + "cur": str(pagina),
    }
    if PP_ID_MUNICIPIO:
        params[PP_NS + "idMunicipio"] = PP_ID_MUNICIPIO
    return PP_BASE_URL + "?" + urllib.parse.urlencode(params)


def descargar_publicaciones(url: str, referer: str = None) -> str:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _pp_opener.open(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def es_de_interes(texto: str) -> bool:
    """Filtro de seguridad por si el filtro de Municipio no quedó aplicado
    del lado del servidor (ver nota en la cabecera del archivo)."""
    texto_up = texto.upper()
    return PP_MUNICIPIO_OBJETIVO in texto_up or PP_DEPARTAMENTO_OBJETIVO in texto_up


def extraer_publicaciones(texto: str, html: str, url_pagina: str):
    """
    Heurística genérica para extraer registros de la página de resultados.

    Se apoya en que el número de radicado judicial colombiano (formato
    unificado) tiene 20-23 dígitos y es prácticamente único por proceso,
    sin importar el rediseño del portal. Alrededor de cada radicado se
    busca una fecha (dd/mm/aaaa) y el nombre del despacho.

    ESTO ES UN PUNTO DE PARTIDA, no una extracción confirmada contra el
    HTML real (ver advertencia al inicio del archivo). Actívalo con
    DEBUG_DUMP_PP=1 y ajústalo si hace falta.
    """
    resultados = []
    vistos = set()

    for m in re.finditer(r"\b(\d{20,23})\b", texto):
        radicado = m.group(1)
        if radicado in vistos:
            continue
        vistos.add(radicado)

        inicio = max(0, m.start() - 300)
        fin = min(len(texto), m.end() + 300)
        contexto = re.sub(r"\s+", " ", texto[inicio:fin]).strip()

        fecha_m = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", contexto)
        despacho_m = re.search(r"(JUZGADO[^.\n]{0,80}|TRIBUNAL[^.\n]{0,80})", contexto, re.I)

        resultados.append({
            "radicado": radicado,
            "fecha_texto": fecha_m.group(0) if fecha_m else "No especificada",
            "despacho": despacho_m.group(0).strip() if despacho_m else "No especificado",
            "detalle": contexto[:300],
            "documento": None,
            "fuente": url_pagina,
        })

    # Enlaces a PDF encontrados en la página (no se pueden asociar con
    # certeza a un radicado específico sin ver el HTML real, así que se
    # exponen aparte para revisión manual si hacen falta).
    enlaces_pdf = re.findall(r'href="([^"]+\.pdf[^"]*)"', html, re.I)
    if enlaces_pdf and resultados:
        for i, r in enumerate(resultados):
            if i < len(enlaces_pdf):
                r["documento"] = enlaces_pdf[i]

    return resultados


def recolectar_publicaciones_procesales():
    resultados = []
    referer = PP_BASE_URL
    for pagina in range(1, MAX_PAGES_PUBLICACIONES + 1):
        url = construir_url_publicaciones(pagina)
        try:
            html = descargar_publicaciones(url, referer=referer)
        except Exception as e:
            print(f"[Publicaciones Procesales] Error en página {pagina}: {e}")
            break
        referer = url

        if DEBUG_DUMP_PP:
            nombre_archivo = f"debug_publicaciones_pagina_{pagina}.html"
            with open(nombre_archivo, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[Publicaciones Procesales] HTML crudo guardado en {nombre_archivo}")

        texto = html_a_texto(html)
        registros = extraer_publicaciones(texto, html, url)
        registros = [r for r in registros if es_de_interes(r["detalle"])]

        if not registros:
            break
        resultados.extend(registros)

    vistos, unicos = set(), []
    for r in resultados:
        if r["radicado"] not in vistos:
            vistos.add(r["radicado"])
            unicos.append(r)
    return unicos


# =========================================================================
# CORREO
# =========================================================================

def construir_html(remates_banagrario, avisos_publicaciones):
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

    if avisos_publicaciones:
        filas_pp = ""
        for a in avisos_publicaciones:
            enlace_doc = (
                f'<a href="{a.get("documento")}">Ver documento/aviso oficial (PDF)</a> &nbsp;|&nbsp; '
                if a.get("documento") else ""
            )
            filas_pp += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Despacho:</b> {a.get('despacho')}</p>
              <p style="margin:2px 0;"><b>Radicado:</b> {a.get('radicado')}</p>
              <p style="margin:2px 0;"><b>Fecha:</b> {a.get('fecha_texto')}</p>
              <p style="margin:2px 0;"><b>Detalle:</b> {a.get('detalle')}</p>
              <p style="margin:6px 0;">{enlace_doc}<a href="{a.get('fuente')}">Ver página de resultados</a></p>
            </div>
            """
        seccion_pp = (
            f"<h3>Publicaciones Procesales — Remates en Medellín, Antioquia ({len(avisos_publicaciones)} registro(s))</h3>"
            f"<p style='font-size:12px;color:#888;'>Esta extracción es heurística; verifica cada registro en el enlace de la página de resultados.</p>"
            f"{filas_pp}"
        )
    else:
        seccion_pp = "<h3>Publicaciones Procesales — Remates en Medellín, Antioquia</h3><p>No se encontraron avisos de remate en esta revisión.</p>"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Remates judiciales en Colombia — {hoy}</h2>
        {seccion_ba}
        <hr>
        {seccion_pp}
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

    avisos_publicaciones = recolectar_publicaciones_procesales()
    print(f"Publicaciones Procesales: {len(avisos_publicaciones)} registro(s) encontrado(s)")

    html = construir_html(remates_banagrario, avisos_publicaciones)
    enviar_correo(html, len(remates_banagrario) + len(avisos_publicaciones))


if __name__ == "__main__":
    main()
