select
  toDate(ts) as day,
  namespace,
  type,
  reason,
  kind,
  count() as events
from {{ ref('k8s_events') }}
group by day, namespace, type, reason, kind
