# 0002 — Bare-metal Ubuntu Server on the first node (no hypervisor)

- Status: accepted
- Date: 2026-08-26

## Context

The first server node is a laptop: i5-1240P (12c/16t), 16 GB RAM, 512 GB NVMe. Two ways
to provision it were considered:

1. **Proxmox underneath** — a hypervisor layer with the cluster inside VMs. Adds
   virtualization skills, VM snapshots, and cloud-like node provisioning.
2. **Bare-metal Ubuntu Server** — the OS directly on hardware, Kubernetes directly on
   the OS.

## Decision

Bare-metal Ubuntu Server 24.04 LTS. Kubernetes runs directly on the OS; no hypervisor
layer on this node.

Reasons, in order of weight:

- **RAM budget.** 16 GB is the floor where a hypervisor plus guest-OS overhead starts
  visibly eating the budget meant for actual workloads (cluster components,
  observability stack, agentic dev environments).
- **Learning focus.** The skills meant to transfer to production work are Kubernetes and
  GitOps — the layer above the hypervisor. Virtualization as a subject is deferred until
  a machine with more headroom joins the lab.
- (Minor, historical: the laptop has no ethernet port, and hypervisor bridged networking
  over Wi-Fi is notoriously fiddly. A USB gigabit adapter mostly neutralized this
  argument before the decision was made; it did not carry the decision.)

## Consequences

- All 16 GB and all cores go to workloads; one less layer to install, patch, and debug
  before Kubernetes exists.
- No VM snapshots for host-level rollback. Mitigation: the node is treated as cattle —
  configuration lives in the repo, cluster state reconciles from git (GitOps), so the
  rebuild path is reflash + rejoin rather than restore-from-snapshot.
- Virtualization skills are not exercised on this node. A future, better-equipped node
  can revisit the hypervisor question with its own ADR; this decision covers only the
  laptop.
