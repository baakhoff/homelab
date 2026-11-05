-- The people in the household's messages and contacts, across sources:
-- one row per person, with every phone number, address and Telegram
-- account seen for them, and how much was written with them where.
--
-- A Google contact is a person, and takes in every Telegram chat whose
-- phone number it lists and every mail address it lists. A Telegram user
-- no contact matches is a person of their own - one row for both Telegram
-- accounts, by user id. A mail address no contact lists is a person only
-- if mail was sent to it: who writes to an inbox is mostly newsletters
-- and shops, who gets written to is people.
--
-- Matching is exact, on phone numbers with everything but digits and the
-- leading + dropped, and on lowercased addresses - a contact saved
-- without the country code does not match its Telegram chat.
with
contacts as (
  select
    contact_id,
    name,
    emails,
    arrayDistinct(arrayFilter(p -> length(p) > 4, arrayMap(p -> replaceRegexpAll(p, '[^0-9+]', ''), phones))) as phones
  from {{ ref('google_contacts') }}
),
contact_phones as (
  select contact_id, arrayJoin(phones) as phone from contacts
),
contact_emails as (
  select contact_id, arrayJoin(emails) as email from contacts
),
tg_chats as (
  select
    c.user_id,
    c.account,
    c.chat_key,
    c.name,
    c.usernames_seen,
    arrayFilter(p -> p != '', arrayMap(p -> replaceRegexpAll(p, '[^0-9+]', ''), c.phones_seen)) as phones,
    m.messages,
    m.first_at,
    m.last_at
  from {{ ref('telegram_chats') }} as c
  left join (
    select chat_key, count() as messages, min(sent_at) as first_at, max(sent_at) as last_at
    from {{ ref('telegram_messages') }}
    group by chat_key
  ) as m on m.chat_key = c.chat_key
  where not c.is_self and c.user_id is not null
),
tg_contact as (
  -- The contact each Telegram user matches, if any: by any phone number.
  select t.user_id, any(p.contact_id) as contact_id
  from (select user_id, arrayJoin(phones) as phone from tg_chats) as t
  inner join contact_phones as p on p.phone = t.phone
  group by t.user_id
),
tg_people as (
  select
    t.user_id,
    any(t.name) as name,
    groupUniqArray(t.account) as accounts,
    arrayDistinct(arrayFlatten(groupArray(t.usernames_seen))) as usernames,
    arrayDistinct(arrayFlatten(groupArray(t.phones))) as phones,
    sum(t.messages) as messages,
    minIf(t.first_at, t.messages > 0) as first_at,
    maxIf(t.last_at, t.messages > 0) as last_at
  from tg_chats as t
  group by t.user_id
),
mail as (
  -- Every address mail went to or came from, with whether any was sent to it.
  select
    address,
    anyIf(name, name != '') as name,
    count() as messages,
    countIf(outgoing) > 0 as written_to,
    min(at) as first_at,
    max(at) as last_at
  from (
    select from_address as address, from_name as name, false as outgoing, sent_at as at
    from {{ ref('proton_messages') }} where not is_sent
    union all
    select arrayJoin(arrayConcat(to_addresses, cc_addresses)) as address, '' as name, true as outgoing, sent_at as at
    from {{ ref('proton_messages') }} where is_sent
    union all
    select from_address as address, from_name as name, false as outgoing, sent_at as at
    from {{ ref('google_gmail_bodies') }} where not is_sent
    union all
    select arrayJoin(arrayConcat(to_addresses, cc_addresses)) as address, '' as name, true as outgoing, sent_at as at
    from {{ ref('google_gmail_bodies') }} where is_sent
    union all
    select sender_address as address, '' as name, false as outgoing, received_at as at
    from {{ ref('google_gmail_messages') }} where not is_sent
    union all
    select lower(arrayJoin(extractAll(concat(recipients, ',', cc), '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+'))) as address,
           '' as name, true as outgoing, received_at as at
    from {{ ref('google_gmail_messages') }} where is_sent
  )
  where address != ''
  group by address
),
mail_contact as (
  select m.address, any(e.contact_id) as contact_id
  from mail as m inner join contact_emails as e on e.email = m.address
  group by m.address
)

-- Google contacts, with what matched them.
select
  concat('google:', c.contact_id) as person_key,
  'google_contact' as anchor,
  c.name as name,
  arrayDistinct(arrayConcat(c.phones, ifNull(tg.phones, []))) as phones,
  c.emails as emails,
  c.contact_id as google_contact_id,
  ifNull(tg.user_ids, []) as telegram_user_ids,
  ifNull(tg.usernames, []) as telegram_usernames,
  ifNull(tg.accounts, []) as telegram_accounts,
  ifNull(tg.messages, 0) as telegram_messages,
  ifNull(ml.messages, 0) as mail_messages,
  -- A side that did not match is NULL or the epoch, depending on
  -- join_use_nulls; neither counts.
  nullIf(arrayMin(arrayFilter(x -> x > toDateTime64('1971-01-01', 3, 'UTC'), [tg.first_at, ml.first_at])),
         toDateTime64(0, 3, 'UTC')) as first_contact_at,
  nullIf(arrayMax(arrayFilter(x -> x > toDateTime64('1971-01-01', 3, 'UTC'), [tg.last_at, ml.last_at])),
         toDateTime64(0, 3, 'UTC')) as last_contact_at
from contacts as c
left join (
  select
    x.contact_id,
    groupArray(p.user_id) as user_ids,
    arrayDistinct(arrayFlatten(groupArray(p.usernames))) as usernames,
    arrayDistinct(arrayFlatten(groupArray(p.accounts))) as accounts,
    arrayDistinct(arrayFlatten(groupArray(p.phones))) as phones,
    sum(p.messages) as messages,
    min(p.first_at) as first_at,
    max(p.last_at) as last_at
  from tg_contact as x inner join tg_people as p on p.user_id = x.user_id
  group by x.contact_id
) as tg on tg.contact_id = c.contact_id
left join (
  select x.contact_id, sum(m.messages) as messages, min(m.first_at) as first_at, max(m.last_at) as last_at
  from mail_contact as x inner join mail as m on m.address = x.address
  group by x.contact_id
) as ml on ml.contact_id = c.contact_id

union all

-- Telegram users no contact matches.
select
  concat('telegram:', toString(p.user_id)) as person_key,
  'telegram' as anchor,
  p.name,
  p.phones,
  [] as emails,
  null as google_contact_id,
  [p.user_id] as telegram_user_ids,
  p.usernames as telegram_usernames,
  p.accounts as telegram_accounts,
  ifNull(p.messages, 0) as telegram_messages,
  0 as mail_messages,
  nullIf(p.first_at, toDateTime64(0, 3, 'UTC')) as first_contact_at,
  nullIf(p.last_at, toDateTime64(0, 3, 'UTC')) as last_contact_at
from tg_people as p
where p.user_id not in (select user_id from tg_contact)

union all

-- Addresses mail was sent to that no contact lists.
select
  concat('email:', m.address) as person_key,
  'email' as anchor,
  m.name,
  [] as phones,
  [m.address] as emails,
  null as google_contact_id,
  [] as telegram_user_ids,
  [] as telegram_usernames,
  [] as telegram_accounts,
  0 as telegram_messages,
  m.messages as mail_messages,
  m.first_at as first_contact_at,
  m.last_at as last_contact_at
from mail as m
where m.written_to and m.address not in (select address from mail_contact)
