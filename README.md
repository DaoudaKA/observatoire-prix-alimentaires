# 🌾 Observatoire des prix alimentaires — Sénégal & Afrique de l'Ouest

> Où et quand les prix du riz, de l'oignon, du mil ou de l'huile flambent-ils ?
> Un projet BI complet, du pipeline de données à l'agent IA, construit sur les données ouvertes du
> Programme alimentaire mondial (WFP).

**Démo :** `https://<votre-projet>.vercel.app` · **Auteur :** Daouda Ka, M2 Informatique (BI), UCAD

---

## La problématique

La vie chère est l'une des premières préoccupations des ménages sénégalais. Les prix des denrées de base
varient fortement d'un marché à l'autre, d'une saison à l'autre (soudure, récolte d'oignon des Niayes) et
réagissent aux chocs mondiaux (2022). Les données existent (relevés de l'ANSD, du CSA et du WFP), mais
elles sont dispersées dans des fichiers bruts difficiles à exploiter.

**Pour qui ?**

| Public | Question à laquelle l'observatoire répond |
|---|---|
| Ménages, associations de consommateurs | Combien coûte le riz à Thiès ce mois-ci ? Est-ce normal ? |
| Producteurs et commerçants (Niayes) | Quand vendre l'oignon ? Quel marché paie le mieux ? |
| Journalistes, ONG | Quels marchés sont en situation de stress ou de crise ? |
| Décideurs publics | Comment évolue l'inflation alimentaire comparée aux voisins ? |

Le même pipeline couvre 9 pays (Sénégal, Mali, Mauritanie, Gambie, Guinée, Guinée-Bissau,
Burkina Faso, Côte d'Ivoire, Niger). Il suffit d'ajouter une ligne dans `ingestion/config.py`
pour suivre n'importe lequel des ~98 pays publiés par le WFP.

## Fonctionnalités

- **Évolution des prix** par produit, avec **prévision à 3 mois** (Holt-Winters, intervalle à 80 %, backtest).
- **Carte des alertes** : chaque marché coloré selon un score de flambée inspiré de l'**ALPS** du WFP
  (écart du prix à sa tendance saisonnière, standardisé : Normal / Stress / Alerte / Crise).
- **Prix par marché** et **comparaison régionale** en dollars US.
- **Inflation alimentaire comparée** entre pays.
- **Analyste IA** (Claude, Anthropic) : questions en langage naturel → requêtes SQL sur l'entrepôt →
  réponse chiffrée en français, avec graphique et SQL visibles.

## Architecture

```
 HDX (WFP Food Prices, CSV mensuels)
        │  ingestion/ingest.py  (Python, API CKAN)
        ▼
 DuckDB  raw.wfp_prices
        │  dbt (transform/)
        ▼
 staging ─► core (modèle en étoile) ─► marts
   stg_wfp_prices   dim_country          mart_national_monthly   (prix national, variations)
                    dim_market           mart_price_alerts       (score de flambée)
                    dim_commodity        mart_food_inflation     (inflation alimentaire)
                    dim_date             mart_country_comparison (comparaison en USD)
                    fct_prices
        │  pipeline/forecast.py (statsmodels)  ─► marts.forecast_prices
        │  pipeline/export.py
        ▼
 web/data/*.json  +  web/data/observatoire.duckdb
        │
        ▼
 Vercel : dashboard statique (ECharts, Leaflet)  +  /api/agent (Python, Claude + DuckDB lecture seule)

 Orchestration : Dagster (orchestration/definitions.py), planifié le 20 de chaque mois
 Automatisation : GitHub Actions (refresh.yml) → commit des données → redéploiement Vercel
 Qualité : 21 tests dbt (unicité, clés étrangères, valeurs acceptées, prix > 0) + tests pytest de l'agent
```

### L'agent IA

`web/api/agent.py` implémente une boucle d'agent avec l'API Claude (*tool use*) :

1. Le schéma de la base (tables, colonnes, pays, produits, régions) et des notes métier sont injectés dans le
   prompt système, avec mise en cache (*prompt caching*) pour réduire le coût.
2. L'agent appelle l'outil `run_sql` autant de fois que nécessaire (8 étapes au plus) : il vérifie les
   libellés, puis calcule.
3. Il peut appeler `show_chart` pour qu'un graphique s'affiche dans la conversation.
4. Sécurité : connexion DuckDB **en lecture seule**, accès aux fichiers et au réseau désactivé, une seule
   requête `SELECT`/`WITH`, mots-clés dangereux refusés, délai maximal de 10 s, 200 lignes au plus,
   limite de 20 questions par IP et par tranche de 10 minutes. La clé API ne quitte jamais le serveur.

## Démarrer en local

```bash
pip install -r requirements.txt

# 1. Données : soit téléchargement automatique depuis HDX…
python -m ingestion.ingest --download
#    …soit déposer les CSV HDX (wfp_food_prices_sen.csv, …) dans data/raw/ puis :
python -m ingestion.ingest

# 2. Transformation + tests
cd transform && dbt build --profiles-dir . && cd ..

# 3. Prévisions et export pour le web
python -m pipeline.forecast
python -m pipeline.export

# 4. Site + agent en local
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/dev_server.py        # http://localhost:8000
```

Avec Dagster, les étapes 1 à 3 deviennent :

```bash
export DAGSTER_HOME=$PWD/.dagster && mkdir -p $DAGSTER_HOME
(cd transform && dbt parse --profiles-dir .)
dagster dev -m orchestration.definitions          # interface sur http://localhost:3000
```

## Déployer

1. Pousser le dépôt sur GitHub.
2. Sur Vercel : *New Project* → importer le dépôt → **Root Directory : `web`** → *Deploy*.
3. Dans *Settings → Environment Variables* : `ANTHROPIC_API_KEY` (et, en option, `ANTHROPIC_MODEL`,
   `claude-sonnet-5-5` par défaut).
4. Dans GitHub, *Actions* → lancer **Rafraîchissement mensuel des données** une première fois.
   Le workflow tourne ensuite seul chaque mois et Vercel redéploie à chaque commit.

> 💡 Fixez une limite de dépense mensuelle dans la console Anthropic : l'agent est public.

## Méthodologie et limites

- **Prix** : prix de détail ramenés à l'unité de base (un relevé « 50 KG » est divisé par 50). Le prix
  national est la **médiane** des marchés, ce qui le rend robuste aux valeurs extrêmes.
- **Score de flambée** : pour chaque série marché × produit, tendance = moyenne des 12 mois précédents ;
  indice saisonnier = ratio moyen prix/tendance du même mois calendaire ; score = écart à la tendance
  désaisonnalisée, divisé par l'écart-type de la série (avec un plancher de 3 % pour ne pas sur-alerter les séries très stables). Seuils : < 0,25 normal ; 0,25-1 stress ;
  1-2 alerte ; ≥ 2 crise. C'est une adaptation simplifiée de l'ALPS, pas l'indicateur officiel du WFP.
- **Inflation alimentaire** : médiane des variations annuelles des produits suivis. Elle n'est pas pondérée
  par la consommation, donc ce n'est pas l'IPC de l'ANSD.
- **Prévisions** : modèle Holt-Winters amorti, saisonnalité 12 mois, entraîné sur 6 ans au plus. L'erreur
  (MAPE) mesurée sur les 6 derniers mois connus est affichée avec chaque prévision.
- **Couverture** : les marchés et produits suivis varient selon les pays et les années ; certaines séries
  ont des trous.

## Structure du dépôt

```
ingestion/        téléchargement HDX et chargement DuckDB
transform/        projet dbt (staging, core, marts, seeds de traduction, tests)
pipeline/         prévisions et export web
orchestration/    définitions Dagster (assets, job, planification)
web/              dashboard statique, fonction serverless de l'agent, données exportées
tests/            jeu de données factice (CI uniquement) et tests de l'agent
.github/workflows CI et rafraîchissement mensuel
```

## Sources

- WFP — *Food Prices*, Humanitarian Data Exchange : https://data.humdata.org/organization/wfp
- Sources nationales relayées par le WFP, dont l'ANSD et le CSA (Sénégal).
- Vérifiez la licence indiquée sur chaque page HDX et citez toujours le WFP comme source.

---

*Stack : Python · DuckDB · dbt · Dagster · GitHub Actions · statsmodels · ECharts · Leaflet · Vercel · Claude API*
