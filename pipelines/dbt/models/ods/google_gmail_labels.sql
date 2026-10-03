-- Gmail's labels: the system ones (INBOX, SENT, CATEGORY_*) and the
-- account's own. Join to google_gmail_messages.label_ids for the names.
select
  id as label_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'type') as type,
  extracted_at
from ({{ snapshot_records('google', 'gmail/labels') }})
