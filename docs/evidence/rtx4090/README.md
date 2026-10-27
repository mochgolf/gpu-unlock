[English](README.md) | [简体中文](README.zh-CN.md)

# Historical RTX 4090 evidence excerpts

These files support the [2026-10-23 single-card report](../../../rtx4090-register-report.md).
That experiment used one RTX 4090 and one successful cold power-on.
The firmware run preceded publication cleanup.
At that report's date, the cleaned module still needed an independent hardware repeat.

The later [local dual-card study](../../../benchmarks/2026-10-26/README.md) uses a different configuration.
It does not retroactively repeat the historical stock-driver experiment.

| File | Contents |
|---|---|
| [baseline.txt](baseline.txt) | Original benchmark stdout, 20,000 iterations, three repetitions per mode |
| [unlocked-20000.txt](unlocked-20000.txt) | Original unlocked benchmark stdout, 20,000 iterations, three repetitions per mode |
| [unlocked-40000.txt](unlocked-40000.txt) | Original unlocked repeat stdout, 40,000 iterations, three repetitions per mode |
| [registers.txt](registers.txt) | Selected cold, firmware, payload, selector, FLR, independent post-unload, post-driver and post-benchmark messages |
| [telemetry-summary.json](telemetry-summary.json) | Summary of 100 ms telemetry samples across the two unlocked invocations |
| [SHA256SUMS](SHA256SUMS) | Checksums for the evidence files above |

## What the excerpts preserve

The benchmark text is unchanged. Its `TF/s` label includes integer rates, which the report labels `TOP/s`.
The benchmark counts two operations per multiply-accumulate and applies no sparsity multiplier.
The baseline preceded the successful unlock's cold power-on.

Kernels, launch shape, timing method, and build flags stayed the same before and after unlock.
Publication cleanup only clarified benchmark comments.

Register excerpts keep the original register values and message content.
They remove wall-clock timestamps, PCI location prefixes, and host-assigned BAR0 address/length metadata.
Section labels identify the sampling stages.
The telemetry summary removes wall-clock start/end fields.

It records 32 total samples and ranges/means for the 26 active samples.
The power range includes entry into load. It does not measure per-kernel peak power.
These files are selected excerpts, not a complete machine-log archive.

## Verify the files

From this directory, run:

```sh
sha256sum -c SHA256SUMS
```

The AD102 payload comes from [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
The Linux loader derives from [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
See the report and [firmware notice](../../../firmware/NOTICE.md) for provenance and licensing.
