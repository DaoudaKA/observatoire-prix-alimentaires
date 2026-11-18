{% test dbt_utils_positive(model, column_name) %}
select * from {{ model }} where {{ column_name }} <= 0
{% endtest %}
