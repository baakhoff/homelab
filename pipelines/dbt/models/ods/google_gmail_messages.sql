-- Gmail, one row per message: who wrote to whom, when, the subject and the
-- labels. No bodies - the DAG's token cannot read one (gmail.metadata).
-- Messages deleted in Gmail drop out; trashed and spam ones are here, with
-- their label.
with messages as (
  select
    id,
    record,
    extracted_at,
    arrayMap(h -> (lower(JSONExtractString(h, 'name')), JSONExtractString(h, 'value')),
             JSONExtractArrayRaw(record, 'payload', 'headers')) as headers,
    JSONExtract(record, 'labelIds', 'Array(String)') as label_ids
  from ({{ accumulated_records('google', ['gmail/messages']) }})
)
select
  id as message_id,
  JSONExtractString(record, 'threadId') as thread_id,
  fromUnixTimestamp64Milli(toInt64OrZero(JSONExtractString(record, 'internalDate')), 'UTC') as received_at,
  arrayFirst(h -> h.1 = 'from', headers).2 as sender,
  lower(trimBoth(if(position(sender, '<') > 0, extract(sender, '<([^>]+)>'), sender))) as sender_address,
  arrayFirst(h -> h.1 = 'to', headers).2 as recipients,
  arrayFirst(h -> h.1 = 'cc', headers).2 as cc,
  arrayFirst(h -> h.1 = 'subject', headers).2 as subject,
  arrayFirst(h -> h.1 = 'list-id', headers).2 as list_id,
  arrayFirst(h -> h.1 = 'in-reply-to', headers).2 != '' as is_reply,
  label_ids,
  has(label_ids, 'SENT') as is_sent,
  has(label_ids, 'INBOX') as is_inbox,
  has(label_ids, 'UNREAD') as is_unread,
  has(label_ids, 'SPAM') as is_spam,
  has(label_ids, 'TRASH') as is_trash,
  JSONExtractUInt(record, 'sizeEstimate') as size_bytes,
  extracted_at
from messages
