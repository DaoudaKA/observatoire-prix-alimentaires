-- Prix mensuels bruts (avant contrôle des valeurs aberrantes). Grain : marché × produit × unité × type de prix × devise × mois
select
    md5(concat_ws('|', s.country_iso3, coalesce(s.admin1, ''), coalesce(s.admin2, ''), s.market)) as market_key,
    md5(s.commodity)                     as commodity_key,
    s.country_iso3,
    s.month_date,
    s.unit,
    s.price_type,
    s.currency,
    avg(s.price_per_unit)                as price,
    avg(s.usd_price_per_unit)            as usd_price,
    count(*)                             as n_obs
from {{ ref('stg_wfp_prices') }} s
group by all
