-- What was eaten: one row per diary entry. The nutrients on an entry are
-- per serving_size of the food, as SparkyFitness stores them; what was
-- actually eaten is that times quantity / serving_size - the same scaling
-- the app's own diary applies.
select
  id as entry_id,
  toDateOrNull(JSONExtractString(record, 'entry_date')) as entry_date,
  JSONExtractString(record, 'meal_type') as meal_type,
  JSONExtractString(record, 'food_name') as food_name,
  JSONExtractString(record, 'brand_name') as brand_name,
  JSONExtractFloat(record, 'quantity') as quantity,
  JSONExtractString(record, 'unit') as unit,
  JSONExtractFloat(record, 'serving_size') as serving_size,
  if(serving_size > 0, quantity / serving_size, NULL) as servings,
  JSONExtractFloat(record, 'calories') * servings as calories,
  JSONExtractFloat(record, 'protein') * servings as protein_g,
  JSONExtractFloat(record, 'carbs') * servings as carbs_g,
  JSONExtractFloat(record, 'fat') * servings as fat_g,
  JSONExtractFloat(record, 'dietary_fiber') * servings as fiber_g,
  JSONExtractFloat(record, 'sugars') * servings as sugars_g,
  JSONExtractFloat(record, 'sodium') * servings as sodium_mg,
  extracted_at
from ({{ snapshot_records('sparkyfitness', 'food-entries/range') }})
