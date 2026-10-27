# Dual RTX 4090 validation and performance — 2026-10-26

**The controlled result is about 1.98x BF16 Tensor throughput with FP32
accumulation. Real application gains are much smaller.** The 11% MOSS training
comparison is observational history with known confounders. Recent Qwen
single-request decoding is approximately unchanged. An independent Triton
kernel comparison is a separate software result, not unlock speedup.

## Configuration and method

Supermicro H13SSL-N, BIOS3.5; two modified 48GiB AD102 RTX4090 (`10de:2684`,
49,140MiB each), ASPEED console, four NUMA nodes. Kernel7.0.0-34-generic,
locally patched nvidia-open-p2p/595.84 with 48GiB and P2P support, 450W/card.
This is not a stock-driver or stock-24GiB-board qualification. MMA was compiled
with nvcc12.8.93, `-O3 -arch=sm_89`; PyTorch operator work used2.14.1/cu130 and
Triton3.8.0. No overclock or higher-than-default power limit was used.

The port did not change the upstream AD102 payload or unlock module. It added
separate pre-driver BME normalization and a verified pre-udev dual-card boot
flow. The diagnostic is pinned to the tested board, BIOS, capacity and slots.

The controlled sequence was cold locked A1, target-unlocked B1, cold locked A2;
a second card stayed locked as control. We retained all primary and matched-
context samples, including clock-ramp variation, negative/small GEMM results
and failed admission attempts. The table below is the matched-context supplement:
30 repetitions per MMA mode/arm and10 per GEMM shape/arm. Shared binaries and
libraries were pinned. This is one-machine evidence, not fleet qualification.

## Controlled A/B/A Tensor results

| Target instruction | A1 locked | B1 unlocked | A2 locked | B1/A1 |
|---|---:|---:|---:|---:|
| f16/f16 (TFLOP/s) | 329.00 | 329.10 | 329.00 | 1.0003x |
| f16/f32 (TFLOP/s) | 164.60 | 328.90 | 164.60 | 1.9982x |
| bf16/f32 (TFLOP/s) | 164.50 | 325.95 | 164.50 | 1.9815x |
| s8/s32 (TOP/s) | 655.80 | 655.80 | 657.60 | 1.0000x |
| dp4a (TOP/s) | 163.10 | 163.15 | 163.20 | 1.0003x |
| ffma (TFLOP/s) | 78.40 | 78.40 | 78.60 | 1.0000x |

The locked control card's BF16 result stayed at about162.9TFLOP/s across all
three arms. Scalar FP32 and integer controls did not show a corresponding2x
increase. [All individual samples and control-normalized comparisons](ab-a-matched.json).

## Controlled cuBLAS GEMM results

| Target dtype / MxNxK | A1 TFLOP/s | B1 TFLOP/s | A2 TFLOP/s | B1/A1 |
|---|---:|---:|---:|---:|
| bf16 / 4096-4096-4096 | 144.48 | 144.61 | 144.40 | 1.0009x |
| bf16 / 8192-8192-8192 | 159.75 | 189.77 | 159.76 | 1.1879x |
| bf16 / 256-512-16384 | 113.03 | 131.59 | 113.26 | 1.1642x |
| fp16 / 4096-4096-4096 | 152.03 | 210.21 | 152.16 | 1.3827x |
| fp16 / 8192-8192-8192 | 160.67 | 181.70 | 160.76 | 1.1309x |
| fp16 / 256-512-16384 | 119.52 | 110.38 | 110.38 | 0.9235x |

BF16 4096-cubed barely changed;8192-cubed improved about18.8%. The small FP16
case changed between locked A1 and locked A2 too, so its first-baseline drop is
not a clean unlock effect. Do not generalize peak MMA improvement to arbitrary
library kernels. All retained full-output GEMM comparisons in this supplement
were bitwise equal, with finite checks and independent sampled error budgets.
This does not prove all future models or inputs are numerically identical.

Primary A1/B1/A2 each passed59 configured cases, including approximately30min
of stability work per arm. The original A0 legacy28GiB P2P mapping failure was
retained; it was not erased by the later VMM P2P success. This custom driver
needs its proven VMM path for the accepted large-memory workload.

## Native deployment acceptance

Both GPUs were subsequently enabled as a persistent GRUB default while the
unchanged original safe-A entry remained first in the visible menu. Initial
dual cold boot, a persistent-default ordinary warm reboot, and a persistent-
default cold start were tested. Warm reboot on this machine satisfied the cold
predicates and completed a full unlock. The alternative pre-action stock-driver
fallback is only chroot-tested for a non-cold failure; any post-action failure
still stops. It must not be advertised as universally fail-safe warm-boot support.

Final native acceptance included33 cases: numerical checks,28GiB allocation in
two memory modes, bidirectional1MiB VMM P2P and MMA checks. Four independent
single-GPU MOSS jobs completed800 optimizer steps with zero nonfinite steps;
8 inference images were generated, with4 cross-GPU output pairs identical.
These are system-load and numerical checks, not a new model-quality result.
Qwen sustained service load completed460 requests with zero observed errors.
That mixed-workload205.96output-token/s result had about79.8% input-cache hits;
it is not comparable to a steady decode-only batch-throughput number.

## Historical MOSS application comparison (not a new causal A/B)

Use total tokens/total interval time, not historical10-step logging medians vs
current1-step medians. Steps51–140 match exactly:90 steps,237 samples,
948,960tokens, same A data/cache/model/BF16/rank16/seed and original offload
policy, excluding warm-up/save/validation. All9 paired10-step windows improved.

| Training policy | Historical token/s | Current token/s | Throughput change |
|---|---:|---:|---:|
| Same original offload | 2753.94 | 3057.85 | +11.04% |
| Current resident policy vs old offload | 2753.94 | 3232.95 | +17.39% |

