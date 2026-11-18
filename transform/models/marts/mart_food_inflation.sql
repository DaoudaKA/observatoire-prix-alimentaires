-- Inflation alimentaire approchée par pays : médiane des variations annuelles
-- des produits suivis (prix de détail, monnaie locale).
select
    country_iso3,
    month_date,
    round(median(yoy_pct), 2)            as food_inflation_yoy_pct,
    round(avg(yoy_pct), 2)               as food_inflation_yoy_mean_pct,
    count(*)                             as n_series
from {{ ref('mart_national_monthly') }}
where price_type = 'Retail'
  and yoy_pct is not null
group by 1, 2
having count(*) >= 3
