-- Prix mensuels validés. Grain : marché × produit × unité × type de prix × devise × mois.
-- Contrôle qualité (voir int_prices_flagged) : on écarte les pics isolés et les mois-pays erronés (erreurs de saisie dans la source, ex. Gambie,
-- décembre 2018 : prix doublés un seul mois). Un relevé est aberrant s'il s'écarte de plus de
-- ×1,8 (ou moins de ×0,55) de la médiane mobile centrée sur 7 mois de sa propre série.
-- Les relevés écartés sont tracés dans qa_price_outliers.
select * exclude (rolling_median, n_window, ratio_to_median, country_month_ratio, is_outlier)
from {{ ref('int_prices_flagged') }}
where not is_outlier
