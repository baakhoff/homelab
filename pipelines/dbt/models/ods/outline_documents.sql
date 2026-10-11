-- One row per published document: its collection, its parent if it is
-- nested, its Markdown text, and who wrote it. Drafts are not listed by the
-- API, so they are not here until published. A document deleted in Outline
-- is gone from the next snapshot, and so from here.
select
  id as document_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'collectionId') as collection_id,
  nullIf(JSONExtractString(record, 'parentDocumentId'), '') as parent_document_id,
  JSONExtractString(record, 'text') as text,
  JSONExtractString(record, 'createdBy', 'name') as created_by,
  JSONExtractString(record, 'updatedBy', 'name') as updated_by,
  JSONExtractString(record, 'url') as url,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  {{ ts("JSONExtractString(record, 'publishedAt')") }} as published_at,
  {{ ts("JSONExtractString(record, 'archivedAt')") }} as archived_at,
  extracted_at
from ({{ snapshot_records('outline', 'documents.list') }})
