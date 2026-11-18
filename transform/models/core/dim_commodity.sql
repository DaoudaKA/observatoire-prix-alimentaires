with c as (
    select distinct commodity, commodity_base, variety, category
    from {{ ref('stg_wfp_prices') }}
)
select
    md5(c.commodity)                                         as commodity_key,
    c.commodity,
    c.commodity_base,
    c.variety,
    c.category,
    coalesce(cat.category_fr, c.category)                    as category_fr,
    coalesce(full_fr.commodity_fr, coalesce(fr.commodity_fr, c.commodity_base)
      || case
           when c.variety is null then ''
           else ' (' || case lower(c.variety)
                          when 'imported' then 'importé'
                          when 'local' then 'local'
                          when 'white' then 'blanc'
                          when 'red' then 'rouge'
                          when 'dry' then 'sec'
                          when 'fresh' then 'frais'
                          when 'powder' then 'en poudre'
                          when 'vegetable' then 'végétale'
                          when 'palm' then 'de palme'
                          when 'shelled' then 'décortiquées'
                          when 'broken' then 'brisé'
                          else c.variety
                        end || ')'
         end)                                                as commodity_fr
from c
left join {{ ref('commodity_fr_full') }} full_fr on full_fr.commodity = c.commodity
left join {{ ref('commodity_fr') }} fr on fr.commodity_base = c.commodity_base
left join {{ ref('category_fr') }} cat on cat.category = c.category
