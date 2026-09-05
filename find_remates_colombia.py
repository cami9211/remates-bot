"""
Bot de oportunidades de remates judiciales en Colombia
--------------------------------------------------------
Este script:
  1. Le pide a Claude (con la herramienta de búsqueda web) que investigue
     oportunidades vigentes de remates/subastas judiciales en Colombia
     (inmuebles, vehículos, empresas, etc.) que puedan ser interesantes
     como inversión.
  2. Recibe el resultado en formato estructurado (JSON).
  3. Arma un correo en HTML con el resumen y lo envía por Gmail.

Variables de entorno requeridas (se configuran como "Secrets" en GitHub):
  ANTHROPIC_API_KEY   -> API key de https://console.anthropic.com
  GMAIL_USER          -> correo de Gmail que envía el mensaje
  GMAIL_APP_PASSWORD  -> "contraseña de aplicación" de Gmail (16 caracteres)
  RECIPIENT_EMAIL     -> correo que RECIBE el resumen (puede ser el mismo GMAIL_USER)

Opcional:
  MODEL               -> modelo de Anthropic a usar (default: claude-sonnet-4-6)
"""

import os
import sys
import json
import smtplib
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import urllib.request
import urllib.error

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Fuentes típicas de remates judiciales / activos en Colombia que el modelo
# debe priorizar al buscar. Se le pasan como contexto en el prompt.
FUENTES_SUGERIDAS = [
    "Rama Judicial de Colombia - consulta de procesos y edictos de remate",
    "SAE (Sociedad de Activos Especiales) - subastas de activos",
    "CISA (Central de Inversiones S.A.) - ventas y remates de cartera/activos",
    "Superintendencia de Notariado y Registro",
    "Portales de remates: rematesjudiciales.com, elremate.com.co, subastas.gov.co, portalsubastas.com",
    "Remates de bancos (Bancolombia, Davivienda, BBVA, Banco de Bogotá, Banco Agrario)",
    "Boletines judiciales departamentales (Bogotá, Medellín, Cali, Barranquilla)",
]


def construir_prompt():
    hoy = datetime.date.today().isoformat()
    fuentes = "\n".join(f"- {f}" for f in FUENTES_SUGERIDAS)
    return f"""
Hoy es {hoy}. Eres un analista que investiga oportunidades DE INVERSIÓN en
remates y subastas judiciales vigentes en Colombia (inmuebles, vehículos,
lotes, locales comerciales, empresas o activos en general).

Usa la herramienta de búsqueda web para encontrar remates o subastas
ACTUALMENTE ABIERTOS o próximos a realizarse (no remates ya cerrados hace
meses). Prioriza estas fuentes, pero puedes buscar en otras si son
confiables:
{fuentes}

Para cada oportunidad que encuentres y que parezca razonablemente atractiva
como inversión (buen precio base frente al valor de mercado, buena
ubicación, activo en buen estado, proceso claro), devuelve la información.

Responde ÚNICAMENTE con un JSON válido (sin texto adicional, sin markdown,
sin ```), con esta forma exacta:

{{
  "fecha_busqueda": "{hoy}",
  "oportunidades": [
    {{
      "titulo": "string corto describiendo el activo",
      "tipo_activo": "inmueble | vehiculo | empresa | lote | otro",
      "ubicacion": "ciudad/departamento",
      "precio_base": "string con el valor y moneda, ej. '$120.000.000 COP'",
      "valor_estimado_mercado": "string o 'No especificado'",
      "fecha_remate": "string con fecha o 'No especificada'",
      "entidad_o_fuente": "quién organiza el remate",
      "por_que_interesante": "1-2 frases explicando el atractivo de inversión",
      "riesgos": "1-2 frases con riesgos o cosas a verificar",
      "link": "URL directa si está disponible, si no 'No disponible'"
    }}
  ],
  "resumen_general": "2-4 frases resumiendo el panorama de esta búsqueda"
}}

Si no encuentras oportunidades claras y verificables, devuelve un arreglo
"oportunidades" vacío y explica el motivo en "resumen_general". No
inventes datos ni links falsos.
"""


