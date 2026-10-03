select
  id as recipe_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'slug') as slug,
  JSONExtractFloat(record, 'rating') as rating,
  JSONExtractString(record, 'totalTime') as total_time,
  arrayMap(c -> JSONExtractString(c, 'name'), JSONExtractArrayRaw(record, 'recipeCategory')) as categories,
  arrayMap(t -> JSONExtractString(t, 'name'), JSONExtractArrayRaw(record, 'tags')) as tags,
  {{ ts("JSONExtractString(record, 'dateAdded')") }} as added_at,
  {{ ts("JSONExtractString(record, 'dateUpdated')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('mealie', 'recipes') }})
