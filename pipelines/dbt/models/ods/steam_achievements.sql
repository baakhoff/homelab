-- Steam achievements, one row per achievement of every game played: its
-- name and description, whether it is unlocked and when, and how many
-- players have it (`global_percent`, Steam-wide). A game's are read again
-- whenever its playtime moves (pipelines/dags/steam.py); each
-- achievement's newest copy.
select
  id as achievement_key,
  JSONExtractUInt(record, 'appid') as appid,
  JSONExtractString(record, 'game') as game,
  JSONExtractString(record, 'apiname') as api_name,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'description'), '') as description,
  JSONExtractUInt(record, 'achieved') = 1 as unlocked,
  if(JSONExtractUInt(record, 'unlocktime') = 0, NULL,
     toDateTime(JSONExtractUInt(record, 'unlocktime'), 'UTC')) as unlocked_at,
  JSONExtract(record, 'global_percent', 'Nullable(Float64)') as global_percent,
  extracted_at
from ({{ accumulated_records('steam', ['achievements']) }})
