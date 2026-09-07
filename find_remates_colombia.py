"""
Bot de remates/subastas judiciales (SIN IA, 100% gratis)
--------------------------------------------------------------------------------
Una sola fuente, leída directamente sin ninguna API de IA:

  Buscador de Edictos de Asuntos Legales / La República, filtrando por
  la categoría REMATES
  https://www.asuntoslegales.com.co/edictos

No existe una URL de listado paginado de solo lectura (el buscador
visible funciona con JavaScript), así que en su lugar se hace un
rastreo por enlaces: cada página de detalle (/edictos/detalle/<id>)
trae al final un bloque "MÁS EDICTOS Y AVISOS LEGALES" con enlaces
"Continuar leyendo" hacia otros avisos recientes. Partiendo de unos
pocos avisos semilla, el bot sigue esos enlaces en cadena (una cola de
IDs por visitar) y se queda solo con los avisos cuya categoría propia
sea "REMATES". NOTA: este rastreo depende de que el sitio siga
mostrando ese bloque de enlaces con la misma estructura; si Asuntos
Legales cambia el diseño de la página, el patrón de extracción
(AL_BLOQUE_RE más abajo) puede necesitar ajuste.

Un aviso solo se incluye en el resultado final si cumple TODAS estas
condiciones:

  1. El texto menciona "remate" o "subasta" (en cualquier variante:
     remate, remates, rematar, subasta, subastar, etc.).
  2. Se le pudo extraer una fecha de remate y esa fecha es hoy o
     posterior (se descartan remates ya vencidos o sin fecha detectable).

El resultado se limita a un máximo de 20 avisos, ordenados por fecha
de remate más próxima primero.

Además, para cada aviso que pasa el filtro se extraen campos
estructurados por expresiones regulares: avalúo, postura mínima, fecha
de remate, radicado, juzgado/entidad, ubicación, dirección y secuestre.
Como esto es puro parseo de texto (sin IA), la extracción es heurística:
cuando un dato no se logra identificar, el campo se marca explícitamente
como "No especificado en el aviso" en vez de omitirse o inventarse.

Variables de entorno requeridas (Secrets en GitHub):
  GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

Opcional:
  MAX_RESULTADOS           -> tope de remates/subastas en el resultado final (default 20)
  MAX_AVISOS_REVISADOS_AL  -> tope de avisos de Asuntos Legales visitados durante el rastreo por enlaces (default 300)
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
MAX_RESULTADOS = int(os.environ.get("MAX_RESULTADOS", "20"))
MAX_AVISOS_REVISADOS_AL = int(os.environ.get("MAX_AVISOS_REVISADOS_AL", "300"))

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
# PATRONES DE EXTRACCIÓN COMPARTIDOS
# =========================================================================

RADICADO_RE = re.compile(r"radicad[oa]\s*(?:no\.?|número)?\s*:?\s*([0-9][0-9\-\.]{8,30})", re.I)

# Filtro: solo nos interesan avisos que mencionen remate o subasta
# (cubre variantes: remate, remates, rematar, rematará, subasta, subastar, etc.)
MENCIONA_REMATE_RE = re.compile(r"remat|subast", re.I)

NO_ESPECIFICADO = "No especificado en el aviso"

MESES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MESES = "|".join(MESES_NUM.keys())

AVALUO_RE = re.compile(r"avalú[oó][^\$\n]{0,40}\$\s*([\d\.,]+)", re.I)
POSTURA_PORCENTAJE_RE = re.compile(r"postura\s+(?:admisible|m[ií]nima)[^\d%]{0,20}(\d{1,3}\s*%)", re.I)
POSTURA_MONTO_RE = re.compile(
    r"postura\s+(?:admisible|m[ií]nima)[^\$\n]{0,60}\$\s*([\d\.,]+)"
    r"|equivalente\s+a\s*\$\s*([\d\.,]+)",
    re.I,
)
FECHA_REMATE_RE = re.compile(
    rf"(\d{{1,2}})\s+de\s+({MESES})\s+de\s+(\d{{4}})", re.I
)
HORA_REMATE_RE = re.compile(r"a\s+la[s]?\s+([\d:]{1,5}\s*[ap]\.?\s*m\.?)", re.I)
SECUESTRE_RE = re.compile(
    r"secuestre\s+([^,\n]{3,80}?)(?:,|\.\s+[A-ZÁÉÍÓÚ]|$)", re.I
)
DIRECCION_RE = re.compile(
    r"((?:calle|cra\.?|carrera|cll\.?|diagonal|dg\.?|transversal|tv\.?|avenida|"
    r"av\.?|circular)\s+\d+.{0,60}?)(?:,|\.\s+[A-ZÁÉÍÓÚ]|$)",
    re.I,
)
DEPARTAMENTOS = (
    "Antioquia|Cundinamarca|Valle del Cauca|Santander|Bol[ií]var|Atl[áa]ntico|"
    "Meta|Caldas|Risaralda|Quind[ií]o|Tolima|Huila|Nari[ñn]o|Cauca|C[óo]rdoba|"
    "Sucre|Magdalena|Cesar|Norte de Santander|Boyac[áa]|Casanare|Arauca|"
    "Choc[óo]|La Guajira|Putumayo|Caquet[áa]"
)
UBICACION_RE = re.compile(rf"([A-ZÁÉÍÓÚÑa-záéíóúñ\.\s]{{3,40}}),\s*({DEPARTAMENTOS})\b")

ENTIDAD_PREFIJO_RE = re.compile(
    r"^(aviso\s+de\s+remate|cartel\s+del\s+remate|aviso\s+de\s+emplazamiento|"
    r"notificaci[oó]n\s+por\s+aviso|edicto\s+emplazatorio|edicto\s+emplazatario|"
    r"edicto|aviso)\s*[:\.]?\s*",
    re.I,
)
ENTIDAD_FIN_RE = re.compile(
    r"\b(hace\s+saber|informa|avisa|emplaza|cita\s+y\s+emplaza|convoca|"
    r"notifica|comunica|hace\s+constar)\b",
    re.I,
)


def _limpiar_monto(s):
    return s.strip().strip(".,")


def extraer_avaluo(texto):
    m = AVALUO_RE.search(texto)
    return f"${_limpiar_monto(m.group(1))}" if m else NO_ESPECIFICADO


def extraer_postura_minima(texto):
    porcentaje = POSTURA_PORCENTAJE_RE.search(texto)
    monto_m = POSTURA_MONTO_RE.search(texto)
    monto = None
    if monto_m:
        monto = _limpiar_monto(monto_m.group(1) or monto_m.group(2))
    if porcentaje and monto:
        return f"{porcentaje.group(1).strip()} del avalúo (${monto})"
    if monto:
        return f"${monto}"
    if porcentaje:
        return f"{porcentaje.group(1).strip()} del avalúo"
    return NO_ESPECIFICADO


def extraer_fecha_remate(texto):
    """Devuelve (fecha_obj_o_None, texto_formateado). fecha_obj es un
    datetime.date solo cuando el día/mes/año se pudieron interpretar."""
    m = FECHA_REMATE_RE.search(texto)
    if not m:
        return None, NO_ESPECIFICADO
    dia, mes_txt, anio = m.groups()
    mes_num = MESES_NUM.get(mes_txt.lower())
    fecha_obj = None
    if mes_num:
        try:
            fecha_obj = datetime.date(int(anio), mes_num, int(dia))
        except ValueError:
            fecha_obj = None
    fecha_formateada = f"{dia} de {mes_txt.lower()} de {anio}"
    hora_m = HORA_REMATE_RE.search(texto)
    if hora_m:
        fecha_formateada += f", {hora_m.group(1).strip()}"
    return fecha_obj, fecha_formateada


def extraer_ubicacion(texto):
    m = UBICACION_RE.search(texto)
    if not m:
        return NO_ESPECIFICADO
    return f"{m.group(1).strip(' ,.')}, {m.group(2)}"


def extraer_direccion(texto):
    m = DIRECCION_RE.search(texto)
    return m.group(1).strip(" ,.") if m else NO_ESPECIFICADO


def extraer_secuestre(texto):
    m = SECUESTRE_RE.search(texto)
    return m.group(1).strip(" ,.").title() if m else NO_ESPECIFICADO


def extraer_entidad(texto):
    limpio = ENTIDAD_PREFIJO_RE.sub("", texto, count=1)
    fin_m = ENTIDAD_FIN_RE.search(limpio)
    entidad = limpio[:fin_m.start()] if fin_m else limpio[:140]
    entidad = entidad.strip(" :.-")
    return entidad if entidad else NO_ESPECIFICADO


def extraer_campos(texto_descripcion, radicado_ya_extraido):
    return {
        "entidad": extraer_entidad(texto_descripcion),
        "radicado": radicado_ya_extraido or NO_ESPECIFICADO,
        "avaluo": extraer_avaluo(texto_descripcion),
        "postura_minima": extraer_postura_minima(texto_descripcion),
        "ubicacion": extraer_ubicacion(texto_descripcion),
        "direccion": extraer_direccion(texto_descripcion),
        "secuestre": extraer_secuestre(texto_descripcion),
    }


# =========================================================================
# ASUNTOS LEGALES (LA REPÚBLICA) - BUSCADOR DE EDICTOS, CATEGORÍA "REMATES"
# =========================================================================

AL_BASE_URL = "https://www.asuntoslegales.com.co"

# Cada aviso vive en /edictos/detalle/<id>, con ids del tipo "003_VEF_17306-1-1".
AL_DETALLE_ID_RE = re.compile(r"/edictos/detalle/([A-Za-z0-9_\-]+)")

# Bloque principal de una página de detalle: justo debajo del título
# "Edictos y Avisos Legales" viene la categoría propia del aviso (p. ej.
# "REMATES", "NOTARIAS", "ART 450"), luego su fecha propia, y después el
# texto completo, hasta llegar al bloque de publicidad
# ("¿Quiere publicar su edicto en línea?") o a la sección de sugeridos
# ("MÁS EDICTOS Y AVISOS LEGALES").
AL_BLOQUE_RE = re.compile(
    r"Edictos y Avisos Legales\s*\n"
    r"(?:[\s\-]*\n)*"
    r"([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 ]{2,25})\s*\n+"
    r"(\d{1,2} de [a-záéíóúñ]+ de \d{4})\s*\n+"
    r"(.*?)"
    r"\n+\s*(?:¿Quiere publicar su edicto en línea\?|MÁS EDICTOS Y AVISOS LEGALES)",
    re.S,
)

# Avisos semilla desde los que arranca el rastreo por enlaces (ver
# explicación al inicio del archivo). Sirven solo como punto de partida;
# el bot descubre el resto siguiendo los enlaces "Continuar leyendo".
# Si el sitio los retira o cambia el formato de sus ids, se recomienda
# reemplazarlos por ids de avisos vigentes tomados del propio sitio.
AL_SEMILLAS = [
    "003_VEF_17306-1-1",
    "002_VEF_27226-1-1",
    "009_VEF_4557-6-1",
    "008_VEF_4071-2-1",
    "003_VEF_16383-11-1",
]

CATEGORIA_REMATES = "REMATES"


def extraer_bloque_asuntoslegales(html):
    """Devuelve (categoria, fecha_publicado_texto, cuerpo_completo) del
    aviso propio de una página de detalle de Asuntos Legales, o
    (None, None, None) si no se pudo reconocer el patrón esperado."""
    texto = html_a_texto(html)
    m = AL_BLOQUE_RE.search(texto)
    if not m:
        return None, None, None
    categoria = m.group(1).strip()
    fecha_publicado_texto = m.group(2).strip()
    cuerpo = re.sub(r"\s+", " ", m.group(3)).strip()
    return categoria, fecha_publicado_texto, cuerpo


def recolectar_remates_asuntoslegales():
    """Rastrea Asuntos Legales siguiendo los enlaces "Continuar leyendo"
    entre avisos (no hay un listado paginado de solo lectura), y se
    queda con los avisos de la categoría REMATES que mencionen
    remate/subasta y tengan fecha de remate futura."""
    hoy = datetime.date.today()
    resultados = []
    visitados = set()
    cola = list(AL_SEMILLAS)
    avisos_revisados = 0

    while cola and avisos_revisados < MAX_AVISOS_REVISADOS_AL:
        id_aviso = cola.pop(0)
        if id_aviso in visitados:
            continue
        visitados.add(id_aviso)
        avisos_revisados += 1

        url_detalle = f"{AL_BASE_URL}/edictos/detalle/{id_aviso}"
        try:
            html = descargar(url_detalle)
        except Exception as e:
            print(f"[AsuntosLegales] Error abriendo {id_aviso}: {e}")
            continue

        # Alimentar la cola con los avisos enlazados en "MÁS EDICTOS Y
        # AVISOS LEGALES" para seguir rastreando, sin duplicados.
        for nuevo_id in AL_DETALLE_ID_RE.findall(html):
            if nuevo_id not in visitados and nuevo_id not in cola:
                cola.append(nuevo_id)

        categoria, fecha_publicado_texto, cuerpo = extraer_bloque_asuntoslegales(html)
        if not categoria or categoria.upper() != CATEGORIA_REMATES:
            continue
        if not cuerpo or not MENCIONA_REMATE_RE.search(cuerpo):
            continue

        fecha_remate_obj, fecha_remate_texto = extraer_fecha_remate(cuerpo)
        if fecha_remate_obj is None or fecha_remate_obj < hoy:
            continue

        radicado_m = RADICADO_RE.search(cuerpo)
        radicado = radicado_m.group(1).strip(" .,") if radicado_m else None
        campos = extraer_campos(cuerpo, radicado)

        aviso = {
            "id": id_aviso,
            "descripcion": cuerpo,
            "fecha_publicado_texto": fecha_publicado_texto or NO_ESPECIFICADO,
            "fecha_remate": fecha_remate_texto,
            "fecha_remate_obj": fecha_remate_obj,
            "link": url_detalle,
            "fuente": "Asuntos Legales",
        }
        aviso.update(campos)
        resultados.append(aviso)

    print(f"[AsuntosLegales] {avisos_revisados} aviso(s) revisados, {len(resultados)} remates cumplen los filtros")
    resultados.sort(key=lambda a: a["fecha_remate_obj"])
    return resultados


# =========================================================================
# CORREO
# =========================================================================

def _campo_html(icono, etiqueta, valor):
    faltante = (valor == NO_ESPECIFICADO)
    color_valor = "#9a9a9a" if faltante else "#1f2937"
    estilo_valor = "italic" if faltante else "normal"
    return f"""
    <tr>
      <td style="padding:6px 10px 6px 0; vertical-align:top; white-space:nowrap; width:34%;">
        <span style="font-size:12px; letter-spacing:.03em; text-transform:uppercase; color:#6b7280; font-weight:700;">
          {icono} {etiqueta}
        </span>
      </td>
      <td style="padding:6px 0; vertical-align:top; font-size:14px; color:{color_valor}; font-style:{estilo_valor};">
        {valor}
      </td>
    </tr>
    """


def _tarjeta_aviso(e, numero):
    campos_html = "".join([
        _campo_html("🏛️", "Juzgado / entidad", e.get("entidad")),
        _campo_html("🧾", "Radicado", e.get("radicado")),
        _campo_html("📅", "Fecha de remate", e.get("fecha_remate")),
        _campo_html("💰", "Avalúo", e.get("avaluo")),
        _campo_html("💵", "Postura mínima", e.get("postura_minima")),
        _campo_html("📍", "Ubicación", e.get("ubicacion")),
        _campo_html("🏠", "Dirección", e.get("direccion")),
        _campo_html("👤", "Secuestre", e.get("secuestre")),
    ])

    fuente = e.get("fuente", NO_ESPECIFICADO)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:#ffffff; border:1px solid #e5e7eb; border-radius:12px;
                  margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
      <tr>
        <td style="padding:18px 22px;">

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="font-size:12px; color:#ffffff; background:#1e3a5f; display:inline-block;
                         padding:4px 10px; border-radius:999px; font-weight:700;">
                REMATE #{numero}
              </td>
              <td style="text-align:right; font-size:12px; color:#6b7280;">
                {fuente} · Publicado: <b>{e.get('fecha_publicado_texto')}</b>
              </td>
            </tr>
          </table>

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;">
            {campos_html}
          </table>

          <div style="margin-top:14px; border-top:1px dashed #e5e7eb; padding-top:12px;">
            <div style="font-size:12px; letter-spacing:.03em; text-transform:uppercase; color:#6b7280; font-weight:700; margin-bottom:6px;">
              📄 Texto completo del edicto
            </div>
            <div style="background:#f9fafb; border-radius:8px; padding:12px 14px; font-size:13px;
                        line-height:1.55; color:#374151; max-height:none;">
              {e.get('descripcion')}
            </div>
          </div>

          <div style="margin-top:14px;">
            <a href="{e.get('link')}"
               style="display:inline-block; font-size:13px; font-weight:700; color:#1e3a5f;
                      text-decoration:none; border:1px solid #1e3a5f; padding:8px 14px; border-radius:8px;">
              Ver aviso original en {fuente} →
            </a>
          </div>

        </td>
      </tr>
    </table>
    """


