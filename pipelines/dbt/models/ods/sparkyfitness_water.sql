-- Water drunk, one total per day - the API's own daily sum.
select
  toDateOrNull(id) as entry_date,
  JSONExtractFloat(record, 'water_ml') as water_ml,
  extracted_at
from ({{ snapshot_records('sparkyfitness', 'measurements/water-intake-range') }})
