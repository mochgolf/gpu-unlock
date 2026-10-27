[English](README.md) | [简体中文](README.zh-CN.md)

# Dual RTX 4090: validation and performance, 2026-10-26

**Controlled BF16 Tensor throughput with FP32 accumulation increased by about 1.98×.**
Application gains were smaller. The historical MOSS comparison showed about 11% higher training throughput, with known confounders.
Recent Qwen single-request decoding stayed approximately unchanged.

The independent Triton comparison measures software implementation differences, not unlock speedup.

## Configuration and method

The system used Supermicro H13SSL-N BIOS 3.5, an ASPEED console, and four NUMA nodes.
It had two modified 48 GiB AD102 RTX 4090 cards, `10de:2684`, reporting 49,140 MiB each.
The kernel was `7.0.0-34-generic`. The custom `nvidia-open-p2p/595.84` driver supported 48 GiB and P2P.

Each card retained its default 450 W limit. The tests used no overclock.
This acceptance does not cover stock drivers or stock 24 GiB boards.
MMA used nvcc 12.8.93 with `-O3 -arch=sm_89`.

Operator tests used PyTorch 2.14.1/cu130 and Triton 3.8.0.

The port kept the upstream AD102 payload and unlock module unchanged.
It added separate pre-driver BME normalization and a verified pre-udev dual-card sequence.
The diagnostic pins the board, BIOS, capacity, and slots.

The controlled sequence was cold locked A1, target-unlocked B1, then cold locked A2.
A second card stayed locked as the control.
The evidence retains primary and matched-context samples, clock-ramp variation, negative or small GEMM results, and failed admission attempts.
The tables below use the matched-context supplement: 30 repetitions per MMA mode per phase and 10 per GEMM shape per phase.

Shared binaries and libraries were pinned. These results cover one machine, not a fleet.

## Controlled A/B/A Tensor results

| Target instruction | A1 locked | B1 unlocked | A2 locked | B1/A1 |
|---|---:|---:|---:|---:|
| f16/f16 (TFLOP/s) | 329.00 | 329.10 | 329.00 | 1.0003x |
| f16/f32 (TFLOP/s) | 164.60 | 328.90 | 164.60 | 1.9982x |
| bf16/f32 (TFLOP/s) | 164.50 | 325.95 | 164.50 | 1.9815x |
| s8/s32 (TOP/s) | 655.80 | 655.80 | 657.60 | 1.0000x |
| dp4a (TOP/s) | 163.10 | 163.15 | 163.20 | 1.0003x |
| ffma (TFLOP/s) | 78.40 | 78.40 | 78.60 | 1.0000x |

The locked control card stayed near 162.9 TFLOP/s for BF16 in all three phases.
Scalar FP32 and integer controls did not show a corresponding 2× increase.
See [individual samples and control-normalized comparisons](ab-a-matched.json).

## Controlled cuBLAS GEMM results

| Target dtype / MxNxK | A1 TFLOP/s | B1 TFLOP/s | A2 TFLOP/s | B1/A1 |
|---|---:|---:|---:|---:|
| bf16 / 4096-4096-4096 | 144.48 | 144.61 | 144.40 | 1.0009x |
| bf16 / 8192-8192-8192 | 159.75 | 189.77 | 159.76 | 1.1879x |
| bf16 / 256-512-16384 | 113.03 | 131.59 | 113.26 | 1.1642x |
| fp16 / 4096-4096-4096 | 152.03 | 210.21 | 152.16 | 1.3827x |
| fp16 / 8192-8192-8192 | 160.67 | 181.70 | 160.76 | 1.1309x |
| fp16 / 256-512-16384 | 119.52 | 110.38 | 110.38 | 0.9235x |

BF16 4096³ stayed almost unchanged. BF16 8192³ improved by about 18.8%.
The small FP16 case also differed between locked A1 and locked A2.
Its decrease from the first baseline therefore does not isolate an unlock effect.

Peak MMA gain does not predict every library kernel's gain.

All retained full-output GEMM comparisons in this supplement were bitwise equal.
Finite checks and independent sampled error budgets also passed.
These checks do not prove identical results for every future model or input.
Each primary phase passed 59 configured cases, including about 30 minutes of stability work.

The evidence retains the original A0 failure with a legacy 28 GiB P2P mapping.
Later VMM P2P success does not erase that failure.
The accepted large-memory workload requires this custom driver's tested VMM path.

