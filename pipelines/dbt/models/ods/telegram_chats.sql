-- Private chats: one row per person each account has ever had a one-to-one
-- chat with, and one for each account's own Saved Messages - kept even after the chat
-- is deleted in Telegram, so a message's sender can always be traced.
--
-- Each row is the person as last seen. Who they were before is kept beside
-- it: every username and phone number any run has seen for them, since
-- people rename themselves and the user id is the only thing that stays.
-- `listed_now` says whether the chat is still in the account's chat list.
-- `chat_key` is the row's key: the chat id, after "<account>:" for every
-- account but `main` - the same person in two accounts is two rows.
with rows as (
  select
    JSONExtractString(payload, 'run_id') as run_id,
    JSONExtractString(payload, 'id') as id,
    JSONExtractRaw(payload, 'record') as record,
    coalesce(nullIf(JSONExtractString(record, 'account'), ''), 'main') as account,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at,
    kafka_ts
  from {{ source('raw', 'telegram') }}
  where JSONExtractString(payload, 'endpoint') = 'chats'
),
-- Per account: one account's failed run must not unlist the other's chats.
latest_run as (
  select account, argMax(run_id, kafka_ts) as run_id from rows group by account
),
history as (
  select
    id,
    min(extracted_at) as first_seen_at,
    arraySort(arrayDistinct(arrayFilter(x -> x != '', arrayFlatten(groupArray(
      arrayConcat([JSONExtractString(record, 'username')], JSONExtract(record, 'usernames', 'Array(String)'))
    ))))) as usernames_seen,
    arraySort(groupUniqArrayIf(JSONExtractString(record, 'phone'), JSONExtractString(record, 'phone') != '')) as phones_seen
  from rows
  group by id
),
latest as (
  select id, account, record, extracted_at, run_id
  from rows
  order by kafka_ts desc
  limit 1 by id
)
select
  latest.id as chat_key,
  latest.account as account,
  JSONExtractInt(record, 'id') as chat_id,
  JSONExtract(record, 'user_id', 'Nullable(Int64)') as user_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'first_name') as first_name,
  JSONExtractString(record, 'last_name') as last_name,
  nullIf(JSONExtractString(record, 'username'), '') as username,
  nullIf(JSONExtractString(record, 'phone'), '') as phone,
  nullIf(JSONExtractString(record, 'link'), '') as link,
  history.usernames_seen,
  history.phones_seen,
  JSONExtractBool(record, 'is_self') as is_self,
  JSONExtractBool(record, 'is_contact') as is_contact,
  JSONExtractBool(record, 'is_mutual_contact') as is_mutual_contact,
  JSONExtractBool(record, 'is_deleted') as is_deleted,
  JSONExtractBool(record, 'archived') as archived,
  JSONExtractInt(record, 'unread_count') as unread_count,
  {{ ts("JSONExtractString(record, 'last_message_at')") }} as last_message_at,
  latest.run_id = latest_run.run_id as listed_now,
  history.first_seen_at,
  latest.extracted_at as extracted_at
from latest
inner join history on history.id = latest.id
inner join latest_run on latest_run.account = latest.account
