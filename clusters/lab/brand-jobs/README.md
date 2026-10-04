# brand-jobs

Scheduled work for the brand agent: Kubernetes CronJobs that the `brand` pod
(`clusters/lab/agents/brand.yaml`) creates, runs and deletes itself, through
the Kubernetes API, in this namespace and nowhere else.

## The exception to GitOps

Everything else in the lab is in this repository and Flux applies it. The
CronJobs here are not: brand creates them live, so the namespace's *contents*
exist only in the cluster. Flux owns the frame around them - the namespace,
the permissions, the quota and the network policy, all in this directory -
and never touches what brand puts inside, because those objects are not in
its inventory and pruning only removes what Flux itself applied.

The cost is that a rebuilt cluster comes back with an empty namespace. brand
should keep the manifests of anything worth keeping in its own repositories
and `kubectl apply` them from there, so a lost CronJob is one command away.

## What brand can do here

`rbac.yaml` is the whole list. CronJobs and Jobs: everything, including
running one now with `kubectl create job --from=cronjob/<name> <run-name>`.
Pods, logs and events: read, and delete a stuck pod. ConfigMaps and Secrets:
everything - a job's script and its credentials live here and never in the
repository.

It cannot create ServiceAccounts, Roles or bindings, so every job runs as
this namespace's `default` account, which has no rights and mounts no token.
It cannot act in any other namespace, and no job can reach the Kubernetes
API at all.

## What a job may reach

The same as brand: cluster DNS, the internet, the Firefly API broker and
Vikunja's API (`networkpolicy.yaml`, with matching rules in those two
services' own policies). Not the house LAN, the tailnet or any other lab
service. Nothing can reach a job.

## Writing a CronJob that is admitted

The namespace enforces the `restricted` Pod Security level, and a pod that
does not meet it is refused when the Job tries to create it - which shows up
as a Job with no pods and a `FailedCreate` event, not as an error from
`kubectl apply`. Every container needs:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000          # or whatever non-root uid the image uses
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
  seccompProfile:
    type: RuntimeDefault
```

Resources default to a 64Mi request and a 256Mi limit (`resourcequota.yaml`),
and a container may not ask for more than 1Gi. The namespace as a whole is
capped at four pods and 1Gi of requested memory at once, and at twenty
CronJobs. Set `successfulJobsHistoryLimit` and `failedJobsHistoryLimit` low
and `concurrencyPolicy: Forbid` unless overlap is intended.

A failed job raises the cluster's `KubeJobFailed` alert in Telegram, like any
other. Deleting the failed Job clears it.

## Checking it from a terminal

```bash
kubectl -n brand-jobs get cronjobs,jobs,pods
kubectl auth can-i --list --as=system:serviceaccount:agents:brand -n brand-jobs
```

From inside the brand pod, `kubectl` already points at this namespace.
