{#
  dbt's default names a custom schema "<target schema>_<custom>", which here
  would build ods models into a database called ods_ods. The layers are
  fixed databases, so the folder's schema is used exactly as written.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
