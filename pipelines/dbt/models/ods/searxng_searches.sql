{{ config(materialized='incremental', incremental_strategy='append', order_by='(ts)', partition_by='toYYYYMM(ts)') }}

-- Every search made on SearXNG, from the household's browsers and from the
-- agent pods alike. SearXNG keeps nothing itself; its web server logs one
-- line per request (clusters/lab/searxng/deployment.yaml), the collectors
-- carry it to raw.logs, and ods.logs keeps it 90 days. This keeps the
-- searches for good.
--
-- A line looks like
--   searxng-access ::ffff:10.42.0.18 someone@example.org "GET /search?q=rust+lifetimes&categories=general" 200 912
-- Lines from before the address was logged lack that field.
--
-- user_email: the Pocket ID address the gate passed on. Empty for the
-- agent pods, which reach SearXNG without the gate, and for searches from
-- before it was logged. A pod in agents could send the header itself, so
-- for via = 'api' it is not evidence of anything.
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
    extractGroups(body, '^searxng-access (\\S+) (?:([^\\s"]+) )?"(\\S+) (\\S+)" (\\d+) (\\d+)') as g
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
  if(g[2] in ('', '-'), '', g[2]) as user_email,
  decodeURLFormComponent(extractURLParameter(g[4], 'q')) as query,
  decodeURLFormComponent(extractURLParameter(g[4], 'categories')) as categories,
  extractURLParameter(g[4], 'language') as language,
  greatest(toUInt16OrZero(extractURLParameter(g[4], 'pageno')), 1) as pageno,
  if(extractURLParameter(g[4], 'format') = 'json', 'api', 'browser') as via,
  g[1] as client_addr,
  toUInt16OrZero(g[5]) as status,
  toUInt32OrZero(g[6]) as duration_ms,
  sensitive,
  ingested_at
from lines
where length(g) = 6
  and startsWith(g[4], '/search?')
  and extractURLParameter(g[4], 'q') != ''