def construir_html(edictos):
    hoy = datetime.date.today().strftime("%d/%m/%Y")

    if edictos:
        tarjetas = "".join(_tarjeta_aviso(e, i + 1) for i, e in enumerate(edictos))
        cuerpo = tarjetas
    else:
        cuerpo = """
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; padding:24px;">
          <tr><td style="font-size:14px; color:#374151;">
            No se encontraron remates o subastas con fecha futura en esta revisión.
          </td></tr>
        </table>
        """

    return f"""
    <html>
      <head><meta charset="utf-8"></head>
      <body style="margin:0; padding:0; background:#f3f4f6; font-family:Arial, Helvetica, sans-serif;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6; padding:24px 0;">
          <tr>
            <td align="center">
              <table role="presentation" width="680" cellpadding="0" cellspacing="0" style="max-width:680px; width:100%;">

                <tr>
                  <td style="background:#1e3a5f; border-radius:12px 12px 0 0; padding:22px 26px;">
                    <div style="font-size:20px; color:#ffffff; font-weight:800;">
                      ⚖️ Remates y subastas judiciales próximos
                    </div>
                    <div style="font-size:13px; color:#c9d6e5; margin-top:4px;">
                      Asuntos Legales (La República) · {hoy} · {len(edictos)} de hasta {MAX_RESULTADOS} resultado(s)
                    </div>
                  </td>
                </tr>

                <tr>
                  <td style="padding:22px 4px 4px 4px;">
                    {cuerpo}
                  </td>
                </tr>

                <tr>
                  <td style="padding:6px 22px 22px 22px;">
                    <p style="font-size:11px; color:#9ca3af; line-height:1.5; margin:0;">
                      Fuente: categoría REMATES del buscador de Edictos de Asuntos Legales
                      (La República). Solo se incluyen avisos que mencionan remate o subasta y
                      cuya fecha de remate detectada es igual o posterior a hoy ({hoy}), ordenados
                      del más próximo al más lejano, hasta un máximo de {MAX_RESULTADOS}. Los campos (avalúo, postura
                      mínima, fecha de remate, radicado, entidad, ubicación, dirección y
                      secuestre) se extraen automáticamente del texto del aviso mediante reglas
                      de texto, sin intervención de IA; cuando un dato no se logra identificar,
                      el campo se marca como "No especificado en el aviso". Verifica siempre la
                      información directamente en el aviso original antes de tomar cualquier
                      decisión legal o financiera. Este resumen no constituye asesoría legal ni
                      financiera.
                    </p>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def enviar_correo(html: str, total: int):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return

    asunto = f"Remates y subastas judiciales (Asuntos Legales) — {total} resultado(s) — {datetime.date.today().isoformat()}"
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
    edictos = recolectar_remates_asuntoslegales()
    edictos = edictos[:MAX_RESULTADOS]

    print(f"Remates/subastas encontrados en Asuntos Legales: {len(edictos)}")

    html = construir_html(edictos)
    enviar_correo(html, len(edictos))


if __name__ == "__main__":
    main()
