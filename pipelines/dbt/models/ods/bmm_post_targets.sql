-- One row per account a BMM post goes to: whether it was published there,
-- the link the network gave, or the network's error.
select
  JSONExtractString(target, 'id') as target_id,
  post_id,
  profile_id,
  JSONExtractString(target, 'accountId') as account_id,
  JSONExtractString(target, 'network') as network,
  JSONExtractString(target, 'username') as username,
  JSONExtractString(target, 'status') as status,
  JSONExtractUInt(target, 'attempts') as attempts,
  JSONExtractString(target, 'externalUrl') as url,
  JSONExtractString(target, 'error') as error,
  {{ ts("JSONExtractString(target, 'publishedAt')") }} as published_at,
  extracted_at
from (
  select
    id as post_id,
    JSONExtractString(record, 'profileId') as profile_id,
    arrayJoin(JSONExtractArrayRaw(record, 'targets')) as target,
    extracted_at
  from ({{ snapshot_records('bmm', 'posts') }})
)
