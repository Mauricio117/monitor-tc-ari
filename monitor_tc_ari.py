#!/usr/bin/env python3
"""
Monitor del tipo de cambio de "ARI Casa de Cambio Internacional S.A."
en la página de ventanilla del BCCR. Si Compra o Venta suben respecto
a la última corrida, envía una notificación push vía ntfy.sh.

Uso:
    python3 monitor_tc_ari.py

Se recomienda programarlo con cron, por ejemplo cada hora:
    0 * * * * /usr/bin/python3 /ruta/monitor_tc_ari.py >> /ruta/monitor.log 2>&1

CONFIGURA ANTES DE USAR:
    - NTFY_TOPIC: escoge un nombre único (letras/números/guiones) y
      suscríbete a ese mismo topic desde la app de ntfy en tu celular.
"""

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://gee.bccr.fi.cr/IndicadoresEconomicos/Cuadros/frmConsultaTCVentanilla.aspx"
ENTIDAD_BUSCADA = "ARI Casa de Cambio Internacional"
NTFY_TOPIC = "monitor_tc_ari"  # <-- CONFIGURA AQUÍ
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_FILE = Path(__file__).parent / "estado_tc_ari.json"


def obtener_valores():
    """Descarga la página y extrae Compra/Venta de la entidad buscada."""
    resp = requests.get(URL, timeout=20, headers={
        "User-Agent": "Mozilla/5.0 (monitor personal de tipo de cambio)"
    })
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Recorremos todas las filas de tabla buscando la que contenga
    # el nombre de la entidad.
    for tr in soup.find_all("tr"):
        celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
        texto_fila = " ".join(celdas)
        if ENTIDAD_BUSCADA in texto_fila:
            # Extraemos todos los números con formato "123,45" o "123.45"
            numeros = re.findall(r"\d{1,3}(?:[.,]\d{1,2})", texto_fila)
            if len(numeros) < 2:
                raise ValueError(f"No se encontraron suficientes valores en la fila: {celdas}")

            def a_float(s):
                return float(s.replace(",", "."))

            compra = a_float(numeros[0])
            venta = a_float(numeros[1])
            return compra, venta

    raise ValueError(f"No se encontró la entidad '{ENTIDAD_BUSCADA}' en la página.")


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
