select
    c.country_iso3,
    c.country_name,
    count(distinct s.market)            as n_markets,
    min(s.month_date)                   as first_month,
    max(s.month_date)                   as last_month
from {{ source('raw', 'countries') }} c
join {{ ref('stg_wfp_prices') }} s using (country_iso3)
group by 1, 2
