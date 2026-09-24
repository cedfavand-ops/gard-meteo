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
    """Un seul appel avec tous les codes de station a la fois."""
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
    """Structure reelle confirmee : data['stations'] est une LISTE de dicts
    {id, name, latitude, longitude, elevation, ...}."""
    for entry in data.get("stations", []):
        if entry.get("id") == code:
            lat, lon, alt = entry.get("latitude"), entry.get("longitude"), entry.get("elevation")
            if lat is None or lon is None:
                return None
            return {
                "lat": round(float(lat), 5),
                "lon": round(float(lon), 5),
                "altitude": int(alt) if alt is not None else None,
                "nom_api": entry.get("name"),
            }
    return None


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
