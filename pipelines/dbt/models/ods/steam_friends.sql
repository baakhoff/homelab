-- Steam friends, one row each: since when, and their name, profile and
-- country as their own profiles show them. Empty while the friends list
-- is private. A friend removed drops out at the next run.
with profiles as (
  select id, record from ({{ snapshot_records('steam', 'friend_profiles') }})
)
select
  f.id as steamid,
  if(JSONExtractUInt(f.record, 'friend_since') = 0, NULL,
     toDateTime(JSONExtractUInt(f.record, 'friend_since'), 'UTC')) as friend_since,
  nullIf(JSONExtractString(p.record, 'personaname'), '') as name,
  nullIf(JSONExtractString(p.record, 'realname'), '') as real_name,
  nullIf(JSONExtractString(p.record, 'profileurl'), '') as profile_url,
  nullIf(JSONExtractString(p.record, 'loccountrycode'), '') as country,
  f.extracted_at
from ({{ snapshot_records('steam', 'friends') }}) f
left join profiles p on p.id = f.id
