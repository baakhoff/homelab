-- One row per model in the 3D model library: its name, caption and
-- description, its licence, who made it, the collections it is in, its tags
-- and how many files it has. A model deleted in Manyfold is gone from the
-- next snapshot, and so from here.
--
-- Ids are Manyfold's own short ids, out of the "@id" links.
select
  splitByChar('/', id)[-1] as model_id,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'caption'), '') as caption,
  nullIf(JSONExtractString(record, 'description'), '') as description,
  nullIf(JSONExtractString(record, 'spdx:license', 'licenseId'), '') as license,
  nullIf(splitByChar('/', JSONExtractString(record, 'creator', '@id'))[-1], '') as creator_id,
  arrayMap(c -> splitByChar('/', JSONExtractString(c, '@id'))[-1], JSONExtractArrayRaw(record, 'isPartOf')) as collection_ids,
  JSONExtract(record, 'keywords', 'Array(String)') as tags,
  length(JSONExtractArrayRaw(record, 'hasPart')) as files,
  JSONExtractBool(record, 'sensitive') as sensitive,
  arrayMap(l -> JSONExtractString(l, 'url'), JSONExtractArrayRaw(record, 'links')) as links,
  extracted_at
from ({{ snapshot_records('manyfold', 'models') }})
