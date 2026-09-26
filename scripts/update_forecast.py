#!/usr/bin/env python3
"""
Pipeline quotidien :
1. Va chercher la prevision ICON-CH1 (Tn/Tx de demain), pour un run precis
   (12z ou 15z), pour chaque station via la Single Runs API d'Open-Meteo.
2. Va chercher en un seul appel les observations reelles d'hier sur
   Infoclimat pour verifier la prevision faite hier pour chaque station.
3. Met a jour un biais correctif par station (moyenne mobile exponentielle).
4. Applique ce biais a la prevision du jour -> data/latest.json
5. Archive tout dans data/history.csv

Variables d'environnement attendues :
  INFOCLIMAT_API_KEY   -> clé API Infoclimat (https://www.infoclimat.fr/opendata)

Pre-requis : stations.json doit avoir lat/lon renseignes (lancer d'abord
scripts/fetch_stations_metadata.py si ce n'est pas deja fait).
"""

import csv
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
STATIONS_FILE = ROOT / "stations.json"
HISTORY_FILE = ROOT / "data" / "history.csv"
BIAS_FILE = ROOT / "data" / "bias.json"
LATEST_FILE = ROOT / "data" / "latest.json"

ALPHA = 0.25
RUN_HOUR_UTC = 12  # ou 15, selon ta préférence

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


def fetch_icon_ch1_forecast(lat, lon, run_date, run_hour=RUN_HOUR_UTC):
    run_iso = f"{run_date.isoformat()}T{run_hour:02d}:00"
    target_day = run_date + timedelta(days=1)

    url = "https://single-runs-api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "models": "meteoswiss_icon_ch1",
        "run": run_iso,
        "timezone": "Europe/Paris",
    }
    r = requests.get(url, params=params, timeout=30)
    if not r.ok:
        print(f"  [!] Open-Meteo a renvoye une erreur {r.status_code} : {r.text[:500]}", file=sys.stderr)
    r.raise_for_status()
    hourly = r.json()["hourly"]

    temps_du_jour = [
        t for time_str, t in zip(hourly["time"], hourly["temperature_2m"])
        if time_str.startswith(target_day.isoformat()) and t is not None
    ]
    if not temps_du_jour:
        raise RuntimeError(
            f"Aucune donnee horaire pour {target_day} dans la reponse du run {run_iso} "
            f"(l'horizon du run {run_hour}z n'atteint peut-etre pas ce jour, ou l'API a change)."
        )

    return {
        "date": target_day.isoformat(),
        "tx": round(max(temps_du_jour), 1),
        "tn": round(min(temps_du_jour), 1),
    }


def fetch_infoclimat_obs_batch(codes, day):
    if not INFOCLIMAT_API_KEY or not codes:
        return {}

    params = [
        ("version", "2"),
        ("method", "get"),
        ("format", "json"),
        ("start", (day - timedelta(days=1)).isoformat()),
        ("end", day.isoformat()),
        ("token", INFOCLIMAT_API_KEY),
    ]
    for code in codes:
        params.append(("stations[]", code))

    url = "https://www.infoclimat.fr/opendata/?" + urlencode(params)

    try:
        r = requests.get(url, timeout=30)
        if not r.ok:
            print(f"  [!] Infoclimat a renvoye une erreur {r.status_code} : {r.text[:500]}", file=sys.stderr)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"  [!] Echec recuperation Infoclimat: {e}", file=sys.stderr)
        return {}

    if payload.get("status") != "OK":
        print(f"  [!] Infoclimat a renvoye une erreur: {payload.get('errors')}", file=sys.stderr)

    return extract_tn_tx_per_station(payload, codes, day)


def extract_tn_tx_per_station(payload, codes, target_day):
    paris_tz = ZoneInfo("Europe/Paris")
    hourly = payload.get("hourly", {})
    result = {}

    for code in codes:
        records = hourly.get(code) or []
        temps = []
        for rec in records:
            raw_temp = rec.get("temperature")
            raw_dh = rec.get("dh_utc")
            if raw_temp is None or raw_dh is None:
                continue
            try:
                dh_utc = datetime.strptime(raw_dh, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
                if dh_utc.astimezone(paris_tz).date() != target_day:
                    continue
                temps.append(float(raw_temp))
            except (ValueError, TypeError):
                continue
        if temps:
            result[code] = {"tn": round(min(temps), 1), "tx": round(max(temps), 1)}

    return result


def update_bias(bias_store, station_id, obs, fcst_for_that_day):
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

    stations_ok = [s for s in config["stations"] if s.get("lat") is not None and s.get("lon") is not None]
    stations_incomplete = [s["id"] for s in config["stations"] if s not in stations_ok]
    if stations_incomplete:
        print(
            f"[!] {len(stations_incomplete)} station(s) sans coordonnees, ignorees : "
            f"{', '.join(stations_incomplete)} -- lance scripts/fetch_stations_metadata.py",
            file=sys.stderr,
        )

    codes = [s["infoclimat_code"] for s in stations_ok]
    obs_today_par_code = fetch_infoclimat_obs_batch(codes, today)

    latest = {"generated_at": today.isoformat(), "zone": config.get("zone"), "stations": []}
    history_rows = []

    for st in stations_ok:
        sid = st["id"]
        code = st["infoclimat_code"]
        print(f"-> {st['nom']}")

        try:
            fcst_tomorrow = fetch_icon_ch1_forecast(st["lat"], st["lon"], today)
        except Exception as e:
            print(f"  [!] Prevision impossible pour {st['nom']}: {e}", file=sys.stderr)
            continue

        prev_fcst_for_today = None
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row["station_id"] == sid and row["date_prevue"] == today.isoformat():
                        prev_fcst_for_today = {
                            "tn": float(row["prevision_brute_tn"]),
                            "tx": float(row["prevision_brute_tx"]),
                        }

        obs = obs_today_par_code.get(code)
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
