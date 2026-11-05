-- One row per file of a model - a mesh, a 3MF project, a picture, a PDF of
-- instructions - with its type and size, and whether it is the presupported
-- version of another.
select
  splitByChar('/', id)[-1] as file_id,
  splitByChar('/', JSONExtractString(record, 'isPartOf', '@id'))[-1] as model_id,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'encodingFormat'), '') as mime_type,
  JSONExtractUInt(record, 'contentSize') as bytes,
  JSONExtractBool(record, 'presupported') as presupported,
  nullIf(JSONExtractString(record, 'caption'), '') as caption,
  extracted_at
from ({{ snapshot_records('manyfold', 'model_files') }})
