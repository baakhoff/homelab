select
  toStartOfHour(ts) as hour,
  namespace,
  container,
  count() as lines,
  countIf(level = 'warning') as warnings,
  countIf(level in ('error', 'fatal')) as errors
from {{ ref('logs') }}
group by hour, namespace, container
