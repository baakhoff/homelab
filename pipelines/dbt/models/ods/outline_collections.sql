-- One row per collection, the top-level groups documents are kept in.
select
  id as collection_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'description') as description,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('outline', 'collections.list') }})
