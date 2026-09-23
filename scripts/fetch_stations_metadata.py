#!/usr/bin/env python3
"""
A lancer UNE FOIS (ou chaque fois que tu ajoutes une station) pour completer
automatiquement les lat/lon/altitude manquants dans stations.json, en un
seul appel a l'API Infoclimat portant sur tous les codes a la fois.

Usage :
    export INFOCLIMAT_API_KEY="ta_cle"
    python scripts/fetch_stations_metadata.py

Cela met a jour stations.json sur place. Verifie le resultat avant de
committer (git diff stations.json).
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
STATIONS_FILE = ROOT / "stations.json"

API_KEY = os.environ.get("INFOCLIMAT_API_KEY")
if not API_KEY:
    sys.exit("Erreur : variable d'environnement INFOCLIMAT_API_KEY manquante.")


def fetch_metadata(codes):
    """
    Un seul appel avec tous les codes de station a la fois.

    NB : la structure exacte de la reponse (imbrication des cles) n'a pas pu
    etre verifiee sans compte actif au moment de l'ecriture de ce script --
    ce parsing essaie plusieurs formes plausibles. Si ca ne matche pas,
    lance ce script avec DEBUG=1 pour voir le JSON brut et ajuste
    extract_one() en consequence (2 minutes de travail, la structure est
    generalement auto-explicative).
    """
    params = [
        ("version", "2"),
        ("method", "get"),
        ("format", "json"),
        ("token", API_KEY),
    ]
    for code in codes:
        params.append(("stations[]", code))

    url = "https://www.infoclimat.fr/opendata/?" + urlencode(params)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    if os.environ.get("DEBUG"):
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

    return data


def extract_one(data, code):
    """Essaie plusieurs formes plausibles de reponse pour un code donne."""
    stations_blob = data.get("stations", data)

    entry = None
    if isinstance(stations_blob, dict):
        entry = stations_blob.get(code)
    elif isinstance(stations_blob, list):
        entry = next((s for s in stations_blob if s.get("id") == code), None)

    if not entry:
        return None

    meta = entry.get("metadonnees", entry)
    lat = meta.get("latitude") or meta.get("lat")
    lon = meta.get("longitude") or meta.get("lon")
    alt = meta.get("altitude")
    nom = meta.get("nom") or meta.get("name")

    if lat is None or lon is None:
        return None

    return {
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "altitude": int(alt) if alt is not None else None,
        "nom_api": nom,
    }


def main():
    with open(STATIONS_FILE, encoding="utf-8") as f:
        config = json.load(f)

    codes = [s["infoclimat_code"] for s in config["stations"]]
    print(f"Requete pour {len(codes)} stations en un seul appel...")
    data = fetch_metadata(codes)

    updated, missing = 0, []
    for st in config["stations"]:
        meta = extract_one(data, st["infoclimat_code"])
        if meta:
            st["lat"], st["lon"], st["altitude"] = meta["lat"], meta["lon"], meta["altitude"]
            updated += 1
        elif st["lat"] is None:
            missing.append(st["id"])

    with open(STATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"{updated} stations mises a jour.")
    if missing:
        print("Toujours sans coordonnees (a verifier manuellement) :", ", ".join(missing))
        print("Relance avec DEBUG=1 pour inspecter la reponse brute de l'API.")


if __name__ == "__main__":
    main()
