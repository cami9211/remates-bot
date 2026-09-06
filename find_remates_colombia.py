"""
Bot de edictos judiciales - Clasificados El Colombiano (SIN IA, 100% gratis)
--------------------------------------------------------------------------------
Fuente única: Clasificados "Judiciales / Edictos" de El Colombiano
(masificados.com), leída directamente sin ninguna API de IA.

  https://www.masificados.com/otros/avisos/judiciales/edictos

El listado se revisa página por página (más recientes primero) y para
cada aviso se abre su página de detalle para extraer el texto completo
del edicto (el listado solo muestra un resumen truncado).

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

Opcional:
  MAX_PAGINAS_EDICTOS -> páginas del listado a revisar (default 2, 50 avisos c/u)
  MAX_AVISOS          -> tope de avisos a abrir en detalle (default 60)
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
MAX_PAGINAS_EDICTOS = int(os.environ.get("MAX_PAGINAS_EDICTOS", "2"))
MAX_AVISOS = int(os.environ.get("MAX_AVISOS", "60"))

HEADERS = {"User-Agent": "Mozilla/5.0 (edictos-bot; uso personal)"}


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
    return texto.strip()


# =========================================================================
# CLASIFICADOS EL COLOMBIANO - JUDICIALES / EDICTOS
# =========================================================================

BASE_URL_EDICTOS = "https://www.masificados.com/otros/avisos/judiciales/edictos"

# Cada aviso vive en /otros/ocasional/{id_categoria}/aviso/{id_aviso}/
AVISO_URL_RE = re.compile(r"/otros/ocasional/(\d+)/aviso/(\d+)/")

FECHA_PUBLICADO_RE = re.compile(r"Publicado:\s*(\d{2})/(\d{2})/(\d{4})")
OG_DESCRIPTION_RE = re.compile(
    r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']\s*/?>',
    re.S | re.I,
)
RADICADO_RE = re.compile(r"radicad[oa]\s*(?:no\.?|número)?\s*:?\s*([0-9][0-9\-\.]{8,30})", re.I)


def listar_ids_avisos():
    """Recorre las páginas del listado (ya viene ordenado por más recientes)
    y devuelve los IDs de aviso en el mismo orden, sin duplicados."""
    ids_vistos = []
    ids_set = set()
    for pagina in range(1, MAX_PAGINAS_EDICTOS + 1):
        url_pagina = f"{BASE_URL_EDICTOS}?max_per_page=50&search_results_view=lineal&page={pagina}"
        try:
            html = descargar(url_pagina)
        except Exception as e:
            print(f"[Edictos] Error en página {pagina}: {e}")
            break
        encontrados = AVISO_URL_RE.findall(html)
        if not encontrados:
            break
        for _id_categoria, id_aviso in encontrados:
            if id_aviso not in ids_set:
                ids_set.add(id_aviso)
                ids_vistos.append(id_aviso)
        if len(ids_vistos) >= MAX_AVISOS:
            break
    return ids_vistos[:MAX_AVISOS]


def parse_fecha_publicado(html):
    m = FECHA_PUBLICADO_RE.search(html)
    if not m:
        return None
    dia, mes, anio = m.groups()
    try:
        return datetime.date(int(anio), int(mes), int(dia))
    except ValueError:
        return None


def extraer_descripcion(html):
    # La meta og:description trae el texto completo del edicto (más
    # confiable que intentar parsear el bloque visible de la página).
    m = OG_DESCRIPTION_RE.search(html)
    if m:
        desc = m.group(1)
        desc = desc.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
        return re.sub(r"\s+", " ", desc).strip()

    # Respaldo: extraer el bloque "Descripción" del cuerpo visible.
    texto = html_a_texto(html)
    m = re.search(r"Descripci[oó]n\s*\n+(.+?)(?:\n\s*Denunciar|\n\s*Avisos similares|$)", texto, re.S | re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return "Descripción no disponible, revisa el aviso en el enlace."


def recolectar_edictos():
    ids = listar_ids_avisos()
    print(f"[Edictos] {len(ids)} aviso(s) encontrados en el listado")

    avisos = []
    for id_aviso in ids:
        # El id de categoría exacto no es necesario para acceder al aviso;
        # el sitio redirige correctamente aunque se use un valor genérico.
        url_detalle = f"https://www.masificados.com/otros/ocasional/0/aviso/{id_aviso}/"
        try:
            html = descargar(url_detalle)
        except Exception as e:
            print(f"[Edictos] Error abriendo aviso {id_aviso}: {e}")
            continue

        descripcion = extraer_descripcion(html)
        fecha = parse_fecha_publicado(html)
        radicado_m = RADICADO_RE.search(descripcion)

        avisos.append({
            "id": id_aviso,
            "descripcion": descripcion,
            "fecha_publicado": fecha,
            "fecha_publicado_texto": fecha.strftime("%d/%m/%Y") if fecha else "No especificada",
            "radicado": radicado_m.group(1).strip() if radicado_m else None,
            "link": url_detalle,
        })

    avisos.sort(key=lambda a: (a["fecha_publicado"] is None, a["fecha_publicado"]), reverse=True)
    return avisos


# =========================================================================
# CORREO
# =========================================================================

def construir_html(edictos):
    hoy = datetime.date.today().isoformat()

    if edictos:
        filas = ""
        for e in edictos:
            radicado_html = f"<p style='margin:2px 0;'><b>Radicado:</b> {e['radicado']}</p>" if e.get("radicado") else ""
            filas += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <p style="margin:2px 0;"><b>Publicado:</b> {e.get('fecha_publicado_texto')}</p>
              {radicado_html}
              <p style="margin:6px 0;">{e.get('descripcion')}</p>
              <p style="margin:6px 0;"><a href="{e.get('link')}">Ver aviso completo en Masificados / El Colombiano</a></p>
            </div>
            """
        seccion = f"<h3>Edictos judiciales - Clasificados El Colombiano ({len(edictos)} aviso(s))</h3>{filas}"
    else:
        seccion = "<h3>Edictos judiciales - Clasificados El Colombiano</h3><p>No se encontraron edictos en esta revisión.</p>"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Edictos judiciales más recientes — {hoy}</h2>
        {seccion}
        <hr>
        <p style="font-size:12px;color:#888;">
          Verifica siempre la información directamente en el aviso original
          antes de tomar cualquier decisión legal o financiera.
          Este resumen no constituye asesoría legal ni financiera.
        </p>
      </body>
    </html>
    """


def enviar_correo(html: str, total: int):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return

    asunto = f"Edictos judiciales El Colombiano — {total} resultado(s) — {datetime.date.today().isoformat()}"
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
    edictos = recolectar_edictos()
    print(f"Edictos: {len(edictos)} aviso(s) recolectados")

    html = construir_html(edictos)
    enviar_correo(html, len(edictos))


if __name__ == "__main__":
    main()
