-- Paperless documents' metadata. The OCR text stays in raw.paperless
-- (record.content); it is large and wanted rarely, and this layer is for
-- counting and joining.
select
  toUInt64OrZero(id) as document_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractUInt(record, 'correspondent') as correspondent_id,
  JSONExtractUInt(record, 'document_type') as document_type_id,
  JSONExtractUInt(record, 'storage_path') as storage_path_id,
  JSONExtract(record, 'tags', 'Array(UInt64)') as tag_ids,
  {{ ts("JSONExtractString(record, 'created')") }} as created_at,
  {{ ts("JSONExtractString(record, 'added')") }} as added_at,
  {{ ts("JSONExtractString(record, 'modified')") }} as modified_at,
  JSONExtractUInt(record, 'archive_serial_number') as archive_serial_number,
  JSONExtractUInt(record, 'page_count') as page_count,
  JSONExtractString(record, 'mime_type') as mime_type,
  JSONExtractString(record, 'original_file_name') as original_file_name,
  extracted_at
from ({{ snapshot_records('paperless', 'documents') }})