## Native deployment acceptance

Both GPUs later became enabled through a persistent GRUB default.
The unchanged safe-A entry remained first in the visible menu.
Acceptance covered an initial dual cold boot, an ordinary warm reboot, and a cold start with the persistent default.
The warm reboot met the cold-state checks and completed a full unlock on this machine.

The non-cold, pre-action stock-driver fallback passed chroot tests only.
Any failure after hardware action still stops the flow.
These results do not establish universal warm-boot recovery.

Final native acceptance passed 33 cases, including numerical checks and 28 GiB allocation in two memory modes.
It also covered bidirectional 1 MiB VMM P2P and MMA checks.
Four independent single-GPU MOSS jobs completed 800 optimizer steps with zero nonfinite steps.
Eight inference images formed four cross-GPU pairs. Each pair was bitwise identical.

These are system-load and numerical checks. They do not establish model quality.
Qwen completed 460 service-load requests with zero observed errors.
That mixed workload achieved 205.96 output-token/s with about 79.8% input-cache hits.

It cannot serve as a steady decode-only batch-throughput comparison.

## Historical MOSS comparison

This comparison uses total tokens divided by total interval time.
It does not compare historical 10-step logging medians with current 1-step medians.
Matched steps 51–140 contain 90 steps, 237 samples, and 948,960 tokens.
Both runs used the same A data, cache, model, BF16, rank16, seed, and original offload policy.

The interval excludes warm-up, saving, and validation. All nine matched 10-step windows improved.

| Training policy | Historical token/s | Current token/s | Throughput change |
|---|---:|---:|---:|
| Same original offload | 2753.94 | 3057.85 | +11.04% |
| Current resident policy vs old offload | 2753.94 | 3232.95 | +17.39% |

The current resident policy adds about 5.73% over the current original-offload policy.
The current launcher also adds explicit NUMA binding.
Logging, boot, date, and cache conditions differ. The 11% gain cannot all be attributed to the unlock.

Historical inference averaged 42.90 s/image. Current inference averaged 38.13–38.66 s/image.
The historical test used 32 balanced-profile images; the current test used four speed-profile images per card.
Prompts and text lengths also changed. This comparison cannot isolate unlock gain.

See [history measurements and denominators](historical-applications.json).

## Qwen single-request speed

The test used TP2, concurrency 1, temperature 0, thinking disabled, and no prefix-cache hits.
Two warm-ups preceded 17 measured requests. Each request produced 512 output tokens.
Decode speed is `(output_tokens-1)/(last_text_time-first_text_time)`.

| Input tokens | Requests | Decode token/s median | TTFT median |
|---|---:|---:|---:|
| 113 | 7 | 88.51 | 0.312s |
| 2220 | 5 | 87.24 | 0.597s |
| 8840 | 5 | 86.45 | 1.477s |

See [request-group measurements](qwen-single.json).
Recent same-profile logs before unlock already showed about 87 token/s.
Matched log bins changed from 87.28 to 88.56 (+1.47%) and from 86.42 to 87.32 (+1.04%).
These are correlated windows with different prompts. They are not independent paired requests or a significance test.

Older 73–81 token/s records used other software stacks or contexts. They are not a valid unlock-only baseline.
Overall C1 speed stayed approximately unchanged.

## Targeted MOSS operator tests

The paired test used identical BF16 inputs, GPU0, and 450 W.
Seven alternating sweeps produced 35 event measurements per implementation.
GPU1 reproduced the direction of improvement.

| MOSS GEMM (M,N,K) | cuBLAS us | cuBLASLt us | Triton128 us | Triton throughput gain |
|---|---:|---:|---:|---:|
| qkv (4160, 3072, 3072) | 425.98 | 368.38 | 331.65 | +28.44% |
| up (4160, 16384, 3072) | 2284.03 | 2318.34 | 1687.42 | +35.36% |
| down (4160, 3072, 8192) | 1172.22 | 1180.53 | 904.18 | +29.64% |
| dgrad (4160, 3072, 16384) | 2425.98 | 2429.80 | 1929.09 | +25.76% |

FFN-up Tensor activity increased from 58.36% to 90.59%.
A 64×64 Triton variant was slower.
The result depends on shape, tile, and implementation. It does not establish a general Triton advantage.

