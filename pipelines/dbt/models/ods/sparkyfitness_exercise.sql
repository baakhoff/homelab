-- Workouts: one row per session. A session is either one exercise
-- ("individual") or a preset workout of several ("preset"), whose calories
-- are the sum of its exercises'.
select
  id as session_id,
  JSONExtractString(record, 'type') as type,
  toDateOrNull(JSONExtractString(record, 'entry_date')) as entry_date,
  if(JSONExtractString(record, 'name') != '', JSONExtractString(record, 'name'),
     JSONExtractString(record, 'exercise_snapshot', 'name')) as name,
  if(type = 'preset',
     JSONExtractFloat(record, 'total_duration_minutes'),
     JSONExtractFloat(record, 'duration_minutes')) as duration_minutes,
  if(type = 'preset',
     arraySum(e -> JSONExtractFloat(e, 'calories_burned'), JSONExtractArrayRaw(record, 'exercises')),
     JSONExtractFloat(record, 'calories_burned')) as calories_burned,
  JSONExtractString(record, 'source') as source,
  extracted_at
from ({{ snapshot_records('sparkyfitness', 'v2/exercise-entries/history') }})
