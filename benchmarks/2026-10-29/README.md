[English](README.md) | [简体中文](README.zh-CN.md)

# FP8 instruction throughput: 2026-10-29

**With the existing unlock active, FP8 input with FP32 accumulation runs at almost the same rate as FP16 accumulation.**
Both E4M3 and E5M2 show this behavior on both tested cards.
No additional FP8 patch was needed.
This follow-up used no local locked arm. It does not establish a measured local before/after speedup.

## Configuration and method

The system is the same [H13SSL-N dual-card installation](../../ports/supermicro-h13ssl/README.md).
It uses modified 48 GiB AD102 cards, BIOS 3.5, kernel `7.0.0-34-generic`, and custom `nvidia-open-p2p/595.84`.
Both cards retained their 450 W limit.
GPU0 is `0000:01:00.0`. GPU1 is `0000:41:00.0`.
The test ran on October 29 in America/Los_Angeles, from 01:41:42 to 01:42:25 UTC on October 30.

The [CUDA source](../../diagnostics/bench/fp8_mma_bench.cu) uses dense, register-resident MMA loops.
Each multiply-accumulate counts as two operations. No sparsity multiplier applies.
FP8 uses `mma.m16n8k32`; FP16/BF16 controls use `mma.m16n8k16`.
The grid has 1,056 blocks and 256 threads per block.
The primary test uses eight independent accumulator chains, 20,000 iterations, and 21 samples per mode per GPU.
Mode order rotates and reverses between repetitions. Warm-up occurs before sampling.

Additional runs use four and 16 chains, with seven samples per mode, and 40,000 iterations with eight chains and 21 samples.
All eight runs and all 784 event samples remain in [samples.json](samples.json).
Samples are correlated. No significance test applies.

## Primary results

Values are medians in dense TFLOP/s. Each cell contains 21 measurements.

| Input / accumulation | GPU0 | GPU1 |
|---|---:|---:|
| E4M3 / FP32 | 648.75 | 656.30 |
| E5M2 / FP32 | 648.67 | 656.28 |
| E4M3 / FP16 | 649.50 | 657.01 |
| E5M2 / FP16 | 649.52 | 657.03 |
| BF16 / FP32 | 325.79 | 329.64 |
| FP16 / FP32 | 325.82 | 329.62 |
| FP16 / FP16 | 325.80 | 329.55 |

FP8/FP32 medians are about 99.9% of their corresponding FP8/FP16 medians.
The 40,000-iteration FP8/FP32 medians remain about 649 TFLOP/s on GPU0 and 655 TFLOP/s on GPU1.
Four chains give slightly lower FP8 rates. Eight and 16 chains give similar rates.
See [results.json](results.json) for every mode, run, range, clock estimate, and ratio.

## Network reference and interpretation

The [NVIDIA Ada whitepaper V2.02](https://images.nvidia.com/aem-dam/Solutions/geforce/ada/nvidia-ada-gpu-architecture.pdf#page=30) gives these RTX 4090 stock peaks:

| FP8 input mode | Dense peak at the specified 2520 MHz boost clock |
|---|---:|
| FP32 accumulation | 330.3 TFLOP/s |
| FP16 accumulation | 660.6 TFLOP/s |

The current FP8/FP32 measurements are about 1.96–1.99× the official FP32-accumulation peak.
That ratio compares a measurement with a specification. It is not a local A/B speedup.
The cards ran at different clocks from the specification.
Primary per-block clock estimates are about 2710 MHz on GPU0 and 2744 MHz on GPU1.

After clock normalization, FP8/FP32 remains about 1.83× the stock theoretical peak at the same clock.
The benchmark reaches about 91% of the unrestricted theoretical rate.
This estimate includes finite-grid, instruction, and timing overhead. It is not a frequency-locked experiment.
The almost equal FP32/FP16 accumulation rates provide the more direct internal comparison.
Together, the results support FP8/FP32 operation in the unrestricted throughput class under the existing unlock.
They do not independently map FP8 to a particular speed-select field.

## Instruction and numerical checks

CUDA 12.8.93 compiled the source with `-O3 -std=c++17 -arch=sm_89 -lineinfo -Xptxas=-v`.
SASS contains `QMMA.16832.F32.E4M3.E4M3` and `QMMA.16832.F32.E5M2.E5M2`, plus the corresponding FP16-accumulation instructions.
The controls use native HMMA instructions. All compiled kernels have zero spill loads and stores.
The test does not convert FP8 inputs to FP16 inside the timed loop.
NVIDIA documents FP8 MMA support for `sm_89` in the [PTX ISA](https://docs.nvidia.com/cuda/archive/12.8.0/parallel-thread-execution/index.html).

All inputs are the exact, nonzero value `2^-6`.
Short tests check every lane, chain, and accumulator element after 1, 2, and 32 iterations.
All 168 checks passed, covering 193,536 output elements with zero absolute error.
All timed output checksums were finite.
Long FP16 accumulation eventually loses these small increments without overflow.
The long loop measures throughput; it does not validate long numerical accumulation.
Uniform-input checks do not qualify arbitrary FP8 inputs, quantization scales, GEMM, backward passes, or training.

## Service coexistence and postconditions

The local controller ran one GPU worker at a time.
It required idle request metrics and allowed only the two admitted Qwen GPU processes plus its own worker.
It checked traffic, process identity, power limits, temperature, and boot identity throughout the campaign.
Any failed check would stop only its own child.
Qwen stayed loaded; all observed running/queued-request metrics were zero.

The 47 active-phase telemetry samples per GPU showed no power-cap or hardware thermal-slowdown flag.
Sampled peak power was 192.88/206.96 W; maximum temperature was 46/50 °C for GPU0/GPU1.
These values describe this uniform register workload, not arbitrary model power demand.
The controller observed the same service GPU PIDs and allocations after testing.
Total used memory returned to baseline. Unlock status remained confirmed on the same boot.
The readable kernel journal contained no new Xid or GPU drop-off message during the test window.
The test changed no boot entry, firmware, module, driver, clock setting, or power limit, and restarted no service.

## Reproduce the instruction test

Use an idle tested GPU with sufficient free VRAM. Isolate service traffic before running.
This public binary does not include the private service-traffic controller.
The program accepts positional arguments: iterations, repetitions, and accumulator chains (`4`, `8`, or `16`).
It requires an `sm_89` GPU with 128 SMs.
Use a fresh output directory:

```sh
mkdir -p build
mkdir build/fp8-run
nvcc -O3 -std=c++17 -arch=sm_89 -lineinfo -Xptxas=-v \
  -o build/fp8-run/fp8_mma_bench diagnostics/bench/fp8_mma_bench.cu
cuobjdump --dump-sass build/fp8-run/fp8_mma_bench > build/fp8-run/instructions.sass
CUDA_VISIBLE_DEVICES=0 build/fp8-run/fp8_mma_bench 20000 21 8 > build/fp8-run/g0-primary.jsonl
CUDA_VISIBLE_DEVICES=1 build/fp8-run/fp8_mma_bench 20000 21 8 > build/fp8-run/g1-primary.jsonl
```

For the secondary runs, use `(20000, 7, 4)`, `(20000, 7, 16)`, and `(40000, 21, 8)` on each card.
Keep each run in a separate file.
Source/binary hashes and the SASS audit are in `results.json`; [SHA256SUMS](SHA256SUMS) covers the public source and evidence files.
Host-only CI does not execute this CUDA test.

These results measure instruction throughput. They do not predict a twofold MOSS or Qwen application gain.
