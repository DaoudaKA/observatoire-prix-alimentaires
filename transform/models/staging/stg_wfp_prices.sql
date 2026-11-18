-- Nettoyage et typage des relevés WFP.
-- * prix ramenés à l'unité de base ("50 KG" -> prix par KG)
-- * séparation produit de base / variété ("Rice (imported)" -> Rice + imported)
-- * exclusion des prévisions WFP et des prix non positifs
with src as (
    select * from {{ source('raw', 'wfp_prices') }}
),

typed as (
    select
        country_iso3,
        try_cast(date as date)                                   as price_date,
        nullif(trim(admin1), '')                                 as admin1,
        nullif(trim(admin2), '')                                 as admin2,
        trim(market)                                             as market,
        try_cast(nullif(latitude, '') as double)                 as latitude,
        try_cast(nullif(longitude, '') as double)                as longitude,
        lower(trim(category))                                    as category,
        trim(commodity)                                          as commodity,
        upper(trim(unit))                                        as unit_raw,
        lower(trim(priceflag))                                   as price_flag,
        trim(pricetype)                                          as price_type,
        upper(trim(currency))                                    as currency,
        try_cast(nullif(price, '') as double)                    as price,
        try_cast(nullif(usdprice, '') as double)                 as usd_price
    from src
),

parsed as (
    select
        *,
        coalesce(try_cast(nullif(regexp_extract(unit_raw, '^([0-9]+(\.[0-9]+)?)\s+', 1), '') as double), 1)
                                                                 as unit_qty,
        trim(regexp_replace(unit_raw, '^[0-9]+(\.[0-9]+)?\s+', ''))
                                                                 as unit,
        trim(regexp_replace(commodity, '\s*\(.*\)\s*$', ''))     as commodity_base,
        nullif(trim(regexp_extract(commodity, '\((.*)\)', 1)), '')
                                                                 as variety
    from typed
)

select
    country_iso3,
    price_date,
    date_trunc('month', price_date)::date                        as month_date,
    admin1,
    admin2,
    market,
    latitude,
    longitude,
    category,
    commodity,
    commodity_base,
    variety,
    unit_raw,
    unit,
    unit_qty,
    price_flag,
    price_type,
    currency,
    price,
    usd_price,
    price / unit_qty                                             as price_per_unit,
    usd_price / unit_qty                                         as usd_price_per_unit
from parsed
where price_date is not null
  and price > 0
  and coalesce(price_flag, '') <> 'forecast'
  and category <> 'non-food'
