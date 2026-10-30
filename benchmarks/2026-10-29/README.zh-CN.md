[English](README.md) | [简体中文](README.zh-CN.md)

# FP8 指令吞吐：2026-10-29

**现有解锁生效时，FP8 输入、FP32 累加与 FP16 累加的吞吐基本相同。**
两张已测显卡的 E4M3、E5M2 均表现如此，无需额外 FP8 补丁。
本次没有本机锁定组，因此不提供本机解锁前后的实测倍率。

## 配置和方法

系统仍为原有 [H13SSL-N 双卡部署](../../ports/supermicro-h13ssl/README.zh-CN.md)。
配置包括改装 48 GiB AD102、BIOS 3.5、内核 `7.0.0-34-generic` 和定制 `nvidia-open-p2p/595.84`。
两张卡均保留 450 W 上限。
GPU0 为 `0000:01:00.0`，GPU1 为 `0000:41:00.0`。
测试发生于洛杉矶时间 10 月 29 日，对应 UTC 10 月 30 日 01:41:42–01:42:25。

[CUDA 源码](../../diagnostics/bench/fp8_mma_bench.cu)使用稠密、寄存器驻留的 MMA 循环。
每个 multiply-accumulate 计为两次操作，不计稀疏倍率。
FP8 使用 `mma.m16n8k32`；FP16/BF16 对照使用 `mma.m16n8k16`。
grid 为 1,056 个 block，每 block 256 thread。
主测试使用八条独立 accumulator chain、20,000 次迭代，每卡每模式测量 21 次。
每轮轮换起始模式，并交替反转顺序；采样前先预热。

补充测试采用四条、16 条 chain，各测七次；另用八条 chain、40,000 次迭代，各测 21 次。
全部八组运行、784 次 event 样本保留在 [samples.json](samples.json)。
样本存在相关性，未作显著性检验。

## 主测试结果

以下为稠密 TFLOP/s 中位数，每个单元格包含 21 次测量。

| 输入 / 累加 | GPU0 | GPU1 |
|---|---:|---:|
| E4M3 / FP32 | 648.75 | 656.30 |
| E5M2 / FP32 | 648.67 | 656.28 |
| E4M3 / FP16 | 649.50 | 657.01 |
| E5M2 / FP16 | 649.52 | 657.03 |
| BF16 / FP32 | 325.79 | 329.64 |
| FP16 / FP32 | 325.82 | 329.62 |
| FP16 / FP16 | 325.80 | 329.55 |

FP8/FP32 中位数约为对应 FP8/FP16 中位数的 99.9%。
40,000 次迭代时，FP8/FP32 中位数仍约为 GPU0 的 649 TFLOP/s、GPU1 的 655 TFLOP/s。
四条 chain 的 FP8 速率略低，八条和 16 条接近。
逐模式、逐组结果、范围、时钟估计和比值见 [results.json](results.json)。

## 网络参考及解读

