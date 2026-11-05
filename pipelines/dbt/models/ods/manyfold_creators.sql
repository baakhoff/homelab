-- One row per creator - a designer or a shop the models came from - with
-- their links (Printables, Thingiverse, MakerWorld and the like).
select
  splitByChar('/', id)[-1] as creator_id,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'caption'), '') as caption,
  nullIf(JSONExtractString(record, 'description'), '') as description,
  arrayMap(l -> JSONExtractString(l, 'url'), JSONExtractArrayRaw(record, 'links')) as links,
  extracted_at
from ({{ snapshot_records('manyfold', 'creators') }})
