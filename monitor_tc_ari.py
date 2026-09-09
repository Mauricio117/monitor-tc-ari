#!/usr/bin/env python3
"""
Monitor del tipo de cambio de "ARI Casa de Cambio Internacional S.A."
usando la nueva página del BCCR (SDDE). Como la API interna requiere
una sesión/token generados por el propio JavaScript de la página, este
script abre la página con un navegador headless (Playwright) e
intercepta la respuesta real de red - así no hace falta replicar
manualmente el token ni las cookies.

Notifica por ntfy.sh si Compra o Venta cambian (suben o bajan)
respecto a la última corrida.

CONFIGURA ANTES DE USAR:
    - NTFY_TOPIC: tu topic único de ntfy.sh.
"""

import json
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

PAGINA_URL = "https://sdd.bccr.fi.cr/es/IndicadoresEconomicos/Inicio/Personalizado/2039?Cuadro=1015"
API_URL_FRAGMENTO = "ObtenerDatosCuadroPersonalizado"  # para identificar la respuesta correcta
ENTIDAD_BUSCADA = "ARI Casa de Cambio Internacional"
NTFY_TOPIC = "CAMBIA-ESTO-por-tu-topic-unico"  # <-- CONFIGURA AQUÍ
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_FILE = Path(__file__).parent / "estado_tc_ari.json"


def obtener_valores():
    """Abre la página con Playwright, intercepta la llamada a la API real
    y extrae Compra/Venta de la entidad buscada."""

    datos_capturados = {}

    def manejar_respuesta(response):
        if API_URL_FRAGMENTO in response.url and response.status == 200:
            try:
                datos_capturados["json"] = response.json()
            except Exception:
                pass  # no era JSON válido, ignorar

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("response", manejar_respuesta)

        page.goto(PAGINA_URL, wait_until="networkidle", timeout=30000)
        # Pequeña espera adicional por si la llamada tarda un poco más
        page.wait_for_timeout(3000)

        browser.close()

    if "json" not in datos_capturados:
        raise RuntimeError("No se pudo capturar la respuesta de la API en la página.")

    data = datos_capturados["json"]

    # La respuesta puede venir envuelta en una clave; si no es lista, buscamos
    # la primera lista dentro del dict.
    lista = data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                lista = v
                break

    idx_nombre = None
    for i, item in enumerate(lista):
        if not isinstance(item, dict):
            continue
        valor = str(item.get("valorEspanol", ""))
        if ENTIDAD_BUSCADA.lower() in valor.lower():
            idx_nombre = i
            break

    if idx_nombre is None:
        # Volcamos el JSON completo al log para poder diagnosticar su
        # estructura real si esto vuelve a fallar.
        print("DEBUG - JSON completo capturado:")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])
        raise ValueError(f"No se encontró la entidad '{ENTIDAD_BUSCADA}' en la respuesta.")

    compra_raw = str(lista[idx_nombre + 1]["valorEspanol"])
    venta_raw = str(lista[idx_nombre + 2]["valorEspanol"])

    compra = float(compra_raw.replace(",", "."))
    venta = float(venta_raw.replace(",", "."))
    return compra, venta


def cargar_estado_anterior():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def guardar_estado(compra, venta):
    STATE_FILE.write_text(json.dumps({"compra": compra, "venta": venta}))


def notificar(mensaje, titulo="Tipo de cambio ARI cambió", tag="chart_with_upwards_trend"):
    try:
        requests.post(
            NTFY_URL,
            data=mensaje.encode("utf-8"),
            headers={
                "Title": titulo.encode("utf-8"),
                "Priority": "high",
                "Tags": tag,
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
    bajo_compra = compra < anterior["compra"]
    bajo_venta = venta < anterior["venta"]

    if subio_compra or subio_venta or bajo_compra or bajo_venta:
        partes = []
        if subio_compra:
            partes.append(f"Compra subió: {anterior['compra']} → {compra}")
        if bajo_compra:
            partes.append(f"Compra bajó: {anterior['compra']} → {compra}")
        if subio_venta:
            partes.append(f"Venta subió: {anterior['venta']} → {venta}")
        if bajo_venta:
            partes.append(f"Venta bajó: {anterior['venta']} → {venta}")

        if subio_compra or subio_venta:
            titulo, tag = "Tipo de cambio ARI subió", "chart_with_upwards_trend"
        else:
            titulo, tag = "Tipo de cambio ARI bajó", "chart_with_downwards_trend"

        mensaje = "\n".join(partes)
        print(mensaje)
        notificar(mensaje, titulo=titulo, tag=tag)
    else:
        print("Sin cambios respecto a la última corrida.")

    guardar_estado(compra, venta)


if __name__ == "__main__":
    main()
