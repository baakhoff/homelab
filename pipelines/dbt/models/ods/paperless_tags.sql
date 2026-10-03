select
  toUInt64OrZero(id) as id,
  JSONExtractString(record, 'name') as name,
  JSONExtractUInt(record, 'document_count') as document_count,
  extracted_at
from ({{ snapshot_records('paperless', 'tags') }})
