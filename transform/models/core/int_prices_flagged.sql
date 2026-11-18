-- Contrôle des valeurs aberrantes à deux niveaux :
-- 1. relevé isolé : écart > ×1,8 (ou < ×0,55) à la médiane mobile centrée 7 mois de sa série ;
-- 2. mois-pays entier : si la médiane de ces ratios sur toutes les séries d'un pays dépasse ×1,4
--    (ou passe sous ×0,7), le mois est une erreur systémique de la source (unités, saisie) :
--    tous ses relevés sont écartés. Un vrai choc de prix dure plusieurs mois et ne déclenche pas
--    ce contrôle, car la médiane centrée le suit.
with w as (
    select
        *,
        median(price) over win  as rolling_median,
        count(*)      over win  as n_window
    from {{ ref('int_prices_monthly') }}
    window win as (
        partition by market_key, commodity_key, unit, price_type, currency
        order by month_date
        range between interval 3 month preceding and interval 3 month following
    )
),
r as (
    select *, price / rolling_median as ratio_to_median from w
),
country_month as (
    select country_iso3, month_date, median(ratio_to_median) as cm_ratio, count(*) as n
    from r where n_window >= 4
    group by 1, 2
)
select
    r.*,
    coalesce(cm.cm_ratio, 1)                                                   as country_month_ratio,
    (r.n_window >= 4 and (r.ratio_to_median > 1.8 or r.ratio_to_median < 0.55))
      or (cm.n >= 10 and (cm.cm_ratio > 1.4 or cm.cm_ratio < 0.7))             as is_outlier
from r
left join country_month cm using (country_iso3, month_date)
