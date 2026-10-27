[English](README.md) | [简体中文](README.zh-CN.md)

# GPU unlock: Supermicro dual RTX 4090 adaptation

This fork contains mochgolf's tested H13SSL-N port for two modified 48 GiB AD102 cards.
It keeps the upstream `gpu_unlock` module and AD102 payload unchanged.
The port adds a separate Bus Master Enable (BME) diagnostic, a pre-udev boot sequence, a boot/SSH reminder, and public test evidence.

| Document | Purpose |
|---|---|
| [Hardware port](ports/supermicro-h13ssl/README.md) | Tested hardware, build steps, boot sequence, and limits |
| [Boot/SSH reminder](monitoring/README.md) | Status checks and warning setup |
| [Local benchmark report](benchmarks/2026-10-26/README.md) | Controlled A/B/A results, MOSS, Qwen, and operator tests |
| [Operator probes](benchmarks/operators/README.md) | Synthetic workload tools and measurement limits |
| [Historical RTX 4090 report](rtx4090-register-report.md) | The separate upstream single-card experiment |

The controlled local BF16/FP32 result was **164.5 → 325.95 → 164.5 TFLOP/s** in A/B/A, or about 1.98×.
BF16 cuBLAS 8192³ improved by about 18.8%. The 4096³ case stayed almost unchanged.
Historical MOSS training throughput increased by about 11% with the same offload policy.

NUMA binding, logging, and other differences prevent an unlock-only attribution.
Recent Qwen C1 decoding stayed approximately unchanged, at 86–89 token/s for the tested input lengths.
The Triton comparison measures a separate software improvement.

The local system used H13SSL-N BIOS 3.5, kernel `7.0.0-34-generic`, and custom `nvidia-open-p2p/595.84`.
Each card had 48 GiB and a 450 W power limit.
This acceptance does not cover other boards, BIOS versions, stock 24 GiB cards, or stock 595.84.
Read the hardware port before you use its pinned diagnostics.

The public wrapper only stages files. It does not install or activate a boot image.
The root install targets below use the upstream packaging path.

## Separate upstream result: GPU unlock 1.0.0

The upstream module applies the SM speed-select override before the stock NVIDIA driver starts.
Its historical RTX 4090 experiment used one `10de:2684` AD102 card and one successful cold power-on.

| Mode | Before | After |
|---|---:|---:|
| FP16 → FP32 accumulate | 165.6 TF/s | 331.6 TF/s |
| BF16 → FP32 accumulate | 165.5 TF/s | 330.6 TF/s |

The override survived PCIe Function Level Reset (FLR), stock NVIDIA `615.78.08` initialization, and CUDA benchmarks.
INT8, `dp4a`, and scalar FP32 stayed near baseline.
The firmware run preceded the publication cleanup.
At that report's date, the cleaned module still needed an independent cold-boot repeat and application numerical validation.

The later local study uses different hardware and a custom driver. It is a separate acceptance result.
Read the [historical report](rtx4090-register-report.md) and [evidence guide](docs/evidence/rtx4090/README.md).

