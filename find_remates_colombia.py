# ============================================================
# VARIABLES DE GITHUB SECRETS
# ============================================================

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")


# ============================================================
# VALIDAR VARIABLES
# ============================================================

faltantes = []

if not GMAIL_USER:
    faltantes.append("GMAIL_USER")

if not GMAIL_APP_PASSWORD:
    faltantes.append("GMAIL_APP_PASSWORD")

if not RECIPIENT_EMAIL:
    faltantes.append("RECIPIENT_EMAIL")


if faltantes:
    raise RuntimeError(
        "Faltan variables de entorno en GitHub Actions: "
        + ", ".join(faltantes)
    )
