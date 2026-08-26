# 0001 — Public GitHub repo, private working notes

- Status: accepted
- Date: 2026-08-26

## Context

The homelab is a learning project whose value multiplies if done in public: writing
docs/ADRs for an audience forces clarity, and the history becomes a portfolio. But
working notes, draft plans, and agent tooling files are noise (or private) and don't
belong in the public record.

## Decision

- GitHub is the canonical host; the repo is public from day one.
- Only finished, sanitized material is tracked: docs, ADRs, runbooks, and later the
  actual infra code (manifests, compose, CI).
- Working notes and local tooling files stay untracked via `.git/info/exclude` (not the
  tracked `.gitignore`), so the public repo carries no trace of them.
- Hygiene rules for tracked files: no secrets ever (encrypted with SOPS/age once GitOps
  needs them), no public IPs, MACs, SSIDs, serials, or precise location. RFC1918
  addresses and internal hostnames are fine.

## Consequences

- Everything committed must pass the "public" bar — slightly more friction per commit,
  much better docs.
- Secret management discipline is forced early (good — it's the production habit).
- Private context lives only on the workstation; it is not backed up by the repo and
  needs its own backup path.
