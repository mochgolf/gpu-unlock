[English](README.md) | [简体中文](README.zh-CN.md)

# 双 RTX 4090：验收和性能，2026-10-26

**受控 BF16 Tensor、FP32 累加吞吐提升约 1.98 倍。**
真实应用提升较小。MOSS 历史训练吞吐对比提升约 11%，但存在已知混杂因素。
近期 Qwen 单请求解码基本不变。
独立 Triton 对比测量软件实现差异，不代表解锁收益。

## 配置和方法

系统使用 Supermicro H13SSL-N BIOS 3.5、ASPEED 控制台和四个 NUMA node。
两张卡均为改装 48 GiB AD102 RTX 4090，`10de:2684`，各报告 49,140 MiB。
内核为 `7.0.0-34-generic`，定制 `nvidia-open-p2p/595.84` 驱动支持 48 GiB 和 P2P。
每卡保留默认 450 W 上限，测试未超频。

验收不覆盖原版驱动或原装 24 GiB 卡。
MMA 使用 nvcc 12.8.93 和 `-O3 -arch=sm_89`。
算子测试使用 PyTorch 2.14.1/cu130 和 Triton 3.8.0。

适配保留上游 AD102 payload 和解锁模块。
新增内容为独立 pre-driver BME 归一化，以及已验证的 pre-udev 双卡流程。
诊断工具固定检查主板、BIOS、容量和插槽。

受控顺序为冷锁定 A1、目标卡解锁 B1、再次冷锁定 A2。
第二张卡始终锁定，作为对照。
证据保留主实验和匹配上下文样本、时钟爬升变化、负面或小幅 GEMM 结果，以及准入失败记录。
下表采用匹配上下文补充实验：每阶段每种 MMA 模式重复 30 次，每种 GEMM 形状重复 10 次。

共享二进制和库版本均固定。结果只覆盖一台机器，不是机群验收。

## 受控 A/B/A Tensor 结果

| 目标指令 | A1 锁定 | B1 解锁 | A2 锁定 | B1/A1 |
|---|---:|---:|---:|---:|
| f16/f16 (TFLOP/s) | 329.00 | 329.10 | 329.00 | 1.0003x |
| f16/f32 (TFLOP/s) | 164.60 | 328.90 | 164.60 | 1.9982x |
| bf16/f32 (TFLOP/s) | 164.50 | 325.95 | 164.50 | 1.9815x |
| s8/s32 (TOP/s) | 655.80 | 655.80 | 657.60 | 1.0000x |
| dp4a (TOP/s) | 163.10 | 163.15 | 163.20 | 1.0003x |
| ffma (TFLOP/s) | 78.40 | 78.40 | 78.60 | 1.0000x |

锁定对照卡三个阶段的 BF16 均约为 162.9 TFLOP/s。
标量 FP32 和整数对照没有相应的两倍提升。
参见[逐次样本和按对照归一化的比较](ab-a-matched.json)。

## 受控 cuBLAS GEMM 结果

| dtype / MxNxK | A1 TFLOP/s | B1 TFLOP/s | A2 TFLOP/s | B1/A1 |
|---|---:|---:|---:|---:|
| bf16 / 4096-4096-4096 | 144.48 | 144.61 | 144.40 | 1.0009x |
| bf16 / 8192-8192-8192 | 159.75 | 189.77 | 159.76 | 1.1879x |
| bf16 / 256-512-16384 | 113.03 | 131.59 | 113.26 | 1.1642x |
| fp16 / 4096-4096-4096 | 152.03 | 210.21 | 152.16 | 1.3827x |
| fp16 / 8192-8192-8192 | 160.67 | 181.70 | 160.76 | 1.1309x |
| fp16 / 256-512-16384 | 119.52 | 110.38 | 110.38 | 0.9235x |

BF16 4096³ 基本不变，8192³ 提升约 18.8%。
小 FP16 用例在锁定 A1 和锁定 A2 间也存在差异，因此相对首个基线的下降不能单独归因于解锁。
峰值 MMA 提升不能预测所有库 kernel 的收益。

此补充实验保留的全部完整 GEMM 输出对比均 bitwise equal。
有限值检查和独立抽样误差预算也通过。
这些检查不能证明所有未来模型或输入结果一致。
主实验每阶段通过 59 个配置用例，其中包括约 30 分钟稳定性测试。

证据保留了最初 A0 的 legacy 28 GiB P2P 映射失败。
后续 VMM P2P 成功不抹去该失败。
已验收的大显存负载要求使用此定制驱动已验证的 VMM 路径。

