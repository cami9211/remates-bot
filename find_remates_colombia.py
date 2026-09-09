name: Ejecutar bot de remates judiciales

on:
  schedule:
    - cron: "0 13 * * *"
  workflow_dispatch: {}

jobs:
  consultar:
    runs-on: ubuntu-latest
    steps:
      - name: Clonar repositorio
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # --- ESTE PASO ES EL QUE PROBABLEMENTE FALTA O ESTÁ MAL ---
      - name: Instalar dependencias
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Ejecutar consulta y enviar correo
        env:
          REMATE_BOT_EMAIL: ${{ secrets.REMATE_BOT_EMAIL }}
          REMATE_BOT_EMAIL_PASSWORD: ${{ secrets.REMATE_BOT_EMAIL_PASSWORD }}
          REMATE_BOT_DESTINO: ${{ secrets.REMATE_BOT_DESTINO }}
        run: python find_remates_colombia.py
