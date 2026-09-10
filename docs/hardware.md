# Hardware inventory

Hardware on hand. Models and specs only — no serials, addresses or other
identifiers.

## Laptop — `node01`

| Field | Value |
|---|---|
| Model | ultrabook-class, exact model TBD (`sudo dmidecode -s system-product-name`) |
| CPU | Intel Core i5-1240P (12th gen) — 12 cores (4 P + 8 E), 16 threads |
| RAM | 16 GB |
| Disk | 512 GB NVMe SSD (Micron 3400) |
| NIC | Wi-Fi only — no built-in ethernet port |
| Role | The cluster's first node: Ubuntu Server 24.04, k3s, Flux, the Incus workbench. The battery doubles as a built-in UPS |

## Raspberry Pi 3B+ — `exitnode`

| Field | Value |
|---|---|
| CPU | Broadcom BCM2837B0, 4× Cortex-A53 @ 1.4 GHz, 64-bit |
| RAM | 1 GB LPDDR2 |
| NIC | Gigabit PHY over USB 2.0 — ~300 Mbit/s practical ceiling; 2.4 / 5 GHz Wi-Fi. On 2.4 GHz Wi-Fi |
| Storage | SanDisk Extreme 32 GB microSDHC (A1 / V30); log2ram keeps logs off the card |
| OS | Raspberry Pi OS Lite 64-bit (Debian 13) |
| Role | Pi-hole DNS for the house and the tailnet; Tailscale exit node and subnet router. Build: [runbook](runbooks/pi-exitnode.md); why: [ADR 0005](decisions/0005-pi-house-dns-and-tailnet-door.md) |

## HP Elite Mini 600 G9 ×3 — `node02`, `node03`, `node04`

Three identical used units, bought in September 2026.

| Field | Value |
|---|---|
| CPU | Intel Core i5-12500T — 6 P-cores / 12 threads, 35 W; vPro, with Intel AMT present in the firmware |
| RAM | 16 GB DDR5-4800 as a single SO-DIMM; two slots, 64 GB maximum |
| Disk | 512 GB NVMe 2280 — two units KIOXIA BG5 (TLC), one Solidigm P41 Plus (QLC), all DRAM-less client drives. A second M.2 2280 PCIe 4.0 ×4 slot is free. A 2.5″ SATA bay exists but takes HP's bracket kit, not fitted |
| NIC | Intel I219-LM 1 GbE; one unit carries a second RJ-45 on a Flex-port module |
| Power | 90 W external adapter each; about 7 W idle per HP's figures |
| Size | 177 × 175 × 34 mm, 1.4 kg; rated for 10–35 °C ambient |
| State | Ubuntu Server 24.04 installed on each; not yet networked or joined to anything |

## Rack

10-inch 3D-printed rack: [KWS Rack V2 (heavy duty)](https://makerworld.com/en/models/2139130-kws-rack-v-2-heavy-duty-10-inch-homelab-rack) — print in progress. The Pi gets a printed 10″ mount; the laptop lives on a shelf beside it.
