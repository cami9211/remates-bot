import os
import re
import smtplib
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from email.message import EmailMessage


# ============================================================
# CONFIGURACIÓN
# ============================================================

URL = "https://judiciales.elespectador.com/"

PALABRA_CLAVE = "remate"

# Rango que aparece en la página:
# Aug 10, 26 - Sep 8, 26
FECHA_INICIAL = "10/08/2026"
FECHA_FINAL = "08/09/2026"

# Campos REALES del formulario
CAMPO_PALABRA = "palabras"
CAMPO_FECHA_INICIO = "validez_init"
CAMPO_FECHA_FIN = "validez_fin"

# Secrets de GitHub
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

ARCHIVO_RESULTADOS = "resultados_remates.txt"


# ============================================================
# VALIDAR VARIABLES
# ============================================================

def validar_configuracion():
    faltantes = []

    if not GMAIL_USER:
        faltantes.append("GMAIL_USER")

    if not GMAIL_APP_PASSWORD:
        faltantes.append("GMAIL_APP_PASSWORD")

    if not RECIPIENT_EMAIL:
        faltantes.append("RECIPIENT_EMAIL")

    if faltantes:
        raise RuntimeError(
            "Faltan los siguientes Secrets de GitHub: "
            + ", ".join(faltantes)
        )


# ============================================================
# SESIÓN HTTP
# ============================================================

def crear_sesion():
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })

    return session


# ============================================================
# OBTENER FORMULARIO
# ============================================================

def obtener_formulario(session):
    print("Accediendo a la página...")

    respuesta = session.get(
        URL,
        timeout=90
    )

    respuesta.raise_for_status()

    print(f"Página cargada. HTTP {respuesta.status_code}")

    soup = BeautifulSoup(respuesta.text, "html.parser")

    # Buscar específicamente el formulario que contiene
    # el campo "palabras"
    formulario = soup.find(
        "form",
        lambda tag: tag and tag.find("input", {"name": CAMPO_PALABRA})
    )

    if not formulario:
        raise RuntimeError(
            "No se encontró el formulario de búsqueda."
        )

    return formulario


# ============================================================
# PREPARAR DATOS DEL FORMULARIO
# ============================================================

def preparar_datos(formulario):
    datos = {}

    # Mantener todos los campos hidden existentes.
    for input_tag in formulario.find_all("input"):
        name = input_tag.get("name")

        if not name:
            continue

        input_type = (input_tag.get("type") or "").lower()

        if input_type == "hidden":
            datos[name] = input_tag.get("value", "")

    # --------------------------------------------------------
    # Campos REALES identificados en la página
    # --------------------------------------------------------

    datos[CAMPO_PALABRA] = PALABRA_CLAVE

    datos[CAMPO_FECHA_INICIO] = FECHA_INICIAL

    datos[CAMPO_FECHA_FIN] = FECHA_FINAL

    # Mostrar los campos importantes, sin revelar secretos
    print("\nDatos de búsqueda:")
    print(f"  Palabra clave : {datos[CAMPO_PALABRA]}")
    print(f"  Fecha inicial : {datos[CAMPO_FECHA_INICIO]}")
    print(f"  Fecha final   : {datos[CAMPO_FECHA_FIN]}")

    return datos


# ============================================================
# OBTENER ACTION Y MÉTODO
# ============================================================

def obtener_configuracion_formulario(formulario):
    action = formulario.get("action")

    if not action:
        action = URL

    action = urljoin(URL, action)

    method = (formulario.get("method") or "get").lower()

    if method not in ("get", "post"):
        method = "get"

    print("\nFormulario:")
    print(f"  Action: {action}")
    print(f"  Method: {method.upper()}")

    return action, method


# ============================================================
# EJECUTAR BÚSQUEDA
# ============================================================

def ejecutar_busqueda(session, action, method, datos):
    print("\nEjecutando búsqueda...")

    if method == "post":
        respuesta = session.post(
            action,
            data=datos,
            timeout=90
        )
    else:
        respuesta = session.get(
            action,
            params=datos,
            timeout=90
        )

    respuesta.raise_for_status()

    print(
        f"Búsqueda ejecutada. HTTP {respuesta.status_code}"
    )

    return respuesta


# ============================================================
# EXTRAER RESULTADOS
# ============================================================

