"""Ingestion des prix alimentaires WFP (HDX) vers DuckDB.

Deux modes :
  - téléchargement automatique depuis l'API CKAN de HDX (GitHub Actions) ;
  - fichiers déjà présents dans data/raw/ (wfp_food_prices_<iso3>.csv).

Les CSV HDX ont une 2e ligne de tags HXL (#date, #adm1+name...) qu'on retire.
Le schéma brut est conservé tel quel dans raw.wfp_prices ; tout le nettoyage
est fait ensuite dans dbt (staging).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import urllib.request
from datetime import datetime, timezone

import duckdb
import pandas as pd

from ingestion.config import COUNTRIES, HDX_API, RAW_DIR, WAREHOUSE

log = logging.getLogger("ingest")

EXPECTED = [
    "date", "admin1", "admin2", "market", "market_id", "latitude", "longitude",
    "category", "commodity", "commodity_id", "unit", "priceflag", "pricetype",
    "currency", "price", "usdprice",
]


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "observatoire-prix/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download_country(iso3: str) -> bool:
    """Télécharge le CSV d'un pays depuis HDX. Retourne False en cas d'échec."""
    slug, _ = COUNTRIES[iso3]
    try:
        meta = json.loads(_http_get(HDX_API.format(slug=slug)))
        resources = meta["result"]["resources"]
        target = f"wfp_food_prices_{iso3.lower()}.csv"
        url = next(
            r["url"] for r in resources
            if r.get("name", "").lower() == target or r["url"].lower().endswith(target)
        )
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / target).write_bytes(_http_get(url, timeout=180))
        log.info("Téléchargé %s", target)
        return True
    except Exception as exc:  # réseau, ressource renommée...
        log.warning("Échec téléchargement %s : %s", iso3, exc)
        return False


def read_hdx_csv(content: bytes | str, iso3: str) -> pd.DataFrame:
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
    # Retire la ligne de tags HXL si présente
    if len(df) and str(df.iloc[0, 0]).startswith("#"):
        df = df.iloc[1:]
    df.columns = [c.strip().lower() for c in df.columns]
    for col in EXPECTED:  # certaines versions n'ont pas market_id / commodity_id
        if col not in df.columns:
            df[col] = ""
    df = df[EXPECTED].copy()
    df.insert(0, "country_iso3", iso3)
    return df


def load(download: bool = False) -> int:
    frames = []
    for iso3 in COUNTRIES:
        if download:
            download_country(iso3)
        path = RAW_DIR / f"wfp_food_prices_{iso3.lower()}.csv"
        if path.exists():
            df = read_hdx_csv(path.read_bytes(), iso3)
            log.info("%s : %d lignes", iso3, len(df))
            frames.append(df)
        else:
            log.info("%s : aucun fichier, ignoré", iso3)
    if not frames:
        raise SystemExit(f"Aucun CSV trouvé dans {RAW_DIR}")

    raw = pd.concat(frames, ignore_index=True)
    raw["_loaded_at"] = datetime.now(timezone.utc).isoformat()

    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.register("raw_df", raw)
    con.execute("CREATE OR REPLACE TABLE raw.wfp_prices AS SELECT * FROM raw_df")
    countries = pd.DataFrame(
        [(k, v[1]) for k, v in COUNTRIES.items()], columns=["country_iso3", "country_name"]
    )
    con.register("c_df", countries)
    con.execute("CREATE OR REPLACE TABLE raw.countries AS SELECT * FROM c_df")
    n = con.execute("SELECT count(*) FROM raw.wfp_prices").fetchone()[0]
    con.close()
    log.info("raw.wfp_prices : %d lignes chargées", n)
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--download", action="store_true", help="Télécharger depuis HDX")
    load(p.parse_args().download)
