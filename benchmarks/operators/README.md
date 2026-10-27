# Synthetic project-shaped operator probes

`worker.py` benchmarks representative MOSS BF16 projection/attention/LoRA/SiTU/
normalization and Qwen GEMV/HC/W4A16 MoE/GDN shapes. `paired_gemm.py` interleaves
cuBLAS, cuBLASLt and the independent 128x128 Triton candidate on identical
inputs. These are diagnostic tools, not deployed model patches.

Use the corresponding project's existing Python environment and dependency
versions. The Qwen cases need the SGLang and QSA plugin source revisions in the
report; the MOSS cases import `kohakumoss_kernels`. No model weights are loaded.
Allow sufficient free VRAM and isolate real traffic before running these finite
GPU workloads. The worker caps its own PyTorch allocator at 1400 MiB but does not
itself manage a production service or prevent outside requests.

```sh
CUDA_VISIBLE_DEVICES=0 python worker.py --project moss --output /tmp/moss-operators
CUDA_VISIBLE_DEVICES=0 python worker.py --project qwen --output /tmp/qwen-operators
CUDA_VISIBLE_DEVICES=0 python paired_gemm.py --output /tmp/moss-gemm-paired
```

Use a new output directory for every experiment. Results include the individual
event samples, finite checks and selected numerical diagnostics. Each ordinary
operator uses 21 CUDA-graph event samples. Qwen additionally records 31 samples
after a 96 MiB cache-eviction read; tiny hot-cache operators are not equivalent
to complete-model layer timings. Paired GEMMs use seven alternating sweeps and
five measurements per implementation per sweep. Samples are correlated.

Counter mode wraps one operation in NVTX `operator_probe`. The published Qwen
counter results use application replay, cache-control none and clock-control
none, with explicit pre-range eviction. Keep profiler timings separate from
ordinary CUDA event timings. The initial kernel-replay HC/GDN cache discrepancy
was retained in the local audit and corrected with application replay.

The full-512-expert MoE uses synthetic packed W4 weights, group128, top10 and
TP2-local intermediate padding to384. It is not a validation of production
weights or all padding values. `dgrad` tests the backward GEMM dimensions with
continuous synthetic weights, not every production transpose stride. The Triton
candidate has no validated training integration/backward replacement.

See the [results and limitations](../2026-10-26/README.md). The local traffic
guard/controller, private host configuration, credentials and boot images are
not included in this public benchmark package.
