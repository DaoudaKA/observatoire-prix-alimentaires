"""Export des marts vers le site web.

* web/data/*.json            : données compactes pour le dashboard statique
* web/data/observatoire.duckdb : base légère interrogée par l'agent IA
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime

import duckdb

from ingestion.config import WAREHOUSE, WEB_DATA_DIR

log = logging.getLogger("export")
SINCE = "2015-01-01"
MARKET_SINCE = "2019-01-01"

AGENT_TABLES = {
    "dim_country": "core.dim_country",
    "dim_market": "core.dim_market",
    "dim_commodity": "core.dim_commodity",
    "dim_date": "core.dim_date",
    "prix_marche_mensuel": """
        select f.country_iso3, m.region, m.departement, m.market, c.commodity, c.commodity_fr,
               c.category_fr, f.unit, f.price_type, f.currency, f.month_date,
               round(f.price, 2) as price, round(f.usd_price, 4) as usd_price
        from core.fct_prices f
        join core.dim_market m using (market_key)
        join core.dim_commodity c using (commodity_key)""",
    "prix_national_mensuel": "select * exclude (commodity_key) from marts.mart_national_monthly",
    "alertes_prix": "select * exclude (market_key, commodity_key) from marts.mart_price_alerts",
    "inflation_alimentaire": "select * from marts.mart_food_inflation",
    "comparaison_pays": "select * from marts.mart_country_comparison",
    "previsions_prix": "select * exclude (commodity_key) from marts.forecast_prices",
}


def _clean(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    return v


def _records(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [{c: _clean(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def _dump(name: str, obj) -> None:
    path = WEB_DATA_DIR / name
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    log.info("%s : %.0f Ko", name, path.stat().st_size / 1024)


def export_json(con) -> None:
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    meta = con.execute("select max(month_date), min(month_date) from core.fct_prices").fetchone()
    _dump("meta.json", {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "last_month": _clean(meta[0]), "first_month": _clean(meta[1]),
        "source": "WFP Food Prices via HDX (Humanitarian Data Exchange)",
    })
    _dump("countries.json", _records(con, "select * from core.dim_country order by country_iso3 = 'SEN' desc, country_name"))

    # Séries nationales de détail, format colonnaire par série
    rows = _records(con, f"""
        select country_iso3 c, commodity_key k, commodity_fr n, category_fr g, unit u, currency cur,
               month_date d, round(price, 2) p, round(usd_price, 4) usd, yoy_pct y, n_markets nm
        from marts.mart_national_monthly
        where price_type = 'Retail' and month_date >= '{SINCE}'
        order by c, n, u, cur, d""")
    series: dict[str, dict] = {}
    for r in rows:
        sid = f"{r['c']}|{r['k'][:10]}|{r['u']}|{r['cur']}"
        s = series.setdefault(sid, {"id": sid, "country": r["c"], "commodity": r["n"], "category": r["g"],
                                    "unit": r["u"], "currency": r["cur"], "d": [], "p": [], "usd": [], "y": [], "nm": []})
        for f in ("d", "p", "usd", "y", "nm"):
            s[f].append(r[f])
    _dump("national.json", list(series.values()))

    _dump("inflation.json", _records(con, f"""
        select country_iso3, month_date, food_inflation_yoy_pct, n_series
        from marts.mart_food_inflation where month_date >= '{SINCE}' order by 1, 2"""))

    _dump("comparison.json", _records(con, """
        select country_iso3, country_name, commodity_fr, commodity_base, unit, currency,
               avg_usd_price_12m, avg_local_price_12m, avg_yoy_pct_12m, last_month
        from marts.mart_country_comparison"""))

    # Dernière alerte de chaque marché × produit (dernier mois du pays)
    _dump("alerts.json", _records(con, """
        with last as (select country_iso3, max(month_date) m from marts.mart_price_alerts group by 1)
        select a.country_iso3, a.region, a.market, a.latitude, a.longitude, a.commodity_fr, a.category_fr,
               a.unit, a.currency, a.month_date, a.price, a.expected_price, a.deviation_pct,
               a.alert_score, a.alert_level
        from marts.mart_price_alerts a join last l on a.country_iso3 = l.country_iso3 and a.month_date = l.m
        where a.price_type = 'Retail'
        order by a.alert_score desc"""))

    _dump("forecast.json", _records(con, """
        select country_iso3, commodity_fr, unit, currency, month_date, horizon,
               round(forecast, 2) forecast, round(lower_80, 2) lower_80, round(upper_80, 2) upper_80,
               backtest_mape_pct
        from marts.forecast_prices order by 1, 2, 3, 4, 6"""))

    # Séries par marché, un fichier par pays (chargé à la demande)
    for (iso,) in con.execute("select country_iso3 from core.dim_country").fetchall():
        mrows = _records(con, f"""
            select m.market mk, m.region r, c.commodity_fr n, f.unit u, f.month_date d, round(f.price, 2) p
            from core.fct_prices f join core.dim_market m using (market_key)
            join core.dim_commodity c using (commodity_key)
            where f.country_iso3 = '{iso}' and f.price_type = 'Retail' and f.month_date >= '{MARKET_SINCE}'
            order by mk, n, u, d""")
        out: dict[str, dict] = {}
        for r in mrows:
            sid = f"{r['mk']}|{r['n']}|{r['u']}"
            s = out.setdefault(sid, {"market": r["mk"], "region": r["r"], "commodity": r["n"], "unit": r["u"], "d": [], "p": []})
            s["d"].append(r["d"]); s["p"].append(r["p"])
        _dump(f"markets_{iso}.json", list(out.values()))


def export_agent_db(con) -> None:
    path = WEB_DATA_DIR / "observatoire.duckdb"
    if path.exists():
        path.unlink()
    con.execute(f"ATTACH '{path}' AS agentdb")
    for name, sql in AGENT_TABLES.items():
        src = sql if " " in sql.strip() else f"select * from {sql}"
        con.execute(f"CREATE TABLE agentdb.main.{name} AS {src}")
    con.execute("DETACH agentdb")
    log.info("observatoire.duckdb : %.1f Mo", path.stat().st_size / 1e6)


def run() -> None:
    con = duckdb.connect(str(WAREHOUSE))
    export_json(con)
    export_agent_db(con)
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
