-- Contact groups (labels): the system ones (myContacts, starred) and the
-- account's own.
select
  id as group_id,
  if(JSONExtractString(record, 'formattedName') != '',
     JSONExtractString(record, 'formattedName'),
     JSONExtractString(record, 'name')) as name,
  JSONExtractString(record, 'groupType') as group_type,
  JSONExtractUInt(record, 'memberCount') as members,
  extracted_at
from ({{ snapshot_records('google', 'contacts/groups') }})