Residency itself adds about5.73% over the current original-offload policy.
Explicit NUMA binding was added to the current launcher, logging changed and
boot/date/cache state differ: the11% is not all attributable to the unlock.
Image generation averaged42.90s/image historically vs38.13–38.66s currently;
that32-image balanced vs4-image/card speed-profile comparison also changed
prompts/text lengths and cannot isolate unlock gain.
[Selected history measurements and denominators](historical-applications.json).

## Qwen single-request service speed

TP2, concurrency1, no prefix-cache hits, temperature0, thinking disabled;
2 warm-ups then17 measured requests, each producing512 output tokens.
Decode speed is `(output_tokens-1)/(last_text_time-first_text_time)`.

| Input tokens | Requests | Decode token/s median | TTFT median |
|---|---:|---:|---:|
| 113 | 7 | 88.51 | 0.312s |
| 2220 | 5 | 87.24 | 0.597s |
| 8840 | 5 | 86.45 | 1.477s |

[Current request-group measurements](qwen-single.json). Before unlock, recent
same-profile service logs already showed about87token/s. Matched single-request
log bins showed87.28→88.56 (+1.47%) and86.42→87.32 (+1.04%). These are correlated
log windows with different prompts, not independent paired requests or a
significance result. Older73–81token/s records used older stacks/contexts and
are not a valid unlock-only baseline. Overall C1 speed is approximately flat.

## Targeted operator findings

Identical BF16 inputs,450W, GPU0,7 alternating sweeps with35 event measurements
per implementation. GPU1 reproduced the direction of the improvement:

| MOSS GEMM (M,N,K) | cuBLAS us | cuBLASLt us | Triton128 us | Triton throughput gain |
|---|---:|---:|---:|---:|
| qkv (4160, 3072, 3072) | 425.98 | 368.38 | 331.65 | +28.44% |
| up (4160, 16384, 3072) | 2284.03 | 2318.34 | 1687.42 | +35.36% |
| down (4160, 3072, 8192) | 1172.22 | 1180.53 | 904.18 | +29.64% |
| dgrad (4160, 3072, 16384) | 2425.98 | 2429.80 | 1929.09 | +25.76% |

The FFN-up Tensor activity counter rose from58.36% to90.59%; a64x64 Triton
variant was slower, so this is a shape/tile/implementation result, not a generic
Triton advantage. Closing BF16 reduced-precision reduction changed the ordinary
cuBLAS QKV/up times by only about0.36%/0.08%. Each paired implementation passed
16 sampled CPU-FP64 forward-error bounds. The candidate has not replaced a
production layer or passed full backward/model qualification. Its improvements
are not unlock gains. `dgrad` reproduces dimensions with continuous synthetic
weights, not all production transpose strides.

A reversible450→300→450W test increased large MOSS GEMM latency by roughly
28–35% at300W; the faster Triton FFN increased about52%. This demonstrates
power sensitivity without proving what fraction of lost unlock speed is power.
Real MOSS training power-cap flags were frequent (136/148 and140/148 original-
offload samples;133/138 and136/138 resident samples). No hardware thermal-
throttling flag was sampled. SiTU and normalization were insensitive to300W
and approached94.0%/82.78% of sustained DRAM throughput in the counter probe.

Qwen LM-head GEMV measured978.8GB/s,97.19% sustained DRAM throughput and0%
Tensor activity. GDN-input GEMV was893.1GB/s; HC and the two Marlin kernels had
about5% Tensor activity. B1 workloads have low arithmetic intensity, tiny per-
expert batches, dequantization and synchronization/launch costs. LM head/HC/
B1-MoE/GDN-recurrent ordinary event medians changed by under0.4% between300W
and restored450W. GDN-input hot-cache latency did change8.84%, about1.76%
after eviction, so this is not a claim that all Qwen kernels ignore power.
CPU scheduling/TP communication/KV/index costs remain possible full-service
limits; their current critical-path fractions were not re-profiled here.

Qwen counter collection was corrected from kernel replay to application replay
with explicit96MiB eviction. Hardware counters are attribution evidence;
profiler durations are not substituted for normal event timing or summed into
whole-model latency. [Individual operator samples and counters](operators.json).

Nsight produced54 driver `pSmIssueThrottleCtrl != NULL` query assertions only
during profiling. The595.84 source returns `NV_ERR_NOT_SUPPORTED` in a getter;
ordinary timing and power-test windows did not have these assertions, and no
Xid was observed. This is a retained profiler/driver compatibility issue, not
proven as a cause of daily training/decode slowness. GPU0 also retained a124MiB
used-memory reporting difference after profiling while application owners and
their reported allocations were unchanged; the production service was not
restarted merely to clear that residual.

## Sources, provenance and limits

- Fork base: [elias-gaeros/gpu-unlock @4ec490d](https://github.com/elias-gaeros/gpu-unlock/tree/4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc).
- Original loader: [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
- Published AD102 payload analysis: [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker). The port does not claim discovery of the chain.
- Runtime source pins: SGLang `baa9befa381511cd4d56f83980951e5a45fffc6d`, QSA plugin `d9c2339771d9bbafc771ec29f3d471aaeca8a1bf`; MOSS used installed kohakumoss0.1.0.
- [Nsight profiling guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html), [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/), [PyTorch BF16 reduction settings](https://docs.pytorch.org/docs/main/notes/cuda.html).

Public evidence retains numeric samples, counter values, controlled comparisons
and limited transaction proof. Host/user names, GPU/filesystem UUIDs, management
network addresses, credentials, private project paths, model weights and whole
machine logs are excluded. Original local evidence remains unchanged. Source
publication uses filtered logs and a parameterized persistence template;
full local initrd images and credential-bearing controllers are not distributed.
