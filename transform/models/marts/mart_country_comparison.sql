-- Comparaison régionale : prix moyen en USD sur les 12 derniers mois disponibles
-- pour chaque pays, par produit de base et unité (détail).
with last_month as (
    select country_iso3, max(month_date) as last_month
    from {{ ref('mart_national_monthly') }}
    group by 1
),
recent as (
    select n.*
    from {{ ref('mart_national_monthly') }} n
    join last_month l using (country_iso3)
    where n.price_type = 'Retail'
      and n.month_date > l.last_month - interval 12 month
)
select
    r.country_iso3,
    d.country_name,
    r.commodity,
    r.commodity_fr,
    r.commodity_base,
    r.unit,
    round(avg(r.usd_price), 3)          as avg_usd_price_12m,
    round(avg(r.price), 1)              as avg_local_price_12m,
    any_value(r.currency)               as currency,
    round(avg(r.yoy_pct), 2)            as avg_yoy_pct_12m,
    max(r.month_date)                   as last_month
from recent r
join {{ ref('dim_country') }} d using (country_iso3)
group by all
