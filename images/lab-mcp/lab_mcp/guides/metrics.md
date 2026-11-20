# metrics: Prometheus, the cluster's health (read only)

GET only. Answers are {"status": "success", "data": ...}.

## Endpoints
- GET /alerts                              alerts that are pending or firing now
- GET /query?query=PROMQL                  one value per series, now
- GET /query_range?query=PROMQL&start=2026-11-20T00:00:00Z&end=2026-11-20T12:00:00Z&step=5m
- GET /rules     GET /targets?state=active     GET /label/__name__/values

## Queries that are often useful
- ALERTS{alertstate="firing"}
- 100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)           memory used per node, %
- 100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))     CPU used per node, %
- kube_pod_status_phase{phase!~"Running|Succeeded"} == 1                            pods that are not running
- sum by (namespace) (container_memory_working_set_bytes{container!=""})            memory per namespace
