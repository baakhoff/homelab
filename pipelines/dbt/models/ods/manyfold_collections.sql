-- One row per collection of models, with the creator it belongs to and the
-- collection it sits in, if any.
select
  splitByChar('/', id)[-1] as collection_id,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'caption'), '') as caption,
  nullIf(JSONExtractString(record, 'description'), '') as description,
  nullIf(splitByChar('/', JSONExtractString(record, 'creator', '@id'))[-1], '') as creator_id,
  nullIf(splitByChar('/', JSONExtractString(record, 'isPartOf', '@id'))[-1], '') as parent_collection_id,
  extracted_at
from ({{ snapshot_records('manyfold', 'collections') }})
