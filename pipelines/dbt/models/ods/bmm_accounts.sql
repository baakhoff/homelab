-- One row per social account connected to a BMM profile. The access tokens
-- are never in the API's answer.
select
  id as account_id,
  JSONExtractString(record, 'profileId') as profile_id,
  JSONExtractString(record, 'network') as network,
  JSONExtractString(record, 'username') as username,
  JSONExtractString(record, 'displayName') as display_name,
  JSONExtractString(record, 'externalId') as external_id,
  JSONExtractString(record, 'status') as status,
  {{ ts("JSONExtractString(record, 'connectedAt')") }} as connected_at,
  extracted_at
from ({{ snapshot_records('bmm', 'accounts') }})
