# Météo Gard rhodanien — Tn/Tx corrigées

Carte de prévision (Tn/Tx du lendemain) pour le Gard rhodanien, basée sur
**ICON‑CH1** (MétéoSuisse, via l'API [Open‑Meteo](https://open-meteo.com), gratuite
et sans clé), et **corrigée peu à peu** grâce aux observations réelles archivées
depuis les stations [Infoclimat](https://www.infoclimat.fr/opendata) de la région.

## Comment ça marche

```
chaque jour (GitHub Actions)
  ├─ 1. prévision brute ICON-CH1 pour demain (Open-Meteo)
  ├─ 2. observation réelle d'hier (Infoclimat) pour vérifier la prévision faite hier
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

## Mise en route

### 1. Créer le dépôt et activer GitHub Pages
- Pousse ce dossier sur un nouveau dépôt GitHub.
- Dans **Settings → Pages**, choisis la branche `main` et le dossier racine `/`.

### 2. Obtenir une clé Infoclimat
- Crée un compte sur [infoclimat.fr/opendata](https://www.infoclimat.fr/opendata).
- Sélectionne la zone géographique du Gard rhodanien (bbox donnée dans
  `stations.json`) et le type d'usage "non-commercial" (site personnel).
- Génère une clé API. Infoclimat affiche alors un exemple de requête tout
  prêt pour ta sélection : **copie l'URL et les paramètres exacts qu'il te
  donne** dans `scripts/update_forecast.py` (fonction `fetch_infoclimat_obs`),
  car le format précis peut différer légèrement de ce qui est ébauché ici.
- Relève au passage les identifiants des stations qui t'intéressent et
  remplace les `"A_REMPLIR"` dans `stations.json`.

### 3. Ajouter la clé comme secret GitHub
- **Settings → Secrets and variables → Actions → New repository secret**
- Nom : `INFOCLIMAT_API_KEY`, valeur : ta clé.

### 4. Lancer une première fois
- Onglet **Actions** → workflow "Mise à jour prévisions Gard rhodanien" →
  **Run workflow** (bouton manuel), pour vérifier que tout fonctionne avant
  d'attendre le lendemain matin.

## Limites à connaître

- ICON‑CH1 a un horizon de prévision de 33h : la Tx/Tn "de demain" est
  toujours disponible, mais pas au-delà.
- Le format exact de l'API Infoclimat (endpoint, structure JSON retournée)
  n'a volontairement pas été figé en dur : vérifie-le avec l'exemple de
  requête que le site te génère pour ta propre clé, et ajuste
  `fetch_infoclimat_obs()` en conséquence.
- La correction actuelle est un simple biais additif par station (moyenne
  mobile exponentielle). Une fois `data/history.csv` suffisamment fourni
  (quelques mois), il devient possible d'affiner : biais saisonnier,
  régression sur plusieurs variables, etc.
