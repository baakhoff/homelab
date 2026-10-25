-- One row per Seerr account: the name it shows, how many requests it has
-- made, and when it first signed in. No email: the name tells the
-- accounts apart, and the address stays in raw.
select
  toUInt64OrZero(id) as user_id,
  JSONExtractString(record, 'displayName') as name,
  nullIf(JSONExtractString(record, 'plexUsername'), '') as plex_username,
  JSONExtractUInt(record, 'requestCount') as requests,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  extracted_at
from ({{ snapshot_records('seerr', 'user') }})