[NVIDIA Ada 白皮书 V2.02](https://images.nvidia.com/aem-dam/Solutions/geforce/ada/nvidia-ada-gpu-architecture.pdf#page=30)给出的 RTX 4090 原版峰值如下：

| FP8 输入模式 | 标称 2520 MHz boost 时钟下的稠密峰值 |
|---|---:|
| FP32 累加 | 330.3 TFLOP/s |
| FP16 累加 | 660.6 TFLOP/s |

当前 FP8/FP32 实测约为官方 FP32 累加峰值的 1.96–1.99 倍。
该比值是实测与规格的比较，不是本机 A/B 加速比；显卡运行时钟也不同。
主测试的 block 时钟估计约为 GPU0 的 2710 MHz、GPU1 的 2744 MHz。

按时钟归一化后，FP8/FP32 仍约为同频原版理论峰值的 1.83 倍，约达到不限速理论值的 91%。
此估计包含有限 grid、指令和计时开销，不是锁频实验。
更直接的内部对照是 FP32、FP16 累加几乎同速。
这些结果共同支持：现有解锁下，FP8/FP32 已处于不限速吞吐档位。
它们没有独立确认 FP8 与某个 speed-select 字段的对应关系。

## 指令和数值检查

CUDA 12.8.93 使用 `-O3 -std=c++17 -arch=sm_89 -lineinfo -Xptxas=-v` 编译源码。
SASS 包含 `QMMA.16832.F32.E4M3.E4M3`、`QMMA.16832.F32.E5M2.E5M2`，以及对应 FP16 累加指令。
对照使用原生 HMMA；所有已编译 kernel 的 spill load/store 均为零。
计时循环没有先将 FP8 转换为 FP16。
`sm_89` 的 FP8 MMA 支持见 [NVIDIA PTX ISA](https://docs.nvidia.com/cuda/archive/12.8.0/parallel-thread-execution/index.html)。

输入均为可精确表示的非零值 `2^-6`。
短测试在 1、2、32 次迭代后检查所有 lane、chain 和 accumulator 元素。
168 项检查全部通过，共覆盖 193,536 个输出元素，绝对误差为零。
全部计时输出 checksum 均为有限值。
长循环的 FP16 累加最终无法分辨这些小增量，但没有溢出。
长循环只测吞吐，不验证长序列数值累加。
均匀输入检查不能验收任意 FP8 输入、量化 scale、GEMM、backward 或训练。

## 服务共存和结束状态

本地 controller 每次只运行一个 GPU worker。
它要求请求指标空闲，并且只允许已准入的两个 Qwen GPU 进程和自己的 worker。
整个测试期间持续检查流量、进程身份、功耗上限、温度和 boot identity。
检查失败时，只停止自己的子进程。
Qwen 保持加载；所有已观察的运行中、排队请求指标均为零。

每卡 47 个活动阶段遥测样本均未显示 power-cap 或 hardware thermal-slowdown flag。
GPU0/GPU1 的采样峰值功耗为 192.88/206.96 W，最高温度为 46/50 °C。
这些值仅代表均匀寄存器负载，不能代表任意模型功耗。
测试后，服务 GPU PID 和分配量保持不变，总已用显存回到基线。
boot 未变，解锁状态仍确认成功；可读取的内核日志中没有测试窗口内新增的 Xid 或 GPU 掉线消息。
测试未修改启动项、固件、模块、驱动、时钟或功耗上限，也没有重启服务。

## 复现指令测试

请使用显存充足的已测空闲 GPU，并在运行前隔离服务流量。
公开程序不包含私有服务流量 controller。
位置参数依次为迭代次数、重复次数、accumulator chain 数（`4`、`8` 或 `16`）。
程序要求具备 128 个 SM 的 `sm_89` GPU。
使用全新输出目录：

```sh
mkdir -p build
mkdir build/fp8-run
nvcc -O3 -std=c++17 -arch=sm_89 -lineinfo -Xptxas=-v \
  -o build/fp8-run/fp8_mma_bench diagnostics/bench/fp8_mma_bench.cu
cuobjdump --dump-sass build/fp8-run/fp8_mma_bench > build/fp8-run/instructions.sass
CUDA_VISIBLE_DEVICES=0 build/fp8-run/fp8_mma_bench 20000 21 8 > build/fp8-run/g0-primary.jsonl
CUDA_VISIBLE_DEVICES=1 build/fp8-run/fp8_mma_bench 20000 21 8 > build/fp8-run/g1-primary.jsonl
```

补充测试在每卡分别使用 `(20000, 7, 4)`、`(20000, 7, 16)`、`(40000, 21, 8)`。
每次运行使用独立文件。
源码/二进制哈希和 SASS 审计见 `results.json`；[SHA256SUMS](SHA256SUMS)覆盖公开源码和证据文件。
仅运行主机测试的 CI 不会执行此 CUDA 基准。

这些结果测量指令吞吐，不能推断 MOSS 或 Qwen 应用会加速两倍。
