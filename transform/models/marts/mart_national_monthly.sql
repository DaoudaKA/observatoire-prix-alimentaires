-- Prix national mensuel : médiane des marchés, variations mensuelle et annuelle
with base as (
    select
        f.country_iso3,
        f.commodity_key,
        f.unit,
        f.price_type,
        f.currency,
        f.month_date,
        median(f.price)                 as price,
        median(f.usd_price)             as usd_price,
        count(distinct f.market_key)    as n_markets
    from {{ ref('fct_prices') }} f
    group by all
)
select
    b.*,
    c.commodity,
    c.commodity_fr,
    c.commodity_base,
    c.category_fr,
    round(100 * (b.price / m1.price - 1), 2)   as mom_pct,
    round(100 * (b.price / y1.price - 1), 2)   as yoy_pct
from base b
join {{ ref('dim_commodity') }} c using (commodity_key)
left join base m1
  on m1.country_iso3 = b.country_iso3 and m1.commodity_key = b.commodity_key
 and m1.unit = b.unit and m1.price_type = b.price_type and m1.currency = b.currency
 and m1.month_date = b.month_date - interval 1 month
left join base y1
  on y1.country_iso3 = b.country_iso3 and y1.commodity_key = b.commodity_key
 and y1.unit = b.unit and y1.price_type = b.price_type and y1.currency = b.currency
 and y1.month_date = b.month_date - interval 12 month
