{{ config(materialized='incremental', incremental_strategy='append', order_by='(ts)', partition_by='toYYYYMM(ts)') }}

-- Every search made on SearXNG, from the household's browsers and from the
-- agent pods alike. SearXNG keeps nothing itself; its web server logs one
-- line per request (clusters/lab/searxng/deployment.yaml), the collectors
-- carry it to raw.logs, and ods.logs keeps it 90 days. This keeps the
-- searches for good.
--
-- A line looks like
--   searxng-access ::ffff:10.42.0.18 "GET /search?q=rust+lifetimes&categories=general" 200 912
--
-- via:
--   browser  a person, through the gate and the results page
--   api      format=json, which in this lab means an agent pod
--
-- A second page of the same search is a row of its own, with pageno 2.
-- Secrets typed into the search box were masked by the collectors before
-- they reached raw.logs; such a row has sensitive = 1.
with lines as (
  select
    ts,
    sensitive,
    ingested_at,
    extractGroups(body, '^searxng-access (\\S+) "(\\S+) (\\S+)" (\\d+) (\\d+)') as g
  from {{ ref('logs') }}
  where namespace = 'searxng'
    and container = 'searxng'
    and startsWith(body, 'searxng-access ')
  {% if is_incremental() -%}
    and ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
)
select
  ts,
  decodeURLFormComponent(extractURLParameter(g[3], 'q')) as query,
  decodeURLFormComponent(extractURLParameter(g[3], 'categories')) as categories,
  extractURLParameter(g[3], 'language') as language,
  greatest(toUInt16OrZero(extractURLParameter(g[3], 'pageno')), 1) as pageno,
  if(extractURLParameter(g[3], 'format') = 'json', 'api', 'browser') as via,
  g[1] as client_addr,
  toUInt16OrZero(g[4]) as status,
  toUInt32OrZero(g[5]) as duration_ms,
  sensitive,
  ingested_at
from lines
where length(g) = 5
  and startsWith(g[3], '/search?')
  and extractURLParameter(g[3], 'q') != ''
