# Mealie

The household's recipe book. Paste a link to a recipe on almost any site and
Mealie imports it: ingredients, steps, photo. Plan the week's meals on a
calendar, and turn a plan or a handful of recipes into a shopping list the
whole household sees and ticks off.

At <https://recipes.lab.baakhoff.com>, and on Homepage under Lab.

## How login works

Pocket ID, through Mealie's own OpenID Connect support, behind the
oauth2-proxy gate as well (ingress.yaml says why). In practice it is one
passkey: the gate asks for it, and Mealie's login finds the Pocket ID session
already there. There is no Mealie password.

Each account is created at its first login, in the default group and
household, so everyone shares the same recipes, meal plans and shopping
lists. Members of the Pocket ID group `mealie-admins` are Mealie admins.

## Setup, in this order

The pod waits in `CreateContainerConfigError` until step 2 exists. That is not
a crash and does not alert. It starts by itself once the Secret reconciles.

**1. Create the OIDC client in Pocket ID** at `https://id.lab.baakhoff.com`,
Administration → OIDC Clients → Add:

| Field | Value |
|---|---|
| Name | Mealie |
| Callback URLs | `https://recipes.lab.baakhoff.com/login` and `https://recipes.lab.baakhoff.com/login?direct=1` |
| PKCE | on |
| Public Client | off |
| Allowed User Groups | the people who share the recipes, e.g. `mealie-users` |

Then, under Administration → User Groups, create `mealie-admins` and put
yourself in it.

Mealie refuses a login whose email Pocket ID does not report as verified.
Under Administration → Users, check that each person's email is marked
verified.

**2. Create the Secret on the workstation**, entering the client ID and secret
Pocket ID shows. `read -rs` keeps both out of the shell history, and nothing
below prints them.

```bash
read -rsp 'client id: ' CID; echo
read -rsp 'client secret: ' CSEC; echo

kubectl create secret generic mealie-oidc \
  --namespace mealie \
  --from-literal=OIDC_CLIENT_ID="$CID" \
  --from-literal=OIDC_CLIENT_SECRET="$CSEC" \
  --dry-run=client -o yaml > clusters/lab/mealie/oidc.sops.yaml

unset CID CSEC
sops --encrypt --in-place clusters/lab/mealie/oidc.sops.yaml
```

Commit and push. The pre-commit hook asserts the file is encrypted.

**3. Sign in** at <https://recipes.lab.baakhoff.com>.

**4. Delete the default admin.** Mealie creates an admin account on first
start, `changeme@example.com`, with a password printed in its own
documentation. Switching the login form off hides it, but Mealie's API still
accepts it. Under Settings → Admin → Users, delete that account. Until then,
the gate and networkpolicy.yaml are what keep it out of reach.

## Things to know

- **Languages.** Each person picks their own interface language under their
  profile. Recipes stay in whatever language they were imported in.
- **AI features** (importing a recipe from a photo, or parsing free-text
  ingredients into amounts and units) are off until an AI provider is added in
  the admin settings. OpenRouter works there, as it does for Paperless, and
  the recipe text then leaves the cluster.
- **The mobile apps and API tokens** cannot get through the gate. The web app
  works well on a phone, and can be added to the home screen.

## Backup - not yet, and in this order

The same three pieces as Paperless, whose README has the reasoning:

1. **The `restic-repo` Secret in the `mealie` namespace**, encrypted into
   `clusters/lab/backup/restic-repo-mealie.sops.yaml`. It uses the same values
   as the other copies and differs only in `metadata.namespace`.
2. **The `RoleBinding`**, already in `clusters/lab/backup/rbac.yaml`.
3. **`mealie/mealie-data` in `BACKUP_TARGETS`**, last, after the Secret has
   reconciled.
