[English](README.md) | [简体中文](README.zh-CN.md)

# Synthetic operator probes for MOSS and Qwen

`worker.py` measures representative operator shapes from both projects.
MOSS cases cover BF16 projection, attention, LoRA, SiTU, and normalization.
Qwen cases cover GEMV, HC, W4A16 MoE, and GDN.
`paired_gemm.py` alternates cuBLAS, cuBLASLt, and the independent 128×128 Triton candidate with identical inputs.

These tools diagnose performance. They do not install model patches.

## Prepare and run

Use the project's existing Python environment and dependency versions.
For Qwen, use the SGLang and QSA source revisions in the [report](../2026-10-26/README.md).
MOSS cases import `kohakumoss_kernels`. The probes load no model weights.

Before running, provide sufficient free VRAM and isolate production traffic.
The worker limits its own PyTorch allocator to 1400 MiB.
That limit does not manage a service or prevent outside requests.
Use a new output directory for each experiment:

```sh
CUDA_VISIBLE_DEVICES=0 python worker.py --project moss --output /tmp/moss-operators
CUDA_VISIBLE_DEVICES=0 python worker.py --project qwen --output /tmp/qwen-operators
CUDA_VISIBLE_DEVICES=0 python paired_gemm.py --output /tmp/moss-gemm-paired
```

## Samples and profiler settings

Outputs include individual CUDA event samples, finite checks, and selected numerical diagnostics.
Each ordinary operator uses 21 CUDA-graph event samples.
Qwen also records 31 samples after a 96 MiB cache-eviction read.
A tiny operator with hot cache does not represent complete-model layer timing.

Paired GEMMs use seven alternating sweeps, with five measurements per implementation in each sweep.
The samples are correlated.

Counter mode places one operation inside NVTX range `operator_probe`.
Published Qwen counters use application replay, cache-control none, and clock-control none.
An explicit eviction read occurs before the range.
Keep profiler timings separate from ordinary CUDA event timings.

The local audit retained the initial HC/GDN kernel-replay cache discrepancy and corrected collection with application replay.

## Scope and limits

The 512-expert MoE uses synthetic packed W4 weights, group128, top10, and TP2-local intermediate padding to 384.
This does not validate production weights or every padding value.
`dgrad` tests backward GEMM dimensions with continuous synthetic weights.
It does not cover every production transpose stride.

The Triton candidate has no validated training integration or backward replacement.

Read the [results and limitations](../2026-10-26/README.md) before interpreting the measurements.
The public package excludes the private traffic guard/controller, host configuration, credentials, and boot images.
