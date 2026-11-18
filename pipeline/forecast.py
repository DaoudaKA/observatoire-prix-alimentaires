"""Prévision des prix nationaux à 3 mois (Holt-Winters amorti, saisonnalité 12 mois).

Pour chaque série nationale (pays × produit × unité, prix de détail) assez longue :
  * entraînement sur les 72 derniers mois au plus ;
  * backtest : on refait le modèle sans les 6 derniers mois et on mesure le MAPE ;
  * intervalle à 80 % tiré de l'écart-type des résidus.
Résultat : table marts.forecast_prices.
"""
from __future__ import annotations

import logging
import warnings

import duckdb
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from ingestion.config import WAREHOUSE

log = logging.getLogger("forecast")
HORIZON = 3
MIN_MONTHS = 36
Z80 = 1.2816


def _fit(y: pd.Series):
    seasonal = "mul" if len(y) >= 24 and (y > 0).all() else None
    model = ExponentialSmoothing(
        y, trend="add", damped_trend=True, seasonal=seasonal,
        seasonal_periods=12 if seasonal else None, initialization_method="estimated",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return model.fit(optimized=True)


def forecast_series(y: pd.Series) -> tuple[pd.DataFrame, float] | None:
    y = y.asfreq("MS").interpolate(limit=2)
    y = y.dropna()
    y = y[y.index >= y.index.max() - pd.DateOffset(months=71)]
    if len(y) < MIN_MONTHS or y.index.to_series().diff().dt.days.max() > 62:
        return None
    # backtest
    train, test = y.iloc[:-6], y.iloc[-6:]
    bt = _fit(train).forecast(6)
    mape = float(np.mean(np.abs((test.values - bt.values) / test.values)) * 100)
    fit = _fit(y)
    fc = fit.forecast(HORIZON)
    sigma = float(np.std(y.values - fit.fittedvalues.values))
    h = np.arange(1, HORIZON + 1)
    out = pd.DataFrame({
        "month_date": fc.index.date,
        "horizon": h,
        "forecast": fc.values,
        "lower_80": np.maximum(fc.values - Z80 * sigma * np.sqrt(h), 0),
        "upper_80": fc.values + Z80 * sigma * np.sqrt(h),
    })
    return out, mape


def run() -> int:
    con = duckdb.connect(str(WAREHOUSE))
    df = con.execute("""
        with last as (select country_iso3, max(month_date) m from marts.mart_national_monthly group by 1)
        select n.country_iso3, n.commodity_key, n.commodity_fr, n.unit, n.currency, n.month_date, n.price
        from marts.mart_national_monthly n join last l using (country_iso3)
        where n.price_type = 'Retail'
          and n.commodity_key in (
              select commodity_key from marts.mart_national_monthly x
              where x.country_iso3 = n.country_iso3 and x.price_type = 'Retail'
                and x.month_date >= l.m - interval 3 month)
        order by 1, 2, 4, 5, 6
    """).df()
    rows = []
    keys = ["country_iso3", "commodity_key", "commodity_fr", "unit", "currency"]
    for key, g in df.groupby(keys):
        y = pd.Series(g["price"].values, index=pd.to_datetime(g["month_date"]))
        try:
            res = forecast_series(y)
        except Exception as exc:  # séries dégénérées
            log.debug("échec %s : %s", key, exc)
            continue
        if res is None:
            continue
        out, mape = res
        for k, v in zip(keys, key):
            out[k] = v
        out["backtest_mape_pct"] = round(mape, 2)
        rows.append(out)
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=keys + ["month_date", "horizon", "forecast", "lower_80", "upper_80", "backtest_mape_pct"])
    con.register("fc", result)
    con.execute("CREATE OR REPLACE TABLE marts.forecast_prices AS SELECT * FROM fc")
    con.close()
    log.info("%d séries prévues", result.groupby(keys).ngroups if len(result) else 0)
    return len(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
