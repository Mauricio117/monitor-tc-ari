#!/usr/bin/env python3
"""
Monitor del tipo de cambio de "ARI Casa de Cambio Internacional S.A."
en la página de ventanilla del BCCR. Si Compra o Venta suben respecto
a la última corrida, envía una notificación push vía ntfy.sh.

Uso:
    python3 monitor_tc_ari.py

CONFIGURA ANTES DE USAR:
    - NTFY_TOPIC: escoge un nombre único (letras/números/guiones) y
      suscríbete a ese mismo topic desde la app de ntfy en tu celular.
"""

import json
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

URL = "https://gee.bccr.fi.cr/IndicadoresEconomicos/Cuadros/frmConsultaTCVentanilla.aspx"
ENTIDAD_BUSCADA = "ARI Casa de Cambio Internacional"
NTFY_TOPIC = "monitor_tc_ari"  # <-- CONFIGURA AQUÍ
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_FILE = Path(__file__).parent / "estado_tc_ari.json"


def obtener_valores():
    resp = requests.get(URL, timeout=20, headers={
        "User-Agent": "Mozilla/5.0 (monitor personal de tipo de cambio)"
    })
    resp.raise_for_status()

    tablas = pd.read_html(
        StringIO(resp.text),
        converters={"Compra": str, "Venta": str},
        thousands=None,
    )

    def normalizar(col):
        # Aplana columnas MultiIndex (tuplas) a un solo string
        if isinstance(col, tuple):
            col = " ".join(str(x) for x in col if str(x).lower() != "nan")
        return str(col).strip().lower()

    df = None
    for t in tablas:
        cols_norm = [normalizar(c) for c in t.columns]
        idx_entidad = next((i for i, c in enumerate(cols_norm) if "entidad autorizada" in c), None)
        idx_compra = next((i for i, c in enumerate(cols_norm) if "compra" in c), None)
        idx_venta = next((i for i, c in enumerate(cols_norm) if "venta" in c), None)

        if idx_entidad is not None and idx_compra is not None and idx_venta is not None:
            t = t.rename(columns={
                t.columns[idx_entidad]: "Entidad Autorizada",
                t.columns[idx_compra]: "Compra",
                t.columns[idx_venta]: "Venta",
            })
            df = t
            break

    if df is None:
        columnas_vistas = [list(t.columns) for t in tablas]
        raise ValueError(
            "No se encontró la tabla esperada. "
            f"Tablas encontradas: {len(tablas)}. Columnas vistas: {columnas_vistas}"
        )

    fila = df[df["Entidad Autorizada"].astype(str).str.contains(ENTIDAD_BUSCADA, case=False, na=False)]
    if fila.empty:
        raise ValueError(f"No se encontró la entidad '{ENTIDAD_BUSCADA}' en la tabla.")

    compra = float(str(fila.iloc[0]["Compra"]).replace(",", "."))
    venta = float(str(fila.iloc[0]["Venta"]).replace(",", "."))
    return compra, venta

def cargar_estado_anterior():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def guardar_estado(compra, venta):
    STATE_FILE.write_text(json.dumps({"compra": compra, "venta": venta}))


def notificar(mensaje, titulo="Tipo de cambio ARI subió"):
    try:
        requests.post(
            NTFY_URL,
            data=mensaje.encode("utf-8"),
            headers={
                "Title": titulo.encode("utf-8"),
                "Priority": "high",
                "Tags": "chart_with_upwards_trend",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"Error enviando notificación a ntfy: {e}", file=sys.stderr)


def main():
    compra, venta = obtener_valores()
    print(f"Valor actual -> Compra: {compra}  Venta: {venta}")

    anterior = cargar_estado_anterior()

    if anterior is None:
        print("Primera corrida, guardando estado inicial sin comparar.")
        guardar_estado(compra, venta)
        return

    subio_compra = compra > anterior["compra"]
    subio_venta = venta > anterior["venta"]

    if subio_compra or subio_venta:
        partes = []
        if subio_compra:
            partes.append(f"Compra: {anterior['compra']} → {compra}")
        if subio_venta:
            partes.append(f"Venta: {anterior['venta']} → {venta}")
        mensaje = "ARI Casa de Cambio subió.\n" + "\n".join(partes)
        print(mensaje)
        notificar(mensaje)
    else:
        print("Sin incrementos respecto a la última corrida.")

    guardar_estado(compra, venta)


if __name__ == "__main__":
    main()
