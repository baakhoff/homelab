# SearXNG

[SearXNG](https://github.com/searxng/searxng), a metasearch engine. One query
goes from this pod to Google, Bing, DuckDuckGo, Wikipedia and a few dozen
more, and the results come back merged on one page. The search engines see
the lab's address and the query, and no account, cookie or profile.

At <https://search.lab.baakhoff.com>, and on Homepage under Tools.

## As the browser's search engine

Open the page once, signed in. Then:

- **Firefox:** right-click the address bar → *Add "lab search"*, then
  Settings → Search → Default search engine.
- **Chrome:** Settings → Search engine → Manage → *lab search* under
  "Inactive shortcuts" → Activate, then *Make default*.

After a gate session expires, the first search goes through Pocket ID and
then lands on its results.

## From the agent pods

Every pod in `agents` can search, past the gate, through the JSON API:

```
curl -s 'http://searxng.searxng.svc.cluster.local/search?q=kubernetes+networkpolicy&format=json' \
  | jq '.results[:5][] | {title, url, content}'
```

The door is a NetworkPolicy on each side: `egress-searxng` in
`clusters/lab/agents/networkpolicy.yaml`, and this namespace's policy.

## Login

Pocket ID through oauth2-proxy, the household gate. SearXNG has no accounts.
Preferences set on its settings page live in a cookie in that browser.

## What it keeps

Nothing. Settings come from `settings.yaml`, the cache is an `emptyDir`,
and the secret key that signs the image proxy's links is made fresh at
every start. No volume, so no backup entry.

Settings live in `settings.yaml`, holding only what differs from upstream's
defaults. Bump `searxng/settings` in `deployment.yaml` with any edit, so
the pod restarts and reads it.

## What goes to the warehouse

Every search, as `ods.searxng_searches`: the query, categories, language,
page, whether it came from a browser or the API, and how long it took.
SearXNG keeps no history of its own. Its web server logs each request with
its query string, the collectors carry that line to `raw.logs` like any
other, and the model keeps the searches past `ods.logs`'s 90 days. That is
why the form uses GET rather than upstream's POST: with POST the query
would not be in the line.

The collectors mask secrets in the line before it leaves the node
(`pipelines/sensitive.md`), so a key pasted into the search box arrives
masked, with `sensitive = 1`.

**Who can read it:** anyone who can read `ods`, which includes the brand
agent's `brand` user.

## When an engine stops answering

Search engines block scrapers, and SearXNG follows them. One engine missing
from the results is normal and the others cover it. The results page's
*Engine stats* say which ones fail, and why.

```bash
kubectl -n searxng logs deploy/searxng --tail=100 | grep -v searxng-access
```

The fix is usually a newer image. Renovate offers one monthly; for a
sooner bump, take the newest tag from Docker Hub
(`searxng/searxng`, `<date>-<commit>`).
