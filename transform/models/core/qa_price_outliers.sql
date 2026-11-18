-- Traçabilité : relevés écartés par le contrôle des valeurs aberrantes
select f.country_iso3, m.market, c.commodity_fr, f.unit, f.month_date,
       round(f.price, 2) as price, round(f.rolling_median, 2) as rolling_median,
       round(f.ratio_to_median, 2) as ratio_to_median
from {{ ref('int_prices_flagged') }} f
join {{ ref('dim_market') }} m using (market_key)
join {{ ref('dim_commodity') }} c using (commodity_key)
where f.is_outlier
