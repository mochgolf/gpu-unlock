[English](rtx4090-register-report.md) | [简体中文](rtx4090-register-report.zh-CN.md)

# Historical RTX 4090 AD102 experiment

**On 2026-10-23, one RTX 4090 showed approximately doubled FP16/BF16 Tensor throughput with FP32 accumulation.**
The override survived FLR, stock NVIDIA initialization, and CUDA load.

| Instruction mode | Baseline | Unlocked, 20k iterations | Unlocked, 40k iterations |
|---|---:|---:|---:|
| FP16 / FP32 accumulate | 165.6 TF/s | **331.6 TF/s** | **330.8 TF/s** |
| BF16 / FP32 accumulate | 165.5 TF/s | **330.6 TF/s** | **330.3 TF/s** |
| FP16 / FP16 accumulate | 325.7 TF/s | 306.3 TF/s | 331.6 TF/s |
| INT8 / INT32 accumulate | 661.6 TOP/s | 661.4 TOP/s | 659.5 TOP/s |
| `dp4a` | 164.5 TOP/s | 164.4 TOP/s | 164.1 TOP/s |
| scalar FP32 `ffma` | 79.1 TF/s | 79.1 TF/s | 79.1 TF/s |

The AD102 payload and construction analysis come from [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
The Linux loader and boot packaging derive from [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
This work integrates the public payload, selects AD102 assets, adds transaction checks, and measures an RTX 4090.
It does not claim discovery of the AD102 chain.

## Scope of this historical report

This report covers one physical card and one successful cold power-on.
The baseline preceded that power-on. It was not an in-place baseline on the successful unlock boot.
Both measurements used the same benchmark kernels, launch geometry, timing method, and build flags.

The successful firmware run preceded publication cleanup.
At the report's date, the cleaned module had host validation but no separate hardware confirmation.
Independent cold-boot reproduction and representative numerical validation remained pending.
The cleaned module retained the normal `targets=` interface.

The later [local dual-card study](benchmarks/2026-10-26/README.md) uses different hardware, kernel, and driver conditions.
Its acceptance does not retroactively repeat this historical stock-driver experiment.
The [evidence guide](docs/evidence/rtx4090/README.md) links original benchmark text and selected sanitized register logs.
Those excerpts are not a complete machine log.

## 1. Configuration and inputs

| Item | Value |
|---|---|
| Device | NVIDIA GeForce RTX 4090, `10de:2684`, AD102, 128 SMs, compute capability 8.9 |
| Chip register | `PMC_BOOT_0 = 0x192000a1` |
| Kernel | Linux `7.2.4` |
| Confirmation driver | unmodified NVIDIA `615.78.08` |
| Generated firmware inputs | pinned NVIDIA `610.43.03` source and binary package |
| AD102 payload | `v67-ad102-610.43.03-four-plm.bin`, 64,000 bytes |
| Payload SHA-256 | `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb` |
| Booter asset | `booter_load_ad102.bin`, 57,672 bytes |
| Booter SHA-256 | `6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49` |
| Benchmark build | `nvcc -O3 -arch=sm_89` |
| Power limit / reported maximum SM clock | 450 W / 3135 MHz |

Before execution, all nine generated assets matched the manifest pins.
The reproduced AD102 payload also matched the published generator and shipped payload byte-for-byte.
Integrity checks are in [generate_v67.py](firmware/generate_v67.py), [extract_boot_assets.py](firmware/extract_boot_assets.py), and the [manifest](firmware/artifacts-610.43.03.json).
[NOTICE.md](firmware/NOTICE.md) records licensing and the pinned upstream revision.

## 2. Mechanism

Direct host writes to feature permissions and speed selectors had no effect on the cold card or after FWSEC-FRTS alone.
Authenticated firmware with the required privilege supplied the missing protected-register write.

The AD103 project published an AD102-family V67 data payload from decrypted debug-booter analysis.
Its instruction addresses supplied the required plaintext-derived knowledge.
The Linux module loads an unchanged signed production booter.
SEC2 authenticates and decrypts that booter inside the GPU.

Crafted signature data overwrites stack slots and redirects returns through existing authenticated booter instructions.
Those instructions perform protected writes. The host does not add executable code to the authenticated image.

The successful run shows that the selected addresses work in the tested production booter.
It does not show that the complete debug and production plaintext images are identical.
This repository distributes no decrypted firmware image.

The transaction follows this sequence:

1. Claim an eligible cold card. Save PCI state and allocate DMA buffers.
2. Run the board ROM's signed FWSEC-FRTS on the GSP Falcon to establish the firmware reservation.
3. Start the signed AD102 booter on SEC2 with crafted V67 signature data.
   The chain targets WPR_CFG, FBPA, WPR, and FEAT permissions, requests mailbox marker `0x67b00001`, then halts.
4. Before host selector writes, require the marker, SEC2 HALT, accessible PCI/BAR, and expected WPR_CFG/WPR/FEAT permissions.
5. Apply SS0 `0x88888888` and SS1 `0x8`.
   Require their readbacks and zero values in all nine effective speed-select fields.
6. Perform PCIe FLR. Verify reset containment and retained FEAT/selector state.
   Restore PCI state and release resources.
7. Initialize the stock NVIDIA driver. Check registers and benchmark the same instruction modes.

The published model orders the four stores as WPR_CFG (`0x1fa7cc`), FBPA (`0x9a0148`), WPR (`0x1fa7c4`), then FEAT (`0x823804`).
Permission transitions and the terminal marker support chain execution.
No independent bus trace confirmed the internal store order.
FBPA stayed unchanged and was not a required success condition.

The payload contains `0xfa00` bytes of repeated `0x0000019c` words, with patches from `0xf948` to `0xf9fc`.
File offsets `0xf94c` and `0xf950` hold the canary and return slot.
With modeled copy base `0x600`, these map to DMEM `0xff4c` and `0xff50`.
The AD102 FEAT target word is at file offset `0xf9cc`. GA102 uses `0xf960`.

File offsets and DMEM addresses are different coordinates.

## 3. Observed firmware transaction

No NVIDIA driver loaded before the successful transaction.
That power-on included exactly one FWSEC start, one AD102 SEC2 start, and one FLR.
Legacy capture and host-write probes were disabled. The public module removes those research paths.

| Stage | Required evidence | Observed |
|---|---|---|
| Asset integrity | correct payload and booter pins | passed |
| Cold state | no bound driver, bus mastering off, WPR2 down, FEAT permission closed | passed |
| FWSEC | scratch `0`, expected FRTS/WPR2 reservation | passed |
| Payload | marker `0x67b00001`, SEC2 HALT, required permissions and accessible PCI/BAR | passed |
| Selectors | SS0/SS1 `0x88888888`/`0x8`, effective readout zero | passed |
| Reset | FLR `0`, FEAT/selector state retained, WPR2 down, DMA contained | passed |
| Driver | same FEAT/selector/readout values after stock initialization | passed |
| Performance | increase beyond baseline variation, with scalar/integer controls | passed |

FWSEC returned scratch `0` and WPR2 low/high `0x05ff2000:0x05ff2e00`.
The payload gate completed about 234 ms after SEC2 start.
It reported mailbox `0x67b00001`, CPUCTL `0x10`, and the required permissions.
Host selector writes then changed the effective readout from `0x00410080` to zero.

| Register | Cold | After payload, before selectors | After FLR and module unload |
|---|---|---|---|
| WPR_CFG PLM `0x001fa7cc` | `0x0004cb8f` | `0xfffff0ff` | `0x0004cb8f` |
| FBPA PLM `0x009a0148` | `0xffffff0f` | `0xffffff0f` | `0xffffff0f` |
| WPR PLM `0x001fa7c4` | `0x0004cb8f` | `0xffffffff` | `0x0004cb8f` |
| FEAT PLM `0x00823804` | `0xffffff8f` | `0xffffffff` | `0xffffffff` |
| SS0 `0x0082381c` | `0x44023025` | `0x44023025` | `0x88888888` |
| SS1 `0x00823820` | `0x00000007` | `0x00000007` | `0x00000008` |
| Effective readout `0x00823818` | `0x00410080` | `0x00410080` | `0x00000000` |

Only four of 31 sampled feature-cluster words changed between cold state and the independent post-unload sample.
They were FEAT PLM, SS0, SS1, and effective readout.
OTP words still reported `FMLA32`, `IMLA2`, and `IMLA4` as `1`.
The result is a feature override, not an OTP fuse rewrite.

FLR restored WPR and WPR_CFG, while FEAT stayed overridden.
Unchanged FBPA does not prove that its attempted store was unnecessary or that the register is physically read-only.

The module restored PCI command `0x3` and checked GSP HALT, WPR2 down, and no pending transactions.
It released DMA and left no retained module reference.
Module removal completed before an independent read-only sample.
Stock NVIDIA `615.78.08` then initialized the GPU.

Samples after initialization and CUDA benchmarks still showed FEAT PLM `0xffffffff`, SS0 `0x88888888`, SS1 `0x8`, and zero effective readout.
The collected confirmation journal contained no NVIDIA Xid/error.

See [registers.txt](docs/evidence/rtx4090/registers.txt).
A successful module-load return alone is insufficient.
Per-card errors can be logged without failing module initialization.
Stage readbacks and independent samples establish this result.

## 4. Benchmark method and limits

The [CUDA benchmark](diagnostics/bench/mma_bench.cu) measures instruction issue throughput, not end-to-end GEMM or application speed.
Timed loops keep operands and accumulators in registers, with no internal memory traffic.
The method uses:

- WMMA m16n16k16 for FP16/FP16, FP16/FP32, BF16/FP32, and INT8/INT32.
- Eight independent Tensor accumulator chains per warp; 32 chains for scalar `dp4a` and FP32 FMA.
- 1,056 blocks of 256 threads, or eight warps per block, on 128 active SMs.
- One warm-up before each CUDA-event timed launch; three timed repetitions per mode, with the best reported.
- 20,000 iterations for the baseline and first unlocked run; 40,000 for the unlocked repeat.

Publication cleanup changes historical comments only.
Kernels, launch geometry, operation counts, timing, and flags match the measured runs.
After the unlock and driver handoff, run these commands with CUDA and NVIDIA loaded:

```sh
mkdir -p build
nvcc -O3 -arch=sm_89 -o build/mma_bench diagnostics/bench/mma_bench.cu
build/mma_bench 20000 3
build/mma_bench 40000 3
```

Each multiply-accumulate counts as two operations. Each WMMA call counts `16 × 16 × 16 × 2 = 8192` operations per warp.
`dp4a` and scalar FMA counts are per lane.
The program prints `TF/s` for every mode. This report uses `TOP/s` for integer results.

It applies no sparsity multiplier.

Generated-code inspection found the intended instructions in the respective loops:
`HMMA.16816.F16`, `HMMA.16816.F32`, `HMMA.16816.F32.BF16`, `IMMA.16816.S8.S8`, `IDP.4A.S8.S8`, and `FFMA`.
Earlier 10k, 20k, and 40k baseline runs gave stable FP32-accumulate, integer, and scalar rates.
This supports real timed work rather than compiler elimination.
Accumulators stay live to prevent elimination. The benchmark does not compare their numerical values with a reference.

Raw principal samples are in [baseline.txt](docs/evidence/rtx4090/baseline.txt),
[unlocked-20000.txt](docs/evidence/rtx4090/unlocked-20000.txt), and [unlocked-40000.txt](docs/evidence/rtx4090/unlocked-40000.txt).

| Mode | Baseline runs | Unlocked 20k runs | Unlocked 40k runs |
|---|---|---|---|
| FP16 / FP16 | 306.3 / 306.3 / 325.7 | 306.3 / 306.3 / 306.3 | 331.6 / 331.6 / 330.9 |
| FP16 / FP32 | 165.6 / 165.6 / 165.6 | 331.6 / 331.6 / 331.6 | 330.8 / 330.8 / 330.8 |
| BF16 / FP32 | 165.4 / 165.5 / 165.5 | 329.5 / 330.6 / 329.6 | 330.3 / 328.3 / 328.2 |
| INT8 / INT32 | 661.5 / 661.6 / 661.4 | 661.4 / 661.3 / 661.3 | 659.5 / 659.4 / 659.4 |
| `dp4a` | 164.5 / 164.5 / 164.5 | 164.4 / 164.4 / 164.4 | 164.1 / 164.0 / 164.1 |
| scalar FP32 | 79.1 / 79.1 / 79.1 | 79.1 / 79.0 / 79.1 | 79.0 / 79.1 / 79.1 |

The best 20k samples improved FP16/FP32 by **2.002×** and BF16/FP32 by **1.998×**.
The longer repeat confirmed the increase.
The first FP16/FP16 group was sensitive to clock ramp before and after unlock.
The longer unlocked run reached 331.6 TF/s.

INT8, `dp4a`, and scalar FP32 stayed near baseline. The results do not support doubled INT8 throughput.

The two unlocked runs produced 32 telemetry samples at 100 ms intervals; 26 had nonzero utilization.
Active samples showed SM clocks of 2550–2760 MHz, memory at 10251 MHz, power of 23.81–224.89 W, and temperature of 35–52 °C.
The low power value includes entry into load. Samples are not per-kernel peaks.

The power limit stayed at 450 W. The reported maximum SM clock stayed at 3135 MHz.
The comparison changed no power limit, clock setting, or NVIDIA driver code.

## 5. Register reference and earlier observations

These are BAR0 offsets.
Names follow the [public Ampere/CMP reference](https://gist.github.com/nvlight/813a866dc69d417497a427f4208321ff).
The experiment measured offset values. It did not independently establish every name or field mapping.

| Offset | Name | Cold value / interpretation |
|---|---|---|
| `0x00820000` | FUSECTRL | `0xe0040000` |
| `0x008200fc` | FUSE_SS_PLM | `0xffffffff` |
| `0x0082038c` | SECURE_FEAT_OVR_QUADRO_WR_SECURE | `1` |
| `0x0082059c` | FUSE_SS_FFMA | `0` |
| `0x008207d4` | FUSE_SS_FMLA16 | `0` |
| `0x008207d8` | FUSE_SS_FMLA32 | `1` |
| `0x008207dc` / `0x008207e0` | FUSE_SS_IMLA0 / IMLA1 | `0` / `0` |
| `0x008207e4` / `0x008207e8` / `0x008207ec` | FUSE_SS_IMLA2 / IMLA3 / IMLA4 | `1` / `0` / `1` |
| `0x00823804` | FEAT_OVR_PLM | `0xffffff8f`, permission gate |
| `0x00823814` | FEAT_READOUT_0 | `0x00000233` |
| `0x00823818` | FEAT_READOUT_1 | `0x00410080`, nine 3-bit fields under mask `0x07ffffff` |
| `0x0082381c` | FEAT_OVR_SM_SPEED_SELECT | `0x44023025` on the successful power-on |
| `0x00823820` | FEAT_OVR_SM_SPEED_SELECT_1 | `0x7` |
| `0x00409664` / `0x00409668` | FECS selector / readout copies | `0xbadf5040` cold and with driver bound |
| `0x00504204` | SM_ISSUE_RATE_MODIFIER | `5`, unchanged by driver |
| `0x001fa824` / `0x001fa828` | WPR2 low / high | `0x1ffffe00` / `0` cold |
| `0x00824140` / `0x008241e0` | booter / FWSEC fuse | `1` / `1` |

Cold `FEAT_READOUT_1`, from low field to high, decodes as `0 0 2 0 0 2 0 2 0`.
The three reduced fields have no established mapping to named FMLA/IMLA fuse words.
Each SS0 nibble contains bit 3 as enable and three value bits. Value `8` enables a zero-value override.

SS1 uses a 4-bit selector. Its isolated performance effect is unmeasured.
Earlier power-ons showed a varying high byte in cold SS0, with every override enable bit clear.
That byte's meaning remains unverified.

SEC2, its FBIF, and its Falcon2 window are at `0x00840000`, `0x00840600`, and `0x00841000`.
The GSP equivalents are `0x00110000`, `0x00110600`, and `0x00111000`.
Falcon CPUCTL offset `0x100` reports HALT as `0x10`. Mailbox0/1 use `0x040`/`0x044`.

EXIT alone does not prove payload execution.
Negative controls produced EXIT even when the GPU refused host-written instructions.
Require the explicit marker, HALT, and independent permission readbacks together.

Earlier bounded experiments found the following:

- Host PLM/selector writes had no effect before the signed payload, including after successful FWSEC-FRTS alone.
- The GA102 booter halted without opening AD102 FEAT permissions.
  The demonstrated result required the AD102 booter and chain.
- Tested SEC2 modes did not execute unsigned host microprograms.
  Self-loop, DMEM-store, and instruction-timing controls showed no execution despite EXIT.
- Tested PIO/DMA/tag/port paths did not extract loaded secure IMEM.
  Secure reads returned `0xdead5ec1`. Readable plain blocks were not fetchable as executable code.
  ROM inspection yielded no plaintext Falcon image.
- Earlier cold-versus-driver samples left 31 feature-cluster words unchanged.
  The successful unlock showed that stock initialization also preserved modified FEAT/selector state.

These observations do not prove that every extraction or authentication attack is impossible.
The public module excludes the research probe and capture modules.

The tested AD102 booter has image size `0xde00`, OS data `0x7e00`/`0x6000`, and application code offset/size `0x100`/`0x7d00`.
Its signature patch offset is `0x7e10`.
The GSP boot image is 36,864 bytes, with descriptor code `0x4800` and data `0x800`.
The ROM FWSEC DMEM length was `0xd80`, requiring 14 rounded 256-byte DMA blocks.

Transfer validation must accept this unaligned length and check its rounded bounds.

## 6. Public module and reproduction

The [README](README.md) describes packaging and the opt-in `gpu_unlock.targets=` interface.
RTX 4090 `10de:2684` selects AD102 assets automatically.
Accepted legacy GA102/GA104 IDs retain their original path. Other Ada IDs are rejected.

A shared Ada booter archive does not establish safe or effective operation on every Ada chip.

The module requires an unbound, powered card, bus mastering off, and eligible firmware state since power-on.
If the marker, HALT, or permissions fail, it stops before selector application.
It checks selector readbacks and effective readout before and after FLR.
It also checks PCI identity, BAR stability, and reset containment.

An inaccessible all-ones MMIO value alone does not mean a permission register is open.

If DMA access can continue and reset containment is unverified, the module retains buffers and its reference until power-off.
Do not force-unload it in this state.
The successful experiment released these resources. Retention is a failure path, not part of normal handoff.

For reproduction, power off fully before a new attempt.
Let the initramfs module run before any GPU driver.
Do not use `nvidia-smi`, CUDA, NVML, or `nvidia-modprobe` for pre-unlock checks.
They can load NVIDIA by name. A normal modprobe blacklist does not block this.

Keep the kernel log. Inspect every transaction stage.
While `gpu_unlock` runs, do not map BAR0 with another experiment module.

This historical study sampled independently after module removal and later with NVIDIA bound.
The local port's different `gpu_cold_probe` collector is restricted to the pre-driver state.
Do not run that collector on a GPU owned by NVIDIA.

After successful FLR handoff, initialize the stock driver.
Independently read selectors and effective readout. Then run the benchmark.
After a failed or retained firmware run, power off before retrying.

A warm reboot does not guarantee a fresh card. This report claims no power-off persistence.

The experiment's host validation passed 13 tests and LLVM builds of the module and read-only sampler.
Tests included complete mocked AD102 transactions and failures for markers, permissions, HALT ordering, selectors, and effective readout.
They also covered corrupted payload copies, metadata races, and DMA retention.
Publication cleanup removed research parameters and capture paths while retaining normal transaction checks.

That historical cleaned tree passed nine host tests, including seven C components and complete mocked GA102/AD102 transactions.
It also passed LLVM module and sampler builds.
Host tests and builds do not replace a hardware repeat.

## 7. Attribution and open work

The decisive AD102 reference is [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker).
It includes `source/firmware-tools/ad102_payload.py`, `docs/ANALYSIS.en.md`, booter disassembly excerpts, and the shipped four-PLM payload.
That project reports approximately doubled FP32-accumulate throughput on RTX 4080/AD103.
Those external results provide attribution and context. They are not measurements from this RTX 4090.

The Linux module derives from [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock).
Its GA102 V67 lineage includes [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock).
Nouveau Falcon/GSP loaders, NVIDIA open-module source, and [envytools](https://github.com/envytools/envytools) informed loading and register analysis.
See [NOTICE.md](firmware/NOTICE.md), the [manifest](firmware/artifacts-610.43.03.json), and [licenses/](licenses/) for provenance, pins, and preserved GPL/MIT notices.

NVIDIA firmware retains its own license terms.

At this report's date, useful next checks were an independent cleaned-module cold repeat, numerical-reference workloads, and longer sustained load.
Open technical questions remain: readout-field mapping, isolated SS1 effect, and the need for each WPR/WPR_CFG/FBPA store.
The AD102 scrubber reservation rule and compatibility beyond the tested booter/card also remain unresolved.
