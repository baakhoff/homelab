# Hardware inventory

## Laptop

| Field | Value |
|---|---|
| Model | ultrabook-class, exact model TBD (`sudo dmidecode -s system-product-name`) |
| CPU | Intel Core i5-1240P (12th gen) — 12 cores (4 P + 8 E), 16 threads |
| RAM | 16 GB |
| Disk | 512 GB NVMe SSD (Micron 3400) |
| NIC | Wi-Fi only — no built-in ethernet port |
| Notes | Battery doubles as a built-in UPS; Tailscale already installed |

## Raspberry Pi 3B+

| Field | Value |
|---|---|
| CPU | Broadcom BCM2837B0, 4× Cortex-A53 @ 1.4 GHz (arm64-capable) |
| RAM | 1 GB LPDDR2 |
| NIC | Gigabit PHY over USB 2.0 — ~300 Mbit/s practical ceiling |
| Storage | microSD — quality A1/A2 card; log2ram reduces write wear |
| Notes | 1 GB RAM limits it to lightweight duties |
