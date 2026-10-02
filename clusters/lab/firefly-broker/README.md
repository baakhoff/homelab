# firefly-broker

The CFO seat's way into Firefly III's API. A Firefly Personal Access Token
carries the owner's rights over the household's books, and the seat's rules
say it must never hold one - so the token lives here instead, in a lab-side
nginx that adds it to requests the agent host sends. The seat calls this
broker; the broker calls Firefly; nothing in the agent host ever sees a
credential.

    [CFO tools in slot-1] --HTTP--> [firefly-broker] --HTTP--> [Firefly /api/v1]

## How it is reached

`http://firefly-broker.firefly-broker.svc.cluster.local/v1/...` - from
slot-1, and from nowhere else: `networkpolicy.yaml` here admits only
slot-1's pods, and the matching egress door in
`clusters/lab/hermes-slots/networkpolicy.yaml` is the only way out of a
slot towards it. `/v1/...` maps onto Firefly's `/api/v1/...`; the broker
replaces the caller's Authorization header with the token, strips the login
headers Firefly trusts, and forwards Firefly's response unmodified.

A caller's own `Accept` header passes through (the CSV export wants
`text/csv`); with none, the broker sends JSON:API's
`application/vnd.api+json`. `GET` only, for now: `limit_except` in the
ConfigMap answers anything else with 403. The seat's mandate starts with
reads (accounts, transactions, budgets, exports); enabling writes is a CEO
call and a one-line change in `configmap.yaml`.

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

1. In Firefly, signed in as the owner: Options → Profile → OAuth →
   Personal Access Tokens → Create, name it `cfo-broker`.
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
   `CreateContainerConfigError` - not a crash, does not alert.

Rotation: revoke the old token on the same UI screen, create a new one and
repeat step 2. Quarterly is the plan; any doubt, rotate now.

## Verify, from slot-1

```bash
BASE=http://firefly-broker.firefly-broker.svc.cluster.local
curl -s "$BASE/v1/about"    | head -c 200   # Firefly version JSON
curl -s "$BASE/v1/accounts" | head -c 200   # account list
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BASE/v1/accounts"   # 403
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
- Nothing to back up: no volume, no state.
