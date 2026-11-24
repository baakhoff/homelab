-- One row per BMM API token: what it may do and when it was last used.
-- The secret itself is never in the API's answer, only its first characters.
select
  id as token_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'prefix') as prefix,
  JSONExtract(record, 'scopes', 'Array(String)') as scopes,
  JSONExtract(record, 'profileIds', 'Array(String)') as profile_ids,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'lastUsedAt')") }} as last_used_at,
  {{ ts("JSONExtractString(record, 'expiresAt')") }} as expires_at,
  extracted_at
from ({{ snapshot_records('bmm', 'tokens') }})
