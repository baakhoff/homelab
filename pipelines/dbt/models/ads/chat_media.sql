-- The photos and videos sent in Telegram and VK chats, as they are in
-- Immich: one row per picture and message it was sent in - who sent it,
-- when, in which chat, with what text, and what Claude saw in it.
--
-- The tie is the hash in the file's name (ods.immich_assets), made when
-- the file was fetched: for Telegram the first 12 hex digits of
-- sha256("<account's user id>/<chat id>/<message id>")
-- (pipelines/tools/telegram_media.py, ingest_telegram), for VK of
-- sha256(<the link>) (pipelines/tools/vk_media.py). A VK link sent in
-- several messages is one file, and a row for each. The same file sent in
-- two Telegram messages is stored once by Immich, under the first name it
-- came with: the hourly upload records which picture the second one is
-- (raw.telegram, endpoint `media`), so it has its row too; in the history
-- fetched once, only the first has. A picture whose message is not in the
-- warehouse - a VK wall or album entry, a Telegram group with --groups - is
-- a row with the message's columns empty.
--
-- `status`: active, the picture is in Immich; deleted, it was deleted
-- there; duplicate, it was removed as a duplicate in Immich, or this
-- message's file is a copy of a picture first sent in another. Nothing
-- leaves: a deleted picture keeps its rows, its description included.
--
-- `sent_at` is UTC, for Telegram; VK's archive wrote local time, so for VK
-- it is empty and `sent_at_local` holds it. `sender` is the chat's person
-- for what they sent, NULL for the account's own. `immich_url` opens the
-- picture; `type` and `description` are immich_sort's, once it has looked.
with
assets as (
  select asset_id, file_name, kind, source, file_hash, status, taken_at
  from {{ ref('immich_assets') }}
  where file_hash is not null
),
-- The hourly upload's word on each message's file.
uploads as (
  select
    JSONExtractString(payload, 'id') as message_key,
    JSONExtractString(payload, 'record', 'asset_id') as asset_id,
    JSONExtractString(payload, 'record', 'upload') = 'duplicate' as is_copy
  from {{ source('raw', 'telegram') }}
  where JSONExtractString(payload, 'endpoint') = 'media'
  order by kafka_ts desc
  limit 1 by message_key
),
owners as (
  select account, any(user_id) as owner_id
  from {{ ref('telegram_chats') }}
  where is_self
  group by account
),
telegram as (
  select
    coalesce(u.asset_id, h.asset_id) as asset_id,
    coalesce(u.is_copy, false) as is_copy,
    m.account as account,
    m.chat_key as chat_key,
    c.name as chat_name,
    m.message_key as message_key,
    m.sent_at as sent_at,
    CAST(NULL, 'Nullable(DateTime)') as sent_at_local,
    m.is_outgoing as is_outgoing,
    if(m.is_outgoing, NULL, c.name) as sender,
    m.text as text,
    m.media_kind as media_kind,
    m.is_forwarded as is_forwarded,
    m.forwarded_from_name as forwarded_from,
    m.reply_to_message_id as reply_to_message_id,
    m.album_id as album_id
  from {{ ref('telegram_messages') }} m
  inner join owners o on o.account = m.account
  left join {{ ref('telegram_chats') }} c on c.chat_key = m.chat_key
  left join uploads u on u.message_key = m.message_key
  left join (select * from assets where source = 'telegram') h
    on h.file_hash = substring(lower(hex(SHA256(concat(toString(o.owner_id), '/', toString(m.chat_id), '/', toString(m.message_id))))), 1, 12)
  where m.media_kind is not null
),
vk as (
  select
    h.asset_id as asset_id,
    false as is_copy,
    'vk' as account,
    m.conversation_id as chat_key,
    m.conversation_name as chat_name,
    m.message_key as message_key,
    CAST(NULL, 'Nullable(DateTime64(3, \'UTC\'))') as sent_at,
    m.sent_at_local as sent_at_local,
    m.is_outgoing as is_outgoing,
    if(m.is_outgoing, NULL, m.sender_name) as sender,
    m.text as text,
    CAST(NULL, 'Nullable(String)') as media_kind,
    false as is_forwarded,
    CAST(NULL, 'Nullable(String)') as forwarded_from,
    CAST(NULL, 'Nullable(Int64)') as reply_to_message_id,
    CAST(NULL, 'Nullable(Int64)') as album_id
  from {{ ref('vk_messages') }} m
  array join arrayDistinct(m.attachment_links) as link
  inner join (select * from assets where source = 'vk') h on h.file_hash = substring(lower(hex(SHA256(link))), 1, 12)
),
messages as (
  select * from telegram where asset_id is not null
  union all
  select * from vk
)
select
  a.asset_id as asset_id,
  concat('https://photos.lab.baakhoff.com/photos/', a.asset_id) as immich_url,
  a.file_name as file_name,
  a.kind as kind,
  a.source as source,
  multiIf(a.status != 'active', a.status, m.is_copy, 'duplicate', 'active') as status,
  m.account as account,
  m.chat_key as chat_key,
  m.chat_name as chat_name,
  m.message_key as message_key,
  m.sent_at as sent_at,
  m.sent_at_local as sent_at_local,
  m.is_outgoing as is_outgoing,
  m.sender as sender,
  m.text as text,
  m.media_kind as media_kind,
  m.is_forwarded as is_forwarded,
  m.forwarded_from as forwarded_from,
  m.reply_to_message_id as reply_to_message_id,
  m.album_id as album_id,
  p.type as type,
  p.description as description,
  p.city as city,
  p.country as country,
  a.taken_at as taken_at
from assets a
left join messages m on m.asset_id = a.asset_id
left join {{ ref('immich_photos') }} p on p.asset_id = a.asset_id
settings join_use_nulls = 1
