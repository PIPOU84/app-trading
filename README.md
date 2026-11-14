# App Trading Swing

Application d'aide à la décision pour le swing trading et le position trading (pas de day trading) :
actions US et européennes, forex, matières premières et crypto. Données 100 % gratuites (Yahoo Finance, FRED).

> Outil d'aide à la décision, pas un conseil en investissement. Le trading comporte un risque de perte en capital.
> L'application ne passe aucun ordre.

## Lancer l'application (le plus simple)

- **Sur le PC** : double-clic sur `Lancer.bat`. Le navigateur s'ouvre sur http://127.0.0.1:8000.
- **Sur le téléphone** : double-clic sur `Lancer-telephone.bat`, puis ouvrir sur le téléphone (même Wi-Fi)
  l'adresse affichée, et menu du navigateur > « Ajouter à l'écran d'accueil ».
  Le PC doit rester allumé avec la fenêtre ouverte.

Fermer la fenêtre noire arrête l'application.

## Écrans

- **Recommandations** : contexte macro, trades à considérer (score ≥ 60), setups plus fragiles,
  produits « à surveiller » (setup en approche), leaders et retardataires par marché, résultats d'entreprises à venir.
- **Marchés** : ~120 produits (actions US, CAC 40, Europe, ETF, forex, métaux, énergie, agricoles, crypto),
  filtres par catégorie, favoris, et **recherche de n'importe quel produit Yahoo Finance** à ajouter au suivi.
- **Fiche produit** : graphique, plan de trade, taille de position, tendances, zones, macro, actualités, favori ☆.
- **Réglages** : capital, devise, risque par trade.

Les favoris ont leurs données H4 mises à jour chaque soir ; les autres produits les téléchargent à l'ouverture de leur fiche.

## Démarrer le back-end à la main (Windows, PowerShell)

```powershell
cd Documents\app-trading
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

Puis ouvrir http://127.0.0.1:8000/docs (documentation interactive de l'API).

1. `POST /api/refresh` : télécharge les données (environ 1 minute) puis lance le scan.
2. `GET /api/signals` : fiches de trade classées par score de confluence.
3. `GET /api/analysis/{symbole}` : analyse complète d'un actif (tendances, zones, macro, signaux, setups rejetés).
4. `POST /api/size` : taille de position pour une entrée et un stop.

Un scan automatique tourne chaque soir à 23:00 (heure de Paris) tant que le serveur est lancé.

## Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

## Organisation

| Dossier | Rôle |
|---|---|
| `backend/app/providers` | Sources de données (Yahoo, FRED) |
| `backend/app/services` | Téléchargement, stockage, orchestration de l'analyse |
| `backend/app/analysis` | Indicateurs, supports/résistances, tendance, macro |
| `backend/app/signals` | Détection des setups et fiches de trade |
| `backend/app/risk` | Taille de position |
| `backend/app/config.py` | Tous les réglages (règles de stop, R:R minimum, heure du scan…) |

## Règles du moteur (modifiables dans `config.py`)

- **Setups** : pullback dans la tendance, cassure + retest, retournement sur divergence RSI (achat et vente).
- **Stop** : derrière le dernier creux/sommet avec 0,5 ATR de marge, et au moins à 1,5 ATR de l'entrée. Rejet si plus de 4 ATR.
- **Objectifs** : TP1 juste avant la prochaine zone (sinon 2R), puis TP2, TP3. Rejet si TP1 < 2R.
- **Score /100** : tendance hebdo 30, setup 30, R:R 15, macro 15, momentum 10.
