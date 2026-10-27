[English](README.md) | [简体中文](README.zh-CN.md)

# Supermicro H13SSL-N: two 48 GiB AD102 cards

This port contains mochgolf's tested local adaptation.
Its base is `elias-gaeros/gpu-unlock` commit `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`.
The AD102 payload and original `gpu_unlock` module are unchanged.
The accepted path clears platform-leftover BME through a separate diagnostic module before loading the original unlock module.

Development also included an offline review of a different hardened-BME patch.
That patch was not used for the accepted A/B/A experiment or dual-card deployment. This port does not substitute it.

## Tested configuration

| Component | Native validation |
|---|---|
| Board / BIOS | Supermicro H13SSL-N / 3.5 |
| GPUs | Two AD102 `10de:2684`, modified 48 GiB boards, 49,140 MiB reported capacity each |
| PCI functions | `0000:41:00.0`, `0000:01:00.0` |
| Console | ASPEED at `0000:c6:00.0`; neither NVIDIA card is boot VGA |
| Kernel | `7.0.0-34-generic` |
| Driver | Locally patched `nvidia-open-p2p/595.84` with 48 GiB/P2P support; **not stock 595.84** |
| Default power | 450 W per card, unchanged for deployment |
| Firmware generation | Upstream pinned 610.43.03 assets |

The DMI, BIOS, capacity, and PCI checks remain pinned to this configuration.
Acceptance does not cover similar boards, other BIOS versions, stock 24 GiB cards, or other slot layouts.
The separate NVIDIA driver patches are an existing dependency. This repository does not contain them.

## Components and behavior

- `gpu_bme_diag.c` and `bme_diag_core.h` handle one explicitly selected function.
  They require an unbound D0 AD102, the tested cold firmware state, and no pending transaction.
  If PCI command is 7, the diagnostic writes 3 once and reads it back.
  The other sampled state must remain unchanged.
  It starts no firmware, allocates no DMA, resets no device, and binds no driver. It does not write Tensor selectors.
  An uncertain write stops the operation. No retry re-enables incoming firmware MASTER.
- `gpu_cold_probe.c` collects pre-driver state through upstream pure parsers and read-only BAR/config mappings.
  **Do not run it on a GPU that NVIDIA already owns.** The reminder uses stored boot receipts.
- `initramfs/experiment_init_top.sh` implements the accepted dual-card sequence, success checks, and failure stops.
  It must run before the original udev trigger, with no NVIDIA or nouveau module present.
- `initramfs/persist_early.sh.in` preserves the deployed persistence logic.
  Required placeholders replace only the private root device and UUID.
- `initramfs/verify_unlock_log.sh` requires success, cleanup, FLR, and retained-selector evidence for each card.
  A successful `insmod` return alone is insufficient.
- `stage_overlay.py` is a new public wrapper with offline validation.
  It fills the root placeholders, validates module/firmware inputs, and stages a fresh directory.
  It does not install an image or change GRUB.
- `provenance.json` records hashes and differences between native-tested sources and the parameterized publication template.

If a cold-state check fails before hardware action, the hook can return to the original udev path.
It records `stock-fallback-no-hardware-action`. This is not unlock success.
After any hardware action, a failure stops boot progression and saves evidence.

The fallback branch passed chroot tests.
The tested warm boot satisfied the cold checks and completed a full unlock.
The non-cold fallback branch has not been forced on hardware.

## Build and check without hardware access

From the repository root, use matching headers, a C compiler, and generated upstream firmware:

```sh
make test ASSETS=/path/to/generated/610.43.03/assets
make -C kernel/gpu_unlock KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl test
```

The suite includes 21 BME transaction/fault cases and 19 reminder tests.
With assets available, it also runs 42 fake-PCI collector/proof checks.
These tests do not access real PCI devices.
Without generated firmware, CI explicitly skips the 42-case collector fixture.

Host test results do not constitute hardware acceptance.

Before staging, review the binaries and obtain their SHA-256 hashes.
A matching vermagic alone is insufficient.
Use this example with your reviewed inputs:

```sh
python3 ports/supermicro-h13ssl/stage_overlay.py \
  --output build/h13ssl-overlay \
  --root-device /dev/REPLACE_WITH_ROOT_PARTITION \
  --root-uuid REPLACE_WITH_ROOT_FILESYSTEM_UUID \
  --firmware-assets /path/to/generated/assets \
  --unlock-module kernel/gpu_unlock/gpu_unlock.ko \
  --unlock-sha256 REPLACE_WITH_REVIEWED_SHA256 \
  --diag-module ports/supermicro-h13ssl/gpu_bme_diag.ko \
  --diag-sha256 REPLACE_WITH_REVIEWED_SHA256 \
  --cold-probe build/h13ssl/gpu_cold_probe
```

## Boot-image requirements

The original deployment used a separately built image.
It preserved the original microcode prefix and every original initramfs file.
It inserted `00_gpu_ab` before the original `udev` entry in `scripts/init-top/ORDER`.
The visible safe-A entry remained unchanged. Independent console recovery remained available.

Before the persistence hook runs, prepare `/var/backups/gpu-unlock-ab-events` on the pinned root partition.
The directory must be root-owned with mode 0700.
Copying the overlay onto an active machine does not install it.

The public wrapper and template rendering passed offline and build checks.
Publication did not install them or execute firmware again.
The source transaction and boot flow passed native acceptance only on the configuration above.

## Acceptance and performance

Cold locked A1, unlocked B1, and cold locked A2 confirmed the target gain.
A second physical card stayed locked as the control.
Later dual-card deployment passed native checks, an ordinary warm reboot, and a cold start.
Read the [benchmark report](../../benchmarks/2026-10-26/README.md) for measurements, negative results, and application limits.

The optional [boot/SSH reminder](../../monitoring/README.md) reports missing or failed evidence without another hardware transaction.
