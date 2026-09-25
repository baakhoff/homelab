# oauth2-proxy

The login gate for services that have none. One Pocket ID client, one cookie
for `.lab.baakhoff.com`, and ingress-nginx asks this before proxying a request
to anything that carries the two annotations:

```yaml
nginx.ingress.kubernetes.io/auth-url: http://oauth2-proxy.oauth2-proxy.svc.cluster.local/oauth2/auth
nginx.ingress.kubernetes.io/auth-signin: https://auth.lab.baakhoff.com/oauth2/start?rd=$scheme://$host$request_uri
```

Behind it today: Homepage, Prometheus, Alertmanager, ConvertX,
Stirling-PDF. Not behind it: anything
that speaks OIDC itself (Grafana, Headlamp) — native login gives the app an
identity to attach roles to, this gives it a yes. And not Vaultwarden, which
holds the passkeys; the Pocket ID README says why.

## The secret

`secret.sops.yaml`, three keys, created by hand:

| Key | From |
|---|---|
| `OAUTH2_PROXY_CLIENT_ID` | the `oauth2-proxy` client in Pocket ID |
| `OAUTH2_PROXY_CLIENT_SECRET` | its Credentials tab, shown once |
| `OAUTH2_PROXY_COOKIE_SECRET` | `openssl rand -base64 32 \| tr -- '+/' '-_'` — 32 bytes, URL-safe base64 |

The client's callback URL is `https://auth.lab.baakhoff.com/oauth2/callback`,
PKCE on, Public Client off. Rotating the cookie secret logs everyone out and
nothing else; rotating the client secret is a new secret in Pocket ID and a
re-encrypt here.

## Adding a person

oauth2-proxy refuses an ID token whose `email_verified` claim is false, and
Pocket ID stores that flag per user. It is false for any account created before
*Emails Verified* was switched on under Application Configuration, and true by
default for accounts created after. The symptom is a 500 on oauth2-proxy's own
error page straight after a successful passkey login, with
`email in id_token (...) isn't verified` in the pod log.

The fix is in Pocket ID, per user: Administration → Users → the account →
**Email verified** on. It cannot be set from the user's own My Account page.
The setting is right for this instance because the admin types every address in
and there is no self-signup; the alternative is an oauth2-proxy flag whose name
begins with `INSECURE`, which is the wrong side to fix it on.

## Adding a service

Two annotations on its Ingress, as above. Nothing here changes. Who may reach
it is decided in Pocket ID on the client's *Allowed User Groups* tab — one
setting for every gated host, which is the point of one client rather than
one per service.

## When it is down

Every gated host answers 500 from ingress-nginx, because `auth_request` failed
rather than denied. Grafana and Headlamp are unaffected; so is Vaultwarden.
`kubectl -n oauth2-proxy logs deploy/oauth2-proxy` — the common causes are a
client secret that was rotated in Pocket ID but not here, and a cookie secret
that is not exactly 32 bytes after decoding.
