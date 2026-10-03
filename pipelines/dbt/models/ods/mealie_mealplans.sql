-- Planned meals: one row per plan entry (a day, a meal slot, a recipe or a note).
select
  id as mealplan_id,
  toDateOrNull(JSONExtractString(record, 'date')) as date,
  JSONExtractString(record, 'entryType') as entry_type,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'recipeId') as recipe_id,
  JSONExtractString(record, 'recipe', 'name') as recipe_name,
  extracted_at
from ({{ snapshot_records('mealie', 'households/mealplans') }})
