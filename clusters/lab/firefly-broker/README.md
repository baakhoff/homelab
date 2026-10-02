# firefly-broker

The CFO seat's way into Firefly III's API. A Firefly Personal Access Token
carries the owner's rights over the household's books, and the seat's rules
say it must never hold one - so the token lives here instead, in a lab-side
nginx that adds it to requests the agent host sends. The seat calls this
broker; the broker calls Firefly; nothing in the agent host ever sees a
credential.

    [an agent's tools] --HTTP--> [firefly-broker] --HTTP--> [Firefly /api/v1]

Its caller is the `brand` agent pod (`clusters/lab/agents/brand.yaml`).

## How it is reached

`http://firefly-broker.firefly-broker.svc.cluster.local/v1/...` - from
the brand pod, and from nowhere else: `networkpolicy.yaml` here admits only
its pods, and `clusters/lab/agents/networkpolicy-brand.yaml` is the matching
egress door out of the agents namespace, which otherwise reaches nothing in
the lab. Another agent needs a rule in both. `/v1/...` maps onto Firefly's `/api/v1/...`; the broker
replaces the caller's Authorization header with the token, strips the login
headers Firefly trusts, and forwards Firefly's response unmodified.

A caller's own `Accept` header passes through. One trap, found live during
acceptance: do **not** send `Accept: text/csv` - Firefly's content
negotiation answers 406 for anything outside its whitelist (JSON, JSON:API,
form-urlencoded, octet-stream, `*/*`). On the default accept the export
returns the CSV itself, as `application/octet-stream`; with no `Accept` at
all, the broker sends JSON:API's `application/vnd.api+json`.

The door: `GET`, `POST` and `PUT` reach Firefly; `DELETE` and everything
else answer 403 from `limit_except` in the ConfigMap - destructive methods
are a deliberate hold, and widening later is the same one line.

## Why it cannot become a second login door

Firefly trusts `X-Auth-Request-Email` from the gate to sign a user in, and
its NetworkPolicy is what keeps that trust safe
(`clusters/lab/firefly/README.md`). The broker's rule in that policy opens
the pod, so the guarantee moves into the broker's own config: the login
headers are cleared on every proxied request, the caller's Authorization is
replaced by the token, and only `/v1/*` paths exist. A caller who tries to
smuggle the header in gets it stripped; nothing through here can become a
web session, and the API answers only tokens.

## The token

Created once, by hand, from Firefly's own UI:

1. In Firefly, signed in as the owner, open
   <https://firefly.lab.baakhoff.com/profile/oauth> - the token page exists
   but is not linked from the UI - and create a token named `cfo-broker`.
2. On the workstation, from the repo root:

   ```bash
   read -rsp 'firefly token: ' TOK; echo

   kubectl create secret generic firefly-broker \
     --namespace firefly-broker \
     --from-literal=FIREFLY_TOKEN="$TOK" \
     --dry-run=client -o yaml > clusters/lab/firefly-broker/token.sops.yaml

   unset TOK
   sops --encrypt --in-place clusters/lab/firefly-broker/token.sops.yaml
   ```

   Commit and push. Until it reconciles, the broker waits in
   `CreateContainerConfigError` - not a crash, but not silent either: the
   Deployment's not-ready warnings (KubePodNotReady, replicas mismatch, rollout
   stuck) fire after 15 minutes; they clear the moment the token lands.

Rotation: revoke the old token on the same page, create a new one and
repeat step 2. Quarterly is the plan; any doubt, rotate now.

## Verify, from the brand pod

```bash
BASE=http://firefly-broker.firefly-broker.svc.cluster.local
curl -s "$BASE/v1/about"    | head -c 200   # Firefly version JSON
curl -s "$BASE/v1/accounts" | head -c 200   # account list

# The door: an empty-body write reaches Firefly and gets Firefly's own
# refusal (415 or 422 - not a 403); DELETE never leaves the broker.
curl -s -o /dev/null -w '%{http_code}\n' -X POST   "$BASE/v1/accounts"    # 415/422
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$BASE/v1/accounts/1"  # 403
```

From anywhere else in the cluster the first call goes unanswered - that is
the NetworkPolicy, not a listener, refusing it.

## Limits

- One replica; more would work, it is stateless.
- No public route. The household's surface (`firefly.lab.baakhoff.com`) is
  untouched by this component, `/api` under the gate included.
- The token carries the owner's rights on the API - that is what the seat
  needs, and why the credential lives here and nowhere else. A compromised
  broker would carry the same power: the pinned image and the rotation are
  the controls.
- Config edits render at container start: after changing `configmap.yaml`,
  restart - `kubectl -n firefly-broker rollout restart deployment/firefly-broker`.
  Flux updates the ConfigMap object; nothing reloads a running nginx.
- Nothing to back up: no volume, no state.
