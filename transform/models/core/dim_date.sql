-- Calendrier mensuel couvrant toute la période observée
with bounds as (
    select min(month_date) as d0, max(month_date) as d1 from {{ ref('stg_wfp_prices') }}
)
select
    m::date                                         as month_date,
    year(m)                                         as year,
    month(m)                                        as month,
    quarter(m)                                      as quarter,
    strftime(m, '%Y-%m')                            as year_month,
    case when month(m) between 7 and 10 then true else false end
                                                    as is_lean_season   -- soudure au Sahel
from bounds, generate_series(d0, d1, interval 1 month) as t(m)