## 原生部署验收

后续两张 GPU 通过持久 GRUB 默认项启用；未修改的 safe-A 仍为可见菜单首项。
验收覆盖首次双卡冷启动、普通热重启，以及使用持久默认项的冷启动。
本机热重启满足冷状态检查，并完成完整解锁。
非冷状态下的动作前原版驱动 fallback 仅通过 chroot 测试。

硬件动作后发生任何失败，流程仍会停止。
这些结果不能证明通用的热启动恢复能力。

最终原生验收通过 33 个用例，包括数值检查、两种内存模式下的 28 GiB 分配、双向 1 MiB VMM P2P 和 MMA。
四个独立单 GPU MOSS 任务完成 800 个 optimizer step，非有限值 step 为零。
八张推理图像形成四组跨 GPU 配对，每对均 bitwise identical。
这些属于系统负载和数值检查，不代表模型质量评估。

Qwen 服务负载完成 460 个请求，观察到零错误。
该混合负载为 205.96 output-token/s，输入 cache hit 约 79.8%。
它不能作为稳态纯 decode 批量吞吐对照。

## MOSS 历史比较

比较使用总 token 数除以总区间时间，不比较历史 10-step 日志中位数和当前 1-step 中位数。
匹配区间为 step 51–140，共 90 step、237 样本、948,960 token。
两次运行使用相同 A 数据、cache、模型、BF16、rank16、seed 和原始 offload 策略。
区间排除 warm-up、保存和验证。九个配对 10-step 窗口均提升。

| 训练策略 | 历史 token/s | 当前 token/s | 吞吐变化 |
|---|---:|---:|---:|
| 相同原始 offload | 2753.94 | 3057.85 | +11.04% |
| 当前 resident 对比旧 offload | 2753.94 | 3232.95 | +17.39% |

当前 resident 策略比当前原始 offload 另高约 5.73%。
当前 launcher 还新增了显式 NUMA 绑定。
日志、启动、日期和 cache 条件均不同，不能把 11% 全部归因于解锁。

历史推理平均 42.90 s/image，当前为 38.13–38.66 s/image。
历史使用 32 张 balanced-profile 图像；当前每卡使用四张 speed-profile 图像。
prompt 和文本长度也有变化，不能分离解锁收益。
参见[历史测量及分母](historical-applications.json)。

## Qwen 单请求速度

测试采用 TP2、并发 1、temperature 0、关闭 thinking，且无 prefix-cache hit。
先预热两次，再测量 17 个请求；每个请求生成 512 个输出 token。
解码速度为 `(output_tokens-1)/(last_text_time-first_text_time)`。

| 输入 token | 请求数 | 解码 token/s 中位数 | TTFT 中位数 |
|---|---:|---:|---:|
| 113 | 7 | 88.51 | 0.312s |
| 2220 | 5 | 87.24 | 0.597s |
| 8840 | 5 | 86.45 | 1.477s |

参见[逐请求组测量](qwen-single.json)。
解锁前近期相同配置日志已约为 87 token/s。
匹配日志分组由 87.28 到 88.56（+1.47%）、86.42 到 87.32（+1.04%）。
这些是 prompt 不同的相关窗口，不是独立配对请求，也不是显著性检验。

更早的 73–81 token/s 来自不同软件栈或上下文，不能作为仅解锁差异的基线。
整体 C1 速度基本不变。

## MOSS 定向算子测试

成对测试使用相同 BF16 输入、GPU0 和 450 W。
七轮交替扫描为每种实现产生 35 次 event 测量。GPU1 复现了改进方向。

| MOSS GEMM (M,N,K) | cuBLAS us | cuBLASLt us | Triton128 us | Triton 吞吐提升 |
|---|---:|---:|---:|---:|
| qkv (4160, 3072, 3072) | 425.98 | 368.38 | 331.65 | +28.44% |
| up (4160, 16384, 3072) | 2284.03 | 2318.34 | 1687.42 | +35.36% |
| down (4160, 3072, 8192) | 1172.22 | 1180.53 | 904.18 | +29.64% |
| dgrad (4160, 3072, 16384) | 2425.98 | 2429.80 | 1929.09 | +25.76% |

FFN-up Tensor activity 从 58.36% 升到 90.59%。64×64 Triton 版本反而更慢。
结果依赖形状、tile 和具体实现，不能证明 Triton 普遍更快。
禁用 BF16 reduced-precision reduction 后，普通 cuBLAS QKV/up 耗时仅变化约 0.36%/0.08%。
每种成对实现均通过 16 个 CPU-FP64 抽样前向误差界检查。

