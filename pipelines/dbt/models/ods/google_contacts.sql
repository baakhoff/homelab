-- Google Contacts, one row per person. Groups are their resource names
-- (contactGroups/...); google_contact_groups has the names.
select
  id as contact_id,
  JSONExtractString(JSONExtractArrayRaw(record, 'names')[1], 'displayName') as name,
  JSONExtractString(JSONExtractArrayRaw(record, 'names')[1], 'givenName') as given_name,
  JSONExtractString(JSONExtractArrayRaw(record, 'names')[1], 'familyName') as family_name,
  arrayMap(e -> lower(JSONExtractString(e, 'value')), JSONExtractArrayRaw(record, 'emailAddresses')) as emails,
  arrayMap(p -> if(JSONExtractString(p, 'canonicalForm') != '', JSONExtractString(p, 'canonicalForm'), JSONExtractString(p, 'value')),
           JSONExtractArrayRaw(record, 'phoneNumbers')) as phones,
  JSONExtractString(JSONExtractArrayRaw(record, 'organizations')[1], 'name') as organization,
  JSONExtractString(JSONExtractArrayRaw(record, 'organizations')[1], 'title') as job_title,
  JSONExtractUInt(JSONExtractArrayRaw(record, 'birthdays')[1], 'date', 'year') as birth_year,
  JSONExtractUInt(JSONExtractArrayRaw(record, 'birthdays')[1], 'date', 'month') as birth_month,
  JSONExtractUInt(JSONExtractArrayRaw(record, 'birthdays')[1], 'date', 'day') as birth_day,
  arrayFilter(g -> g != '', arrayMap(m -> JSONExtractString(m, 'contactGroupMembership', 'contactGroupResourceName'),
              JSONExtractArrayRaw(record, 'memberships'))) as groups,
  {{ ts("JSONExtractString(JSONExtractArrayRaw(record, 'metadata', 'sources')[1], 'updateTime')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('google', 'contacts/people') }})
