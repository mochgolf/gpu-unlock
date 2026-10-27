# Supermicro H13SSL-N / dual 48 GiB AD102 port

This is the source of **mochgolf's measured local adaptation**, based on
`elias-gaeros/gpu-unlock` at `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`.
The AD102 payload and original `gpu_unlock` module are unchanged. The accepted
path normalizes platform-leftover PCI bus mastering in a **separate diagnostic
module before loading the original unlock module**. A different hardened-BME
patch was reviewed offline during development; it was not the module used for
the accepted A/B/A or dual-card deployment and is not substituted here.

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

The DMI/BIOS/capacity/PCI guards are intentionally still pinned. Similar boards,
different BIOSes, stock 24 GiB cards and different slot layouts are not covered
by this hardware acceptance. The separate NVIDIA driver patches are an existing
dependency, not part of this repository.

## Files and behavior

- `gpu_bme_diag.c`, `bme_diag_core.h`: one explicitly selected function; require
  an unbound D0 AD102, the tested firmware/cold state and no pending transaction.
  If command is 7, write command 3 once, read it back and require the other sampled
  state to remain unchanged. It does not start firmware, allocate DMA, reset,
  bind a driver, or write the Tensor selectors. Uncertain writes stop; no retry
  re-enables incoming firmware MASTER.
- `gpu_cold_probe.c`: pre-driver read-only collector, using the upstream pure
  parsers. Its BAR/config mappings are read-only. **Do not run this collector
  against a GPU already owned by NVIDIA**; the production reminder uses stored
  boot receipts instead.
- `initramfs/experiment_init_top.sh`: the accepted dual-card pre-udev sequence,
  success proof and stop-on-failure logic. It must run before the original udev
  trigger and before any NVIDIA/nouveau module is present.
- `initramfs/persist_early.sh.in`: the deployed persistence implementation with
  just the private root device/UUID replaced by required placeholders.
- `initramfs/verify_unlock_log.sh`: independently require all success, cleanup,
  FLR and retained-selector receipts for each card. A successful `insmod` exit
  alone does not qualify the transaction.
- `stage_overlay.py`: a new, offline-verified public staging wrapper. It renders
  the root placeholders, validates firmware/module inputs and stages files in
  a fresh directory. It never installs an image or changes a GRUB entry.
- `provenance.json`: hashes and exact distinctions between native-tested sources
  and the parameterized publication template.

On a pre-action cold-condition failure, the hook can hand back to the original
udev path and explicitly records `stock-fallback-no-hardware-action`. This is
not unlock success. Any failure after hardware action stops the boot flow and
persists evidence. The fallback branch passed chroot tests; actual warm boot on
this machine satisfied the cold predicates and performed a full unlock, so the
non-cold fallback branch has not itself been forced on hardware.

## Build and offline checks

From the repository root, with matching headers, a C compiler and upstream
generated firmware available:

```sh
make test ASSETS=/path/to/generated/610.43.03/assets
make -C kernel/gpu_unlock KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl test
```

The port tests include 21 BME transaction/fault cases, 42 fake-PCI collector/proof
checks when assets are available, and 19 reminder state/notification tests.
These do not touch real PCI devices. CI without generated firmware skips the
42-case collector fixture explicitly; that is not a hardware acceptance result.

Example staging invocation; provide hashes of the **reviewed binaries you intend
to use**, rather than blindly accepting a binary with matching vermagic:

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

The original deployment used a separately built image, preserved the original
microcode prefix and all original initramfs files, and inserted `00_gpu_ab`
before the original `udev` entry in `scripts/init-top/ORDER`. A visible, unchanged
safe-A entry and independent console recovery were retained. The pinned root
partition must contain a root-owned mode-0700
`/var/backups/gpu-unlock-ab-events` before the early persistence hook runs.
Merely copying this overlay onto an active machine is not an installation.

The public wrapper and template rendering have offline/build validation. They
were not reinstalled or given another firmware run just for publication. The
source transaction and boot flow were accepted on the configuration above.

## Acceptance and performance

Cold A1 / unlocked B1 / cold locked A2 verified the target gain while a second
physical card remained a locked control. Subsequent dual-card deployment passed
native checks, an ordinary warm reboot and a cold start. Details, retained
negative results and application-comparison limits are in the
[benchmark report](../../benchmarks/2026-10-26/README.md).

The optional [boot/SSH reminder](../../monitoring/README.md) reports failed or
unconfirmed evidence without doing another hardware transaction.
