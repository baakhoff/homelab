-- What is in Google Drive: one row per file or folder, never its contents.
-- Google Docs, Sheets and the like take no quota, so their size is NULL.
select
  id as file_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'mimeType') as mime_type,
  JSONExtractString(record, 'mimeType') = 'application/vnd.google-apps.folder' as is_folder,
  JSONExtractString(record, 'fileExtension') as extension,
  JSONExtract(record, 'parents', 'Array(String)')[1] as parent_id,
  toUInt64OrNull(JSONExtractString(record, 'size')) as size_bytes,
  toUInt64OrNull(JSONExtractString(record, 'quotaBytesUsed')) as quota_bytes,
  JSONExtractBool(record, 'starred') as starred,
  JSONExtractBool(record, 'trashed') as trashed,
  JSONExtractBool(record, 'shared') as shared,
  JSONExtractBool(record, 'ownedByMe') as owned_by_me,
  JSONExtractString(JSONExtractArrayRaw(record, 'owners')[1], 'displayName') as owner,
  JSONExtractString(record, 'lastModifyingUser', 'displayName') as modified_by,
  {{ ts("JSONExtractString(record, 'createdTime')") }} as created_at,
  {{ ts("JSONExtractString(record, 'modifiedTime')") }} as modified_at,
  {{ ts("JSONExtractString(record, 'viewedByMeTime')") }} as viewed_at,
  extracted_at
from ({{ snapshot_records('google', 'drive/files') }})
