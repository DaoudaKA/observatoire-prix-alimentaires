-- Détection des flambées de prix, inspirée de l'indicateur ALPS du WFP
-- (Alert for Price Spikes) : écart du prix à sa tendance saisonnière,
-- standardisé par série. Seuils : <0.25 normal, 0.25-1 stress,
-- 1-2 alerte, >=2 crise. Écart-type plancher : 3 %.
with s as (
    select
        market_key, commodity_key, country_iso3, unit, price_type, currency,
        month_date, price,
        avg(price) over w12                              as trend_12m,
        count(*)   over w12                              as n_hist
    from {{ ref('fct_prices') }}
    window w12 as (
        partition by market_key, commodity_key, unit, price_type, currency
        order by month_date
        range between interval 12 month preceding and interval 1 month preceding
    )
),
ratios as (
    select *, price / trend_12m as ratio
    from s
    where n_hist >= 6
),
seasonal as (
    select *,
        avg(ratio) over (
            partition by market_key, commodity_key, unit, price_type, currency, month(month_date)
        ) as seasonal_idx
    from ratios
),
dev as (
    select *,
        ratio / seasonal_idx - 1 as deviation
    from seasonal
),
scored as (
    select *,
        -- plancher de 3 % sur l'écart-type : une série très stable ne passe pas
        -- en « crise » pour une hausse de 2 ou 3 %
        deviation / greatest(stddev_samp(deviation) over (
            partition by market_key, commodity_key, unit, price_type, currency
        ), 0.03) as score,
        count(*) over (partition by market_key, commodity_key, unit, price_type, currency) as n_points
    from dev
)
select
    sc.market_key,
    sc.commodity_key,
    sc.country_iso3,
    m.region,
    m.market,
    m.latitude,
    m.longitude,
    c.commodity,
    c.commodity_fr,
    c.category_fr,
    sc.unit,
    sc.price_type,
    sc.currency,
    sc.month_date,
    round(sc.price, 2)                         as price,
    round(sc.trend_12m * sc.seasonal_idx, 2)   as expected_price,
    round(100 * sc.deviation, 2)               as deviation_pct,
    round(sc.score, 2)                         as alert_score,
    case
        when sc.score >= 2    then 'Crise'
        when sc.score >= 1    then 'Alerte'
        when sc.score >= 0.25 then 'Stress'
        else 'Normal'
    end                                        as alert_level
from scored sc
join {{ ref('dim_market') }} m using (market_key)
join {{ ref('dim_commodity') }} c using (commodity_key)
where sc.n_points >= 12
