# Hardware inventory

## Laptop

Specs TBD. To fill this in, run on the laptop:

```bash
lscpu | grep -E 'Model name|^CPU\(s\)'; free -h | head -2; lsblk -d -o NAME,SIZE,MODEL,ROTA; ip -br link
```

| Field | Value |
|---|---|
| Model | TBD |
| CPU | TBD |
| RAM | TBD |
| Disk | TBD |
| NIC | TBD |

## Raspberry Pi 3B+

| Field | Value |
|---|---|
| CPU | Broadcom BCM2837B0, 4× Cortex-A53 @ 1.4 GHz (arm64-capable) |
| RAM | 1 GB LPDDR2 |
| NIC | Gigabit PHY over USB 2.0 — ~300 Mbit/s practical ceiling |
| Storage | microSD — quality A1/A2 card; log2ram reduces write wear |
| Notes | 1 GB RAM limits it to lightweight duties |
