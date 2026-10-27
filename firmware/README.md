[English](README.md) | [简体中文](README.zh-CN.md)

# Pinned 610.43.03 firmware

## Download and verify inputs

`make inputs` runs `fetch_artifacts.py`.
It downloads the NVIDIA open kernel-module source archive and the exact CachyOS `nvidia-utils` package in `artifacts-610.43.03.json`.
Downloads use HTTPS. The script checks SHA-256 before adding files to the cache.

It checks cached files again on every run.
It does not execute or install downloaded files.

## Generate assets

`make firmware` generates nine files for the module's `gpu-unlock/610.43.03/` firmware path:

- `generate_v67.py` extracts `gsp_ga10x.bin` and the NVIDIA license from the package.
  It also generates `v67-ga102-610.43.03.bin` and `v67-ad102-610.43.03-four-plm.bin`.
  Each payload is 64,000 bytes.
- `extract_boot_assets.py` extracts `booter_load_ga102.bin`, `gsp_boot_ga102.bin`, and `gsp_boot_desc_ga102.bin` from the source archive.
  It also extracts the three AD102 equivalents.

Both scripts check every input and output against its pinned SHA-256 before writing outputs.
Extraction requires Python 3 and the `zstd` command.

## AD102 payload and runtime checks

The manifest pins the AD102 payload to SHA-256 `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb`.
The payload reproduces the published four-write chain: WPR_CFG, FBPA, WPR, then FEAT_OVR_PLM.
The first value is `0xfffff0ff`. The other three values are `0xffffffff`.

The payload then requests mailbox0 marker `0x67b00001` and cleanup.
Before applying selectors, runtime checks require the marker, required permission readbacks, and SEC2 HALT.

The [historical RTX 4090 report](../rtx4090-register-report.md) records one card's production execution, FLR/stock-driver persistence, and approximately doubled FP32-accumulate Tensor throughput.
The payload and plaintext-derived instruction addresses come from [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
The [local dual-card report](../benchmarks/2026-10-26/README.md) covers a separate configuration and acceptance.

## File offsets and DMEM addresses

The manifest keeps payload offsets separate from DMEM addresses.
With modeled copy base `0x600`, payload canary offset `0xf94c` maps to DMEM `0xff4c`.
The return slot at payload offset `0xf950` maps to DMEM `0xff50`.
The AD102 FEAT_OVR_PLM address word is at payload offset `0xf9cc`. GA102 uses `0xf960`.

See [NOTICE.md](NOTICE.md) for provenance and licensing.