Disabling BF16 reduced-precision reduction changed ordinary cuBLAS QKV/up times by only about 0.36%/0.08%.
Each paired implementation passed 16 sampled CPU-FP64 forward-error bounds.
The candidate has not replaced a production layer or passed full backward/model qualification.
These improvements are separate from unlock gains.

`dgrad` uses continuous synthetic weights with the backward GEMM dimensions. It does not cover all production transpose strides.

## Power, memory, and software limits

A reversible 450 → 300 → 450 W test increased large MOSS GEMM latency by about 28–35% at 300 W.
The faster Triton FFN latency increased by about 52%.
This establishes power sensitivity. It does not quantify power's share of the missing unlock gain.

Real MOSS offload training showed power-cap flags in 136/148 and 140/148 samples.
Resident training showed them in 133/138 and 136/138 samples.
No sampled flag indicated hardware thermal throttling.
SiTU and normalization were insensitive to 300 W.

Their counter probes reached 94.0% and 82.78% of sustained DRAM throughput.

Qwen LM-head GEMV reached 978.8 GB/s, 97.19% sustained DRAM throughput, and 0% Tensor activity.
GDN-input GEMV reached 893.1 GB/s. HC and both Marlin kernels showed about 5% Tensor activity.
Batch-1 workloads have low arithmetic intensity, small per-expert batches, dequantization costs, and synchronization/launch costs.

LM head, HC, batch-1 MoE, and GDN-recurrent event medians changed by under 0.4% between 300 W and restored 450 W.
GDN-input hot-cache latency changed by 8.84%. After eviction, it changed by about 1.76%.
Thus, these results do not show that every Qwen kernel is insensitive to power.

CPU scheduling, TP communication, KV access, and indexing remain possible service limits.
This study did not re-profile their current critical-path fractions.

Qwen counter collection changed from kernel replay to application replay with explicit 96 MiB eviction.
Counters help identify limits. Profiler durations do not replace normal event timings or add up to whole-model latency.
See [individual operator samples and counters](operators.json).

Nsight produced 54 driver assertions for `pSmIssueThrottleCtrl != NULL`, only during profiling.
The 595.84 source returns `NV_ERR_NOT_SUPPORTED` in a getter.
Ordinary timing and power-test windows had no such assertions. No Xid was observed.

This profiler/driver compatibility issue is not a proven cause of routine training or decoding limits.
After profiling, GPU0 retained a 124 MiB used-memory reporting difference.
Application owners and their reported allocations stayed unchanged.
The production service was not restarted to clear the difference.

## Sources, provenance, and limits

- Base: [elias-gaeros/gpu-unlock @4ec490d](https://github.com/elias-gaeros/gpu-unlock/tree/4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc).
- Loader: [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
- AD102 payload analysis: [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
  This port does not claim discovery of the chain.
- Runtime pins: SGLang `baa9befa381511cd4d56f83980951e5a45fffc6d`; QSA `d9c2339771d9bbafc771ec29f3d471aaeca8a1bf`.
  MOSS used installed kohakumoss 0.1.0.
- References: [Nsight guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html),
  [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/), and [PyTorch BF16 reduction settings](https://docs.pytorch.org/docs/main/notes/cuda.html).

Public evidence retains numerical samples, counters, controlled comparisons, and limited transaction proof.
It excludes host/user names, GPU/filesystem UUIDs, management addresses, credentials, private project paths, model weights, and complete machine logs.
Original local evidence stays unchanged.
Publication uses filtered logs and a parameterized persistence template.

It excludes complete local initrd images and controllers that contain credentials.

## Publication checks

The assembled fork passed 12 host tests with no skips on the measured host.
These included 21 BME fault cases, 42 fake-PCI checks, and 19 reminder tests.
Both kernel modules and the static collector rebuilt for `7.0.0-34-generic`.
The staging wrapper checked pinned assets and produced an overlay without installation or hardware action.

BTF generation was skipped because `vmlinux` was unavailable.
The compiler-name warning referred to the same GCC 13.3.0 version.
Checks recomputed individual MMA medians, all nine matched MOSS intervals, and all 19 Qwen request measurements from public data.
See the [validation receipt](publication-validation.json).

Publication did not reboot, execute firmware, or restart a production service.
Rebuilt artifacts did not replace deployed artifacts.
