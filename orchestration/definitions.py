"""Orchestration Dagster : ingestion -> dbt -> prévisions -> export web.

Lancer l'interface :  dagster dev -m orchestration.definitions
Matérialiser tout  :  dagster asset materialize -m orchestration.definitions --select '*'
"""
import os
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    AssetKey,
    Definitions,
    MaterializeResult,
    MetadataValue,
    ScheduleDefinition,
    asset,
    define_asset_job,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets

from ingestion import ingest
from pipeline import export, forecast

ROOT = Path(__file__).resolve().parent.parent
dbt_project = DbtProject(project_dir=ROOT / "transform", profiles_dir=ROOT / "transform")
dbt_project.prepare_if_dev()


@asset(
    key=AssetKey(["raw", "wfp_prices"]),
    group_name="ingestion",
    description="Prix WFP (HDX) de 9 pays d'Afrique de l'Ouest chargés dans DuckDB.",
)
def wfp_prices_raw(context: AssetExecutionContext) -> MaterializeResult:
    download = os.environ.get("HDX_DOWNLOAD", "1") == "1"
    n = ingest.load(download=download)
    return MaterializeResult(metadata={"lignes": n, "telechargement_hdx": download})


@asset(key=AssetKey(["raw", "countries"]), group_name="ingestion", deps=[wfp_prices_raw],
       description="Référentiel des pays (créé par l'ingestion).")
def countries_raw() -> None:
    return None


@dbt_assets(manifest=dbt_project.manifest_path)
def dbt_models(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build"], context=context).stream()


@asset(
    group_name="analytics",
    deps=[AssetKey(["marts", "mart_national_monthly"])],
    description="Prévisions Holt-Winters à 3 mois avec backtest (MAPE).",
)
def forecast_prices() -> MaterializeResult:
    n = forecast.run()
    return MaterializeResult(metadata={"lignes": n})


@asset(
    group_name="web",
    deps=[forecast_prices, AssetKey(["marts", "mart_price_alerts"]),
          AssetKey(["marts", "mart_food_inflation"]), AssetKey(["marts", "mart_country_comparison"])],
    description="JSON du dashboard + base DuckDB de l'agent IA dans web/data.",
)
def web_exports() -> MaterializeResult:
    export.run()
    files = sorted(p.name for p in export.WEB_DATA_DIR.glob("*"))
    return MaterializeResult(metadata={"fichiers": MetadataValue.json(files)})


full_refresh = define_asset_job("rafraichissement_complet", selection="*")

defs = Definitions(
    assets=[wfp_prices_raw, countries_raw, dbt_models, forecast_prices, web_exports],
    jobs=[full_refresh],
    # Le WFP publie mensuellement : le 20 de chaque mois à 6h UTC
    schedules=[ScheduleDefinition(job=full_refresh, cron_schedule="0 6 20 * *")],
    resources={"dbt": DbtCliResource(project_dir=dbt_project)},
)
