#!/usr/bin/env python3
"""
Monitor del tipo de cambio de "ARI Casa de Cambio Internacional S.A."
usando la nueva API del BCCR (SDDE). Notifica por ntfy.sh si Compra
o Venta cambian (suben o bajan) respecto a la última corrida.

CONFIGURA ANTES DE USAR:
    - NTFY_TOPIC: tu topic único de ntfy.sh.
"""

import json
import sys
from pathlib import Path

import requests

API_URL = (
    "https://apim.bccr.fi.cr/SDDE/api/Bccr.GE.SDDE.IndicadoresSitioExterno"
    ".GrupoVariables.API/CuadroPersonalizadoGrupoVariables/ObtenerDatosCuadroPersonalizado"
)
ID_GRUPO_VARIABLE = 1015
ENTIDAD_BUSCADA = "ARI Casa de Cambio Internacional"
NTFY_TOPIC = "CAMBIA-ESTO-por-tu-topic-unico"  # <-- CONFIGURA AQUÍ
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_FILE = Path(__file__).parent / "estado_tc_ari.json"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://sdd.bccr.fi.cr",
    "Referer": "https://sdd.bccr.fi.cr/es/IndicadoresEconomicos/Inicio/Personalizado/2039?Cuadro=1015",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


def obtener_valores():
    """Descarga el JSON de la API nueva y extrae Compra/Venta de la entidad buscada."""
    from datetime import date

    params = {
        "idGrupoVariable": ID_GRUPO_VARIABLE,
        "fechaAConsultar": date.today().isoformat(),
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    # La respuesta puede venir envuelta en una clave (ej. "data" o "resultado").
    # Si data no es una lista directamente, buscamos la primera lista dentro del dict.
    lista = data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                lista = v
                break

    idx_nombre = None
    for i, item in enumerate(lista):
        valor = str(item.get("valorEspanol", ""))
        if ENTIDAD_BUSCADA.lower() in valor.lower():
            idx_nombre = i
            break

    if idx_nombre is None:
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
