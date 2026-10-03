select
  id as item_id,
  JSONExtractString(record, 'shoppingListId') as list_id,
  JSONExtractString(record, 'display') as display,
  JSONExtractString(record, 'note') as note,
  JSONExtractFloat(record, 'quantity') as quantity,
  JSONExtractBool(record, 'checked') as checked,
  JSONExtractString(record, 'label', 'name') as label,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('mealie', 'households/shopping/items') }})
