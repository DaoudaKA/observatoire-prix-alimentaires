select
    md5(concat_ws('|', country_iso3, coalesce(admin1, ''), coalesce(admin2, ''), market)) as market_key,
    country_iso3,
    admin1                                  as region,
    admin2                                  as departement,
    market,
    avg(latitude)                           as latitude,
    avg(longitude)                          as longitude,
    min(month_date)                         as first_month,
    max(month_date)                         as last_month,
    count(distinct commodity)               as n_commodities
from {{ ref('stg_wfp_prices') }}
group by country_iso3, admin1, admin2, market
