# Bot de oportunidades de remates judiciales (Colombia)

Este automatismo corre varias veces AL DÍA en la nube de GitHub (no en tu
computador), busca oportunidades de inversión en remates y subastas
judiciales vigentes en Colombia (inmuebles, vehículos, lotes, empresas,
etc.) y te envía un resumen por correo electrónico.

## Pasos para activarlo (una sola vez, ~10 minutos)

### 1. Crear el repositorio en GitHub

1. Entra a github.com, haz clic en "New repository".
2. Nómbralo por ejemplo `remates-bot`. Puede ser privado.
3. Sube estos dos archivos manteniendo la misma carpeta:
   - `find_remates_colombia.py`
   - `.github/workflows/remates-colombia.yml`
   - (Puedes arrastrarlos en la interfaz web de GitHub o usar `git push`.)

### 2. Crear tu API key de Anthropic

1. Entra a https://console.anthropic.com
2. Ve a "API Keys" y crea una nueva key.
3. Cópiala (empieza con `sk-ant-...`). Nota: esto usa la API de pago de
   Anthropic (facturación por uso), es independiente de tu cuenta de
   Claude.ai. El costo de correr esta búsqueda 3 veces al día es muy bajo
   (unos pocos centavos de dólar al mes).

### 3. Crear una "contraseña de aplicación" de Gmail

(Necesaria porque Gmail no permite usar tu contraseña normal desde scripts)

1. Activa la verificación en dos pasos en tu cuenta de Gmail si no la tienes.
2. Ve a https://myaccount.google.com/apppasswords
3. Genera una contraseña de aplicación y cópiala (16 caracteres).

### 4. Configurar los "Secrets" en GitHub

En tu repositorio: **Settings → Secrets and variables → Actions → New
repository secret**. Crea estos cuatro secrets:

| Nombre | Valor |
|---|---|
| `ANTHROPIC_API_KEY` | tu key `sk-ant-...` |
| `GMAIL_USER` | tu correo de Gmail que envía el mensaje |
| `GMAIL_APP_PASSWORD` | la contraseña de aplicación de 16 caracteres |
| `RECIPIENT_EMAIL` | el correo donde quieres RECIBIR el resumen |

### 5. Activar las GitHub Actions

1. Ve a la pestaña **Actions** de tu repositorio.
2. Si aparece un botón para habilitar los workflows, haz clic en él.
3. Entra al workflow "Remates judiciales Colombia" y usa **Run workflow**
   para probarlo manualmente la primera vez.
4. Revisa tu correo — deberías recibir el resumen en pocos minutos.

## Frecuencia

Por defecto el bot corre 3 veces al día (8:00 a.m., 12:00 p.m. y 4:00 p.m.
hora Colombia). Puedes cambiar la frecuencia editando la línea `cron` en
`.github/workflows/remates-colombia.yml` (los horarios ahí están en UTC,
y Colombia va 5 horas detrás de UTC).

## Notas importantes

- Este resumen es generado automáticamente por un modelo de IA a partir de
  búsquedas web. **Siempre verifica la información directamente en la
  entidad o portal oficial** (Rama Judicial, SAE, CISA, el banco
  correspondiente, etc.) antes de tomar cualquier decisión.
- Este bot no constituye asesoría legal ni financiera.
- Si algún mes no llegan correos, revisa la pestaña **Actions** de tu
  repositorio para ver si hubo algún error (por ejemplo, un secret mal
  copiado).
