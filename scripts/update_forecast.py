#!/usr/bin/env python3
"""
Pipeline quotidien :
1. Va chercher la prevision ICON-CH1 (Tn/Tx de demain) pour chaque station via Open-Meteo.
2. Va chercher l'observation reelle d'hier sur Infoclimat pour verifier la prevision faite hier.
3. Met a jour un biais correctif par station (moyenne mobile exponentielle).
4. Applique ce biais a la prevision du jour -> data/latest.json
5. Archive tout dans data/history.csv

Variables d'environnement attendues :
  INFOCLIMAT_API_KEY   -> clé API Infoclimat (https://www.infoclimat.fr/opendata)
"""

import csv
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATIONS_FILE = ROOT / "stations.json"
HISTORY_FILE = ROOT / "data" / "history.csv"
BIAS_FILE = ROOT / "data" / "bias.json"
LATEST_FILE = ROOT / "data" / "latest.json"

# Poids donné à la nouvelle erreur dans la moyenne mobile exponentielle.
# 0.2-0.3 = correction progressive et stable ; plus haut = réagit plus vite
# mais plus bruité.
ALPHA = 0.25

INFOCLIMAT_API_KEY = os.environ.get("INFOCLIMAT_API_KEY")


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_icon_ch1_forecast(lat, lon):
    """Prevision Tn/Tx de demain (ICON-CH1, MeteoSuisse) via Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "models": "meteoswiss_icon_ch1",
        "timezone": "Europe/Paris",
        "forecast_days": 2,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    # index 0 = aujourd'hui, index 1 = demain
    return {
        "date": d["time"][1],
        "tx": d["temperature_2m_max"][1],
        "tn": d["temperature_2m_min"][1],
    }


def fetch_infoclimat_obs(infoclimat_id, day):
    """
    Observation Tn/Tx reelle pour une station et une date donnee, via l'API
    Open Data Infoclimat (reseau StatIC).

    ATTENTION : le format exact de la requete (parametres, endpoint) doit
    etre confirme depuis ta page https://www.infoclimat.fr/opendata une fois
    connecte : Infoclimat te genere un exemple de requete pret a l'emploi
    pour la zone/station que tu selectionnes. Adapte l'URL et les parametres
    ci-dessous en consequence -- ce qui suit est un point de depart plausible,
    pas une garantie de fonctionner tel quel.
    """
    if not INFOCLIMAT_API_KEY or infoclimat_id in (None, "", "A_REMPLIR"):
        return None

    url = "https://www.infoclimat.fr/opendata/"
    params = {
        "method": "get",
        "format": "json",
        "stations[]": infoclimat_id,
        "start": day.isoformat(),
        "end": day.isoformat(),
        "token": INFOCLIMAT_API_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"  [!] Echec recuperation Infoclimat pour {infoclimat_id}: {e}", file=sys.stderr)
        return None

    # A adapter a la structure reelle renvoyee par l'API (voir doc/exemple
    # Infoclimat). On suppose ici une liste d'observations horaires dont on
    # extrait le min/max de temperature.
    try:
        hourly = payload["stations"][infoclimat_id]["insert_date"]
        temps = [v["temperature"] for v in hourly.values() if v.get("temperature") is not None]
        if not temps:
            return None
        return {"tn": min(temps), "tx": max(temps)}
    except Exception:
        return None


def update_bias(bias_store, station_id, obs, fcst_for_that_day):
    """Met a jour le biais (obs - prevision) par moyenne mobile exponentielle."""
    if obs is None or fcst_for_that_day is None:
        return
    entry = bias_store.setdefault(station_id, {"bias_tn": 0.0, "bias_tx": 0.0})
    err_tn = obs["tn"] - fcst_for_that_day["tn"]
    err_tx = obs["tx"] - fcst_for_that_day["tx"]
    entry["bias_tn"] = (1 - ALPHA) * entry["bias_tn"] + ALPHA * err_tn
    entry["bias_tx"] = (1 - ALPHA) * entry["bias_tx"] + ALPHA * err_tx


def append_history(rows):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_new = not HISTORY_FILE.exists()
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date_maj", "station_id", "date_prevue",
                "prevision_brute_tn", "prevision_brute_tx",
                "prevision_corrigee_tn", "prevision_corrigee_tx",
                "obs_veille_tn", "obs_veille_tx",
            ],
        )
        if is_new:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    config = load_json(STATIONS_FILE, {"stations": [], "zone": {}})
    bias_store = load_json(BIAS_FILE, {})

    today = date.today()
    yesterday = today - timedelta(days=1)

    latest = {"generated_at": today.isoformat(), "zone": config.get("zone"), "stations": []}
    history_rows = []

    for st in config["stations"]:
        sid = st["id"]
        print(f"-> {st['nom']}")

        # 1) prevision brute de demain
        fcst_tomorrow = fetch_icon_ch1_forecast(st["lat"], st["lon"])

        # 2) verification de la prevision faite hier pour aujourd'hui
        #    (on refait un appel "prevision d'hier pour aujourd'hui" en
        #    pratique on relit la ligne archivee correspondante ; ici, pour
        #    rester simple, on relit l'historique local)
        obs_yesterday_target = None
        prev_fcst_for_today = None
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row["station_id"] == sid and row["date_prevue"] == today.isoformat():
                        prev_fcst_for_today = {
                            "tn": float(row["prevision_brute_tn"]),
                            "tx": float(row["prevision_brute_tx"]),
                        }

        obs = fetch_infoclimat_obs(st.get("infoclimat_id"), today)
        update_bias(bias_store, sid, obs, prev_fcst_for_today)

        bias = bias_store.get(sid, {"bias_tn": 0.0, "bias_tx": 0.0})
        corrected = {
            "tn": round(fcst_tomorrow["tn"] + bias["bias_tn"], 1),
            "tx": round(fcst_tomorrow["tx"] + bias["bias_tx"], 1),
        }

        latest["stations"].append({
            "id": sid,
            "nom": st["nom"],
            "lat": st["lat"],
            "lon": st["lon"],
            "date_prevue": fcst_tomorrow["date"],
            "brute": {"tn": fcst_tomorrow["tn"], "tx": fcst_tomorrow["tx"]},
            "corrigee": corrected,
            "biais_applique": {"tn": round(bias["bias_tn"], 2), "tx": round(bias["bias_tx"], 2)},
        })

        history_rows.append({
            "date_maj": today.isoformat(),
            "station_id": sid,
            "date_prevue": fcst_tomorrow["date"],
            "prevision_brute_tn": fcst_tomorrow["tn"],
            "prevision_brute_tx": fcst_tomorrow["tx"],
            "prevision_corrigee_tn": corrected["tn"],
            "prevision_corrigee_tx": corrected["tx"],
            "obs_veille_tn": obs["tn"] if obs else "",
            "obs_veille_tx": obs["tx"] if obs else "",
        })

    save_json(BIAS_FILE, bias_store)
    save_json(LATEST_FILE, latest)
    append_history(history_rows)
    print("Termine.")


if __name__ == "__main__":
    main()