def extraer_resultados(soup):
    resultados = []

    # --------------------------------------------------------
    # Primero buscamos enlaces hacia las páginas de detalle.
    #
    # Las páginas de avisos utilizan:
    #
    # detalle.php?idenv=...
    # --------------------------------------------------------

    enlaces = soup.find_all(
        "a",
        href=re.compile(r"detalle\.php", re.I)
    )

    vistos = set()

    for enlace in enlaces:
        href = enlace.get("href")

        if not href:
            continue

        url_detalle = urljoin(URL, href)

        if url_detalle in vistos:
            continue

        vistos.add(url_detalle)

        # Buscar el contenedor que contiene el resultado.
        contenedor = (
            enlace.find_parent("article")
            or enlace.find_parent("li")
            or enlace.find_parent("div", class_=True)
            or enlace.parent
        )

        if contenedor:
            texto = contenedor.get_text(
                " ",
                strip=True
            )
        else:
            texto = enlace.get_text(
                " ",
                strip=True
            )

        texto = re.sub(
            r"\s+",
            " ",
            texto
        ).strip()

        if texto:
            resultados.append({
                "texto": texto,
                "url": url_detalle
            })

    # --------------------------------------------------------
    # Si no encontramos enlaces de detalle, usar bloques de
    # texto como método alternativo.
    # --------------------------------------------------------

    if not resultados:
        print(
            "No se encontraron enlaces detalle.php. "
            "Intentando extracción alternativa..."
        )

        candidatos = soup.find_all(
            string=re.compile(r"\bremate\b", re.I)
        )

        vistos_texto = set()

        for texto_tag in candidatos:
            padre = texto_tag.parent

            if not padre:
                continue

            texto = padre.get_text(
                " ",
                strip=True
            )

            texto = re.sub(
                r"\s+",
                " ",
                texto
            ).strip()

            if not texto:
                continue

            if texto in vistos_texto:
                continue

            vistos_texto.add(texto)

            resultados.append({
                "texto": texto,
                "url": ""
            })

    return resultados


# ============================================================
# EXTRAER DETALLES DE CADA AVISO
# ============================================================

def obtener_detalle(session, resultado):
    url_detalle = resultado["url"]

    if not url_detalle:
        return resultado["texto"]

    try:
        respuesta = session.get(
            url_detalle,
            timeout=90
        )

        respuesta.raise_for_status()

        soup = BeautifulSoup(
            respuesta.text,
            "html.parser"
        )

        # Intentar encontrar el contenido principal.
        contenido = (
            soup.find("main")
            or soup.find("article")
            or soup.find("body")
        )

        if contenido:
            texto = contenido.get_text(
                "\n",
                strip=True
            )
        else:
            texto = resultado["texto"]

        # Limpiar líneas vacías y espacios
        lineas = []

        for linea in texto.splitlines():
            linea = re.sub(
                r"\s+",
                " ",
                linea
            ).strip()

            if linea:
                lineas.append(linea)

        texto_final = "\n".join(lineas)

        if texto_final:
            return texto_final

    except Exception as e:
        print(
            f"No fue posible obtener el detalle "
            f"{url_detalle}: {e}"
        )

    return resultado["texto"]


# ============================================================
# PAGINACIÓN
# ============================================================

def encontrar_paginas(soup):
    paginas = set()

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        texto = enlace.get_text(
            " ",
            strip=True
        ).lower()

        # No seguir páginas de detalle
        if "detalle.php" in href.lower():
            continue

        # Solo enlaces del mismo sitio
        url = urljoin(URL, href)

        parsed = urlparse(url)

        if parsed.netloc and parsed.netloc != urlparse(URL).netloc:
            continue

        # Detectar parámetros típicos de paginación
        href_lower = href.lower()

        parece_paginacion = any(
            parametro in href_lower
            for parametro in [
                "page=",
                "pagina=",
                "pag=",
                "offset=",
                "start="
            ]
        )

        # También aceptar botones numerados / siguiente
        if texto.isdigit():
            parece_paginacion = True

        if any(
            palabra in texto
            for palabra in [
                "siguiente",
                "next",
                "›",
                "»"
            ]
        ):
            parece_paginacion = True

        if parece_paginacion:
            paginas.add(url)

    return paginas


# ============================================================
# BUSCAR TODAS LAS PÁGINAS
# ============================================================

def buscar_todas_las_paginas(
    session,
    primera_respuesta
):
    pendientes = [primera_respuesta.url]
    visitadas = set()

    todos_resultados = {}

    max_paginas = 100

    while pendientes and len(visitadas) < max_paginas:
        url_actual = pendientes.pop(0)

        if url_actual in visitadas:
            continue

        visitadas.add(url_actual)

        print(
            f"\nProcesando página {len(visitadas)}:"
        )
        print(url_actual)

        try:
            if url_actual == primera_respuesta.url:
                respuesta = primera_respuesta
            else:
                respuesta = session.get(
                    url_actual,
                    timeout=90
                )

            respuesta.raise_for_status()

        except Exception as e:
            print(
                f"Error procesando página: {e}"
            )
            continue

        soup = BeautifulSoup(
            respuesta.text,
            "html.parser"
        )

        resultados = extraer_resultados(soup)

        print(
            f"Resultados encontrados en esta página: "
            f"{len(resultados)}"
        )

        for resultado in resultados:
            url = resultado["url"]

            if url:
                clave = url
            else:
                clave = resultado["texto"]

            if clave not in todos_resultados:
                todos_resultados[clave] = resultado

        # Buscar otras páginas
        nuevas_paginas = encontrar_paginas(soup)

        for pagina in nuevas_paginas:
            if pagina not in visitadas:
                if pagina not in pendientes:
                    pendientes.append(pagina)

    print(
        f"\nPáginas procesadas: {len(visitadas)}"
    )

    print(
        f"Resultados únicos encontrados: "
        f"{len(todos_resultados)}"
    )

    return list(todos_resultados.values())