def llamar_claude(prompt: str) -> dict:
    body = {
        "model": MODEL,
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("Error llamando a la API de Anthropic:", e.read().decode("utf-8"))
        raise

    texto = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    texto_limpio = texto.strip()
    if texto_limpio.startswith("```"):
        texto_limpio = texto_limpio.strip("`")
        texto_limpio = texto_limpio.replace("json\n", "", 1)

    try:
        return json.loads(texto_limpio)
    except json.JSONDecodeError:
        print("No se pudo parsear la respuesta como JSON. Respuesta cruda:")
        print(texto)
        return {"fecha_busqueda": datetime.date.today().isoformat(), "oportunidades": [], "resumen_general": "Error al procesar la respuesta del modelo."}


def construir_html(resultado: dict) -> str:
    oportunidades = resultado.get("oportunidades", [])
    resumen = resultado.get("resumen_general", "")
    fecha = resultado.get("fecha_busqueda", datetime.date.today().isoformat())

    if not oportunidades:
        cuerpo = f"<p>No se encontraron oportunidades claras en esta búsqueda.</p><p>{resumen}</p>"
    else:
        filas = ""
        for op in oportunidades:
            link = op.get("link", "No disponible")
            link_html = f'<a href="{link}">Ver fuente</a>' if link and link != "No disponible" else "No disponible"
            filas += f"""
            <div style="border:1px solid #ddd;border-radius:8px;padding:14px;margin-bottom:14px;">
              <h3 style="margin:0 0 6px 0;">{op.get('titulo','(sin título)')}</h3>
              <p style="margin:2px 0;"><b>Tipo:</b> {op.get('tipo_activo','-')} &nbsp; | &nbsp; <b>Ubicación:</b> {op.get('ubicacion','-')}</p>
              <p style="margin:2px 0;"><b>Precio base:</b> {op.get('precio_base','-')} &nbsp; | &nbsp; <b>Valor de mercado estimado:</b> {op.get('valor_estimado_mercado','-')}</p>
              <p style="margin:2px 0;"><b>Fecha del remate:</b> {op.get('fecha_remate','-')} &nbsp; | &nbsp; <b>Fuente:</b> {op.get('entidad_o_fuente','-')}</p>
              <p style="margin:6px 0;"><b>Por qué es interesante:</b> {op.get('por_que_interesante','-')}</p>
              <p style="margin:2px 0;"><b>Riesgos a verificar:</b> {op.get('riesgos','-')}</p>
              <p style="margin:6px 0;">{link_html}</p>
            </div>
            """
        cuerpo = f"<p>{resumen}</p>{filas}"

    return f"""
    <html>
      <body style="font-family:Arial, sans-serif; color:#222;">
        <h2>Remates judiciales en Colombia — {fecha}</h2>
        {cuerpo}
        <hr>
        <p style="font-size:12px;color:#888;">
          Generado automáticamente. Verifica siempre la información directamente
          en la entidad o portal oficial antes de tomar cualquier decisión de
          inversión. Este resumen no constituye asesoría legal ni financiera.
        </p>
      </body>
    </html>
    """


def enviar_correo(html: str, num_oportunidades: int):
    if not (GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL):
        print("Faltan variables de correo (GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL). No se envía correo.")
        return

    asunto = f"Remates judiciales Colombia — {num_oportunidades} oportunidad(es) — {datetime.date.today().isoformat()}"

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
    if not ANTHROPIC_API_KEY:
        print("Falta ANTHROPIC_API_KEY.")
        sys.exit(1)

    prompt = construir_prompt()
    resultado = llamar_claude(prompt)
    num = len(resultado.get("oportunidades", []))
    print(f"Oportunidades encontradas: {num}")

    html = construir_html(resultado)
    enviar_correo(html, num)


if __name__ == "__main__":
    main()
