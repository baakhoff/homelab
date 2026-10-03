# Hardware inventory

Hardware on hand. Models and specs only — no serials, addresses or other
identifiers.

## Laptop — `node01`

| Field | Value |
|---|---|
| Model | MSI ultrabook — the exact model was never recorded, and the disk it could have been read from is wiped |
| CPU | Intel Core i5-1240P (12th gen) — 12 cores (4 P + 8 E), 16 threads |
| RAM | 16 GB |
| Disk | 512 GB NVMe SSD (Micron 3400) |
| NIC | Wi-Fi only — no built-in ethernet port |
| Role | **Retired: powered off 2026-09-19, wiped 2026-09-20.** Was the cluster's first node: Ubuntu Server 24.04, k3s, Flux, the Incus workbench, with the battery doubling as a built-in UPS. What it ran and how it was emptied: [the lab over time](history.md) |

## Raspberry Pi 3B+ — `exitnode`

| Field | Value |
|---|---|
| CPU | Broadcom BCM2837B0, 4× Cortex-A53 @ 1.4 GHz, 64-bit |
| RAM | 1 GB LPDDR2 |
| NIC | Gigabit PHY over USB 2.0 — ~300 Mbit/s practical ceiling; 2.4 / 5 GHz Wi-Fi. **Wired**, with the Wi-Fi profile kept as a fallback that does not connect automatically |
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
| State | Ubuntu Server 24.04, wired, keys-only SSH, swap off, upgraded and burnt in — [bring-up](runbooks/node-bring-up.md). In service as a three-node k3s cluster: all three are servers with embedded etcd, Flux reconciles `clusters/lab/`, and Rook-Ceph runs an OSD on each from a logical volume carved out of the unallocated space on its system disk |

Measured during bring-in, worth keeping as a baseline:

| | Result |
|---|---|
| Drive health | zero media errors and zero critical warnings on all three; 0–4% wear after 9,700–18,900 power-on hours |
| Sustained all-core load | 69–76 °C package, against a high threshold of 80 °C — stacked with no airflow, which is the worst case they will see |
| Idle | 34–39 °C |
| Throughput spread | within 3% of each other under `stress-ng` |

## Switch

| Field | Value |
|---|---|
| Model | TP-Link TL-SG108E, hardware V6 |
| Ports | 8 × 1 GbE |
| Management | web UI over HTTP, no TLS; VLANs, QoS and port mirroring available and unused |
| Power | 5 V wall-plug adapter, no separate brick |
| Role | the lab's wired backbone — the three mini PCs, the Pi, and the uplink to the mesh. Port map and addressing: [the network](network.md) |

## Rack

A 10-inch 3D-printed rack, 12U. The switch, the keystone patch panel, the three
mini PCs and the power shelf are mounted in it, and the mesh unit sits on the lid.
The Pi shelf and carrier are printed and not yet fitted.

Every printed part comes from MakerWorld; each link opens the print profile used.

| Part | For | Model |
|---|---|---|
| Frame | the rack itself, 10″ | [KWS Rack V2 (heavy duty)](https://makerworld.com/en/models/2139130-kws-rack-v-2-heavy-duty-10-inch-homelab-rack#profileId-2317125) |
| Mini PC mount | the three HP Elite Mini 600 G9 | [HP Elite Mini G9 600, 10″ rack mount](https://makerworld.com/en/models/1645139-hp-elite-mini-g9-600-10-inch-rack-mount#profileId-1738764) |
| Switch mount | the TP-Link TL-SG108E | [TP-Link TL-SG108 8-port switch, 10″ rack mount](https://makerworld.com/en/models/1765496-tp-link-8-port-switch-tl-sg108-10-in-rack-mount#profileId-1878782) |
| Patch panel | keystone jacks between the switch and the machines | [Patch keystones panel, 2–3U, for the KWS rack](https://makerworld.com/en/models/2154991-patch-keystones-panel-2-3u-for-10-inch-kws-rack#profileId-2335937) |
| Pi shelf | the snap-in base the Pi carrier slots into | [Rack snap-in system, 8-bay Raspberry Pi cluster](https://makerworld.com/en/models/2314737-rack-snap-in-system-8-bay-raspberry-pi-cluster#profileId-2527379) |
| Pi carrier | the Raspberry Pi 3B+ | [Raspberry Pi 3B for the rack snap-in system](https://makerworld.com/en/models/3067754-raspberry-pi-3b-2017-for-rack-snap-in-system#profileId-3453178) |
| Power shelf | the power adapters, 2U | [2U power supplies shelf for the KWS rack](https://makerworld.com/en/models/2383010-2u-power-supplies-shelf-for-kws-rack#profileId-2609751) |