The AD102 payload and debug-booter analysis come from [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
The Linux integration derives from [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
The published payload is essential to the result.

## Supported targets and mechanism

RTX 4090 `10de:2684` automatically selects the AD102 assets.
The module retains the original GeForce/CMP GA102/GA104 device list and GA102 payload.
Upstream reported RTX 3090 success. This AD102 work does not revalidate every legacy board.

The module rejects other Ada IDs, professional RTX A-series cards, and data-centre parts.
Shared Ada firmware does not establish support for other cards.

The RTX 4090 path runs signed firmware and checks the payload marker and required permissions.
It writes SS0 `0x88888888` and SS1 `0x8`, then performs FLR before the NVIDIA driver binds.
It requires the expected effective speed-select readout before and after FLR.
This upstream path needs no NVIDIA driver patch or UEFI application.

The local 48 GiB port separately depends on its existing custom NVIDIA driver.
The payload uses instruction addresses from published decrypted debug-booter analysis.
The GPU authenticates and decrypts the production booter internally.

## Build and install the upstream package

Install the package and build dependencies for your distribution:

```sh
make install-arch   # makepkg -sif
make install-deb    # apt-get build-dep, dpkg-buildpackage, apt-get install
make install-rpm    # dnf builddep, rpmbuild, dnf install
```

`make arch`, `make deb`, and `make rpm` build packages without installation.
Packages use committed `HEAD`. Debian and RPM outputs go to `build/deb` and `build/rpm`.
Install matching kernel headers and a working DKMS toolchain.

Builds download pinned NVIDIA `610.43.03` inputs over HTTPS and check their SHA-256 hashes.
`make inputs` prepares the cache. `make firmware` generates assets from cached inputs. `make assets` does both.

The default cache is `$HOME/.cache/gpu-unlock`.
Use `CACHE=`, `INPUTS=`, and `ASSETS=` to change the paths.
For a clean-chroot Debian build, set `GPU_UNLOCK_INPUTS` to the input cache.
`dpkg-buildpackage` does not download inputs itself.

The `make dist` archive, Debian source package, and `.nosrc.rpm` exclude NVIDIA archives and generated firmware.
See the [firmware guide](firmware/README.md) for the input and asset layout.

## Enable the upstream boot path

The package puts the module and firmware in the initramfs, before NVIDIA binds.
The module stays inactive until the kernel command line selects targets:

```text
gpu_unlock.targets=0000:03:00.0
gpu_unlock.targets=0000:03:00.0,0000:04:00.0
gpu_unlock.targets=all
```

These addresses are examples. Use the full PCI names from `lspci -D`.
`all` selects every supported unbound card, including legacy GA102/GA104 targets.
Use an explicit address to select one card. Do not combine `all` with addresses.

The module logs invalid entries and ignores them.

The packages support these initramfs generators:

- **mkinitcpio:** `/etc/mkinitcpio.conf.d/zz-gpu-unlock.conf` adds `gpu_unlock` immediately before `nvidia` in `MODULES`.
  If NVIDIA is absent, it adds `gpu_unlock` last. Installation rebuilds the images.
  A custom `-c` configuration or preset `_config` bypasses drop-ins.
  In that configuration, manually put `gpu_unlock` before `nvidia` in `MODULES`.
- **initramfs-tools:** `/usr/share/initramfs-tools/modules.d/gpu-unlock.conf` supplies the integration.
- **dracut:** `/usr/lib/dracut/dracut.conf.d/gpu-unlock.conf` supplies the integration.

The package adds no `softdep nvidia pre:` rule.
Kmod uses only the first matching soft-dependency line. Another package can therefore cause a conflict.

**For the first attempt, power off the machine fully, then start it.**
The card must have no GPU-driver initialization since power-on.
A warm reboot does not guarantee this state.
The module skips bound, powered-down, or bus-mastering cards. It rejects firmware state that indicates earlier use.

Manual module loading after NVIDIA has bound cannot unlock the card.

Before a manual cold-card attempt, do not run `nvidia-smi`, CUDA, NVML, or `nvidia-modprobe`.
These tools can load NVIDIA by name. Ordinary modprobe blacklists do not block explicit named loads.
The packaged initramfs path avoids manual firmware staging and research parameters.

The upstream path removes the firmware framebuffer immediately before FLR.
The display stays blank until `nvidia-drm` takes control.
The historical single-card study did not validate display handoff or multiple cards.
The local dual-card acceptance used a separate ASPEED console.

## Check or disable the unlock

After boot, inspect the kernel log and PCI binding:

```sh
journalctl -k -b | grep gpu_unlock
lspci -nnk -s 0000:03:00.0  # replace the example address
```

A loaded module or successful `modprobe` return does not prove success.
For each selected card, require `gpu_unlock: unlocked` and the payload, selector, and post-FLR checks.
The historical report also provides independent register and performance confirmation.
The optional sampler is in `diagnostics/peek`. The CUDA instruction benchmark is in `diagnostics/bench`.

While the firmware transaction runs, do not load another BAR0 sampler.

If firmware does not stop and the module retains DMA buffers, power off before another attempt.
Firmware can still use those buffers. Do not force-unload the module in this state.

To disable future attempts, remove `gpu_unlock.targets=` from the kernel command line.
For one boot, remove it in the bootloader editor.
Package removal deletes the module and initramfs integration.
Power off to obtain a fresh hardware state.

## Development, attribution, and licenses

`make test` runs host tests without GPU access.
With generated firmware, it also tests complete transactions against mocked hardware.
`make LLVM=1 -C kernel/gpu_unlock` builds with LLVM and the running kernel's headers.

The Linux module and packaging derive from [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
The AD102 four-PLM payload uses [TOTORONG's generator and debug-booter analysis](https://huggingface.co/TOTORONG/AD103_win_unlocker).
The GA102 V67 chain derives from [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock).
Earlier CMP work, NVIDIA loader code, Nouveau, and [envytools](https://github.com/envytools/envytools) also informed this work.

The module, packaging, and payload integration use GPL-2.0-only.
NVIDIA firmware keeps its own license terms.
See [firmware/NOTICE.md](firmware/NOTICE.md) and [licenses/](licenses/) for provenance and preserved notices.
