# Météo Gard rhodanien — Tn/Tx corrigées

Carte de prévision (Tn/Tx du lendemain) pour le Gard rhodanien et ses marges
(Ardèche, Vaucluse, Drôme), basée sur **ICON‑CH1** (MétéoSuisse, run 12z fixe,
via l'API [Open‑Meteo](https://open-meteo.com)), et **corrigée peu à peu**
grâce aux observations réelles archivées depuis 17 stations
[Infoclimat](https://www.infoclimat.fr/opendata) (réseau StatIC) de la région.

> **Note importante** : les stations officielles Météo-France affichées sur
> le site infoclimat.fr (Nîmes-Courbessac, Avignon, Orange-Caritat, Pujaut,
> Saint-Montan, Salindres, Méjannes-le-Clap, etc.) ne sont **pas**
> interrogeables via l'API `stations[]` — testé et confirmé. Seules les
> stations du réseau amateur StatIC (codes `000XXX` / `STATICxxxx` /
> `000XX`) répondent. `stations.json` ne liste donc que celles-là.

## Comment ça marche

```
une fois, à l'installation
  └─ scripts/fetch_stations_metadata.py : un seul appel Infoclimat pour
     récupérer lat/lon/altitude des 29 stations -> stations.json complété

chaque jour (GitHub Actions, ~14h30 UTC)
  ├─ 1. prévision brute ICON-CH1 pour demain, run 12z fixe (Open-Meteo)
  ├─ 2. observation réelle d'aujourd'hui (Infoclimat, un seul appel groupé)
  │     pour vérifier la prévision faite hier
  ├─ 3. mise à jour du biais par station (moyenne mobile exponentielle)
  ├─ 4. prévision corrigée = prévision brute + biais appris
  └─ 5. écriture de data/latest.json + archivage dans data/history.csv
                         │
                         ▼
              index.html (carte Leaflet, statique)
```

Le biais se réajuste tout seul, jour après jour : si le modèle a tendance à
prévoir 1°C de trop sur les Tx à Bagnols-sur-Cèze en été, la correction va
progressivement le compenser. `data/history.csv` est l'archive complète
(prévision brute, prévision corrigée, observation) : elle sert à la fois de
journal et de matière pour affiner la méthode de correction plus tard
(régression, un biais différent été/hiver, etc.).

Le run ICON‑CH1 utilisé est fixé (12z par défaut, réglable via
`RUN_HOUR_UTC` dans `scripts/update_forecast.py`) plutôt que "le dernier run
disponible", pour que la prévision soit comparable d'un jour à l'autre —
important pour que la correction de biais ait un sens.

## Mise en route

### 1. Créer le dépôt et activer GitHub Pages
- Pousse ce dossier sur un nouveau dépôt GitHub.
- Dans **Settings → Pages**, choisis la branche `main` et le dossier racine `/`.

### 2. Obtenir une clé Infoclimat
- Crée un compte sur [infoclimat.fr/opendata](https://www.infoclimat.fr/opendata).
- Génère une clé API (usage non‑commercial : site personnel).

### 3. Compléter automatiquement les coordonnées des stations
```bash
export INFOCLIMAT_API_KEY="ta_cle"
python scripts/fetch_stations_metadata.py
```
Ce script fait **un seul appel** avec les 17 codes de station à la fois et
remplit les `lat`/`lon`/`altitude` manquants dans `stations.json`. Vérifie le
résultat (`git diff stations.json`) avant de committer — si certaines
stations restent sans coordonnées, relance avec `DEBUG=1` pour voir la
réponse brute de l'API et ajuster `extract_one()` si sa structure diffère de
ce qui était prévu.

### 4. Ajouter la clé comme secret GitHub
- **Settings → Secrets and variables → Actions → New repository secret**
- Nom : `INFOCLIMAT_API_KEY`, valeur : ta clé.

### 5. Lancer une première fois
- Onglet **Actions** → workflow "Mise à jour prévisions Gard rhodanien" →
  **Run workflow** (bouton manuel), pour vérifier que tout fonctionne avant
  d'attendre le lendemain matin.

## Limites à connaître

- ICON‑CH1 a un horizon de prévision de 33h : la Tx/Tn "de demain" est
  toujours disponible depuis le run 12z, mais pas au-delà.
- La structure exacte du JSON renvoyé par l'API Infoclimat (`extract_one()`
  dans `fetch_stations_metadata.py`, `extract_tn_tx_per_station()` dans
  `update_forecast.py`) a été écrite sans compte actif pour la vérifier :
  elle essaie les formes les plus plausibles, mais un ajustement mineur est
  possible au premier lancement (`DEBUG=1` affiche la réponse brute).
- La correction actuelle est un simple biais additif par station (moyenne
  mobile exponentielle). Une fois `data/history.csv` suffisamment fourni
  (quelques mois), il devient possible d'affiner : biais saisonnier,
  régression sur plusieurs variables, etc.
- Certaines stations (StatIC amateurs) peuvent avoir des coupures de
  service ; le pipeline ignore silencieusement une observation manquante
  pour un jour donné (le biais n'est simplement pas mis à jour ce jour-là).

