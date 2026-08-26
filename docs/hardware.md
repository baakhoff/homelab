# Hardware inventory

## Laptop (first server node)

Specs TBD. To fill this in, run on the laptop:

```bash
lscpu | grep -E 'Model name|^CPU\(s\)'; free -h | head -2; lsblk -d -o NAME,SIZE,MODEL,ROTA; ip -br link
```

| Field | Value |
|---|---|
| Model | TBD |
| CPU | TBD |
| RAM | TBD (decides D1: Proxmox vs bare metal) |
| Disk | TBD |
| NIC | TBD (wired strongly preferred for a server) |

## Raspberry Pi 3B+ (learning node / utility)

| Field | Value |
|---|---|
| CPU | Broadcom BCM2837B0, 4× Cortex-A53 @ 1.4 GHz (arm64-capable) |
| RAM | 1 GB LPDDR2 |
| NIC | Gigabit ethernet limited to ~300 Mbit real (USB 2.0 bus); 100 Mbit in practice varies |
| Storage | microSD — use a quality A1/A2 card; consider log2ram to reduce wear |
| Notes | 1 GB RAM makes it a tainted, lightweight k3s agent at best — or a great standalone DNS box |

## Planned

- Additional Raspberry Pis (4/5 class — much better k3s workers than the 3B+)
- NAS (build vs buy — decision D4 in [roadmap.md](roadmap.md))
- Dedicated PC as first serious amd64 worker
