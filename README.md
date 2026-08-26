# homelab

Building a homelab out of spare hardware to learn production infrastructure end to end —
networking, clustering, Kubernetes, GitOps, observability — and to host agentic dev
tooling (Claude Code instances) off my main workstation.

The build is documented here as it happens: what exists, how it was set up, and which
decisions were made and why.

## Hardware

| Device | Specs | Status |
|---|---|---|
| Laptop | i5-1240P · 16 GB RAM · 512 GB NVMe · Wi-Fi only — [details](docs/hardware.md) | not yet provisioned |
| Raspberry Pi 3B+ | 4× Cortex-A53 @ 1.4 GHz, 1 GB RAM | not yet provisioned |
| Rack | 10″ 3D-printed — [KWS Rack V2](https://makerworld.com/en/models/2139130-kws-rack-v-2-heavy-duty-10-inch-homelab-rack) | printing |

## Repo layout

```
docs/
  hardware.md     # hardware inventory and specs
  decisions/      # architecture decision records (ADRs)
```

## Principles

- Everything as code, GitOps where possible — if it's not in the repo, it doesn't exist.
- No secrets in the repo, ever. Encrypted (SOPS/age) once GitOps needs them.
- Docs updated in the same change that alters behavior, not later.
- Docs describe what exists and what was decided — not what might happen.
- Skills over convenience: choices favor what transfers to production work.
