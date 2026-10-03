-- Chrome's browsing history, as synced to the Google account, from the
-- Data Portability exports: one row per page visit.
select
  id as visit_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'url') as url,
  domain(JSONExtractString(record, 'url')) as domain,
  if(JSONExtractInt(record, 'time_usec') > 0,
     fromUnixTimestamp64Micro(JSONExtractInt(record, 'time_usec'), 'UTC'), NULL) as visited_at,
  JSONExtractString(record, 'page_transition') as transition,
  extracted_at
from ({{ accumulated_records('google', ['portability/chrome.history']) }})