候选尚未替换生产层，也未通过完整 backward/模型验收。
这些改进与解锁收益分开计算。
`dgrad` 采用 backward GEMM 维度和连续合成权重，不覆盖所有生产 transpose stride。

## 功耗、内存和软件限制

可逆 450 → 300 → 450 W 测试使大 MOSS GEMM 在 300 W 下延迟增加约 28–35%。
更快的 Triton FFN 延迟增加约 52%。
这证明对功耗敏感，但不能量化功耗在缺失解锁收益中的占比。
真实 MOSS offload 训练分别有 136/148、140/148 样本触发 power-cap flag。

resident 训练分别为 133/138、136/138。
没有采到 hardware thermal-throttling flag。
SiTU 和 normalization 对 300 W 不敏感，counter 探针分别接近持续 DRAM 吞吐的 94.0%、82.78%。

Qwen LM-head GEMV 为 978.8 GB/s、97.19% 持续 DRAM 吞吐、0% Tensor activity。
GDN-input GEMV 为 893.1 GB/s；HC 和两个 Marlin kernel 的 Tensor activity 约为 5%。
batch-1 负载具有低 arithmetic intensity、小 expert batch、反量化以及同步/启动开销。
LM head、HC、batch-1 MoE 和 GDN-recurrent 的 event 中位数在 300 W 与恢复后的 450 W 间变化不足 0.4%。

GDN-input hot-cache 延迟变化 8.84%；驱逐缓存后约为 1.76%。
因此，不能推断所有 Qwen kernel 都不受功耗影响。
CPU 调度、TP 通信、KV 访问和 indexing 仍可能限制服务。
本次未重新分析它们在当前关键路径中的占比。

Qwen counter 采集从 kernel replay 改为 application replay，并显式驱逐 96 MiB 缓存。
counter 用于分析限制；profiler 耗时不能替代普通 event 时间，也不能求和得到整模型延迟。
参见[逐算子样本和 counter](operators.json)。

Nsight 仅在 profiling 期间产生 54 次驱动 `pSmIssueThrottleCtrl != NULL` 断言。
595.84 源码在 getter 中返回 `NV_ERR_NOT_SUPPORTED`。
普通计时和功耗测试窗口没有这些断言，且未观察到 Xid。
尚无证据证明此 profiler/驱动兼容问题造成日常训练或解码性能限制。

profiling 后 GPU0 仍有 124 MiB 的已用显存报告差异。
应用 owner 和其报告的分配量未变。未为清除此差异而重启生产服务。

## 来源、追溯和限制

- 基础版本：[elias-gaeros/gpu-unlock @4ec490d](https://github.com/elias-gaeros/gpu-unlock/tree/4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc)。
- Loader：[Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)。
- AD102 payload 分析：[TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)。本适配不主张发现该链。
- 运行源码版本：SGLang `baa9befa381511cd4d56f83980951e5a45fffc6d`；QSA `d9c2339771d9bbafc771ec29f3d471aaeca8a1bf`。
  MOSS 使用已安装 kohakumoss 0.1.0。
- 参考：[Nsight 指南](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)、
  [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/) 和 [PyTorch BF16 reduction 设置](https://docs.pytorch.org/docs/main/notes/cuda.html)。

公开证据保留数值样本、counter、受控比较和有限事务证明。
它不包含主机/用户名、GPU/文件系统 UUID、管理地址、凭据、私有项目路径、模型权重或完整机器日志。
原始本地证据保持不变。
发布使用过滤日志和参数化持久化模板，不分发完整本地 initrd 镜像或含凭据的 controller。

## 发布检查

组装后的 fork 在实测主机通过 12 个主机测试，无跳过。
其中包含 21 个 BME 故障用例、42 个 fake-PCI 检查和 19 个提醒测试。
两个内核模块和静态 collector 均针对 `7.0.0-34-generic` 重建。
staging wrapper 核验固定资源并生成 overlay，未安装，也未执行硬件动作。

因缺少 `vmlinux`，跳过 BTF 生成；编译器名称警告指向相同 GCC 13.3.0 版本。
检查从公开数据重新计算了逐组 MMA 中位数、九个匹配 MOSS 区间和全部 19 次 Qwen 请求测量。
参见[验证记录](publication-validation.json)。
发布没有重启、执行固件或重启生产服务，也没有用重建产物替换已部署产物。
