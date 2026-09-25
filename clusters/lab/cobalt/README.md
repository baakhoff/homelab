# cobalt

Paste a link from YouTube, TikTok, Instagram, Reddit, X, SoundCloud, Vimeo and
[many more](https://github.com/imputnet/cobalt#supported-services), and the video
or audio downloads to the device you pasted it on. Nothing is stored in the
cluster: the file streams from the site, through the API, straight to the
browser. When a site serves video and audio separately, as YouTube does,
they are merged on the way through.

At <https://cobalt.lab.baakhoff.com>, and on Homepage under Lab.

## How it is put together

One pod, two containers:

| Container | Image | What it does |
|---|---|---|
| `web` | `ghcr.io/baakhoff/cobalt-web`, built in `images/cobalt-web/` | nginx: serves the page and forwards API calls to `api` |
| `api` | `ghcr.io/imputnet/cobalt`, upstream | fetches from the source site and streams to the browser; listens on loopback only |

Both are on one hostname so that the Pocket ID gate covers the API as well as
the page. `nginx.yaml` explains the routing, including the one path the two
share.

The two images carry the same version and move together. `images/cobalt-web/README.md`
has the upgrade order.

## Login

Pocket ID through oauth2-proxy, like ConvertX. cobalt has no accounts of its own.
If a session expires while the page is open, downloads fail with a generic error
until the page is reloaded, which sends the browser through Pocket ID again.

## When a site stops working

Sites change how they serve media, and cobalt follows. A service that worked
and stops usually needs a newer cobalt version, which Renovate proposes. Check
[upstream's issues](https://github.com/imputnet/cobalt/issues) for the site
first; the log shows what the API received:

```bash
kubectl -n cobalt logs deploy/cobalt -c api --tail=100
```

YouTube in particular sometimes refuses unauthenticated requests. cobalt can
send cookies from a logged-in account (`COOKIE_PATH`). That would be a
throwaway Google account's cookies in a SOPS Secret, added only if YouTube
downloads start failing.