# ============================================================
# GENERAR REPORTE
# ============================================================

def generar_reporte(session, resultados):
    print("\nObteniendo información de los avisos...")

    reporte = []

    for indice, resultado in enumerate(
        resultados,
        start=1
    ):
        print(
            f"  Procesando {indice}/{len(resultados)}"
        )

        detalle = obtener_detalle(
            session,
            resultado
        )

        bloque = []

        bloque.append("=" * 80)
        bloque.append(
            f"RESULTADO #{indice}"
        )
        bloque.append("=" * 80)

        if resultado["url"]:
            bloque.append(
                f"URL: {resultado['url']}"
            )

        bloque.append("")
        bloque.append(detalle)

        reporte.append(
            "\n".join(bloque)
        )

    texto_reporte = "\n\n".join(reporte)

    return texto_reporte


# ============================================================
# GUARDAR ARCHIVO
# ============================================================

def guardar_reporte(texto):
    with open(
        ARCHIVO_RESULTADOS,
        "w",
        encoding="utf-8"
    ) as archivo:
        archivo.write(texto)

    print(
        f"\nReporte guardado en: "
        f"{ARCHIVO_RESULTADOS}"
    )


# ============================================================
# ENVIAR CORREO
# ============================================================

def enviar_correo(texto_reporte, cantidad):
    print("\nEnviando correo...")

    mensaje = EmailMessage()

    mensaje["Subject"] = (
        f"Avisos Judiciales - Remates "
        f"({cantidad} resultados)"
    )

    mensaje["From"] = GMAIL_USER
    mensaje["To"] = RECIPIENT_EMAIL

    mensaje.set_content(
        f"""Consulta automática de Avisos Judiciales.

Palabra clave:
{PALABRA_CLAVE}

Fecha inicial:
{FECHA_INICIAL}

Fecha final:
{FECHA_FINAL}

Resultados encontrados:
{cantidad}

El reporte completo se encuentra adjunto.
"""
    )

    mensaje.add_attachment(
        texto_reporte.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename=ARCHIVO_RESULTADOS
    )

    with smtplib.SMTP(
        "smtp.gmail.com",
        587,
        timeout=90
    ) as servidor:

        servidor.ehlo()
        servidor.starttls()
        servidor.ehlo()

        servidor.login(
            GMAIL_USER,
            GMAIL_APP_PASSWORD
        )

        servidor.send_message(mensaje)

    print("Correo enviado correctamente.")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 80)
    print("BÚSQUEDA AUTOMÁTICA DE REMATES")
    print("=" * 80)

    validar_configuracion()

    session = crear_sesion()

    # --------------------------------------------------------
    # 1. Obtener formulario
    # --------------------------------------------------------

    formulario = obtener_formulario(
        session
    )

    # --------------------------------------------------------
    # 2. Preparar datos
    # --------------------------------------------------------

    datos = preparar_datos(
        formulario
    )

    # --------------------------------------------------------
    # 3. Obtener action/method
    # --------------------------------------------------------

    action, method = obtener_configuracion_formulario(
        formulario
    )

    # --------------------------------------------------------
    # 4. Ejecutar búsqueda
    # --------------------------------------------------------

    respuesta = ejecutar_busqueda(
        session,
        action,
        method,
        datos
    )

    # --------------------------------------------------------
    # 5. Buscar resultados
    # --------------------------------------------------------

    resultados = buscar_todas_las_paginas(
        session,
        respuesta
    )

    # --------------------------------------------------------
    # 6. Validar resultados
    # --------------------------------------------------------

    if not resultados:
        print("\nNo se encontraron resultados.")

        texto_reporte = (
            "No se encontraron avisos judiciales "
            "para los criterios indicados.\n\n"
            f"Palabra clave: {PALABRA_CLAVE}\n"
            f"Fecha inicial: {FECHA_INICIAL}\n"
            f"Fecha final: {FECHA_FINAL}\n"
        )

    else:
        # ----------------------------------------------------
        # 7. Obtener detalle
        # ----------------------------------------------------

        texto_reporte = generar_reporte(
            session,
            resultados
        )

    # --------------------------------------------------------
    # 8. Imprimir resultados
    # --------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("RESULTADOS")
    print("=" * 80)
    print(texto_reporte)

    # --------------------------------------------------------
    # 9. Guardar archivo
    # --------------------------------------------------------

    guardar_reporte(
        texto_reporte
    )

    # --------------------------------------------------------
    # 10. Enviar correo
    # --------------------------------------------------------

    enviar_correo(
        texto_reporte,
        len(resultados)
    )

    print("\n")
    print("=" * 80)
    print("PROCESO FINALIZADO CORRECTAMENTE")
    print("=" * 80)


if __name__ == "__main__":
    main()
