[English](README.md) | [简体中文](README.zh-CN.md)

# MOSS 和 Qwen 合成算子探针

`worker.py` 测量两个项目的代表性算子形状。
MOSS 用例覆盖 BF16 projection、attention、LoRA、SiTU 和 normalization。
Qwen 用例覆盖 GEMV、HC、W4A16 MoE 和 GDN。
`paired_gemm.py` 使用相同输入，交替测量 cuBLAS、cuBLASLt 和独立的 128×128 Triton 候选实现。

这些工具用于性能诊断，不安装模型补丁。

## 准备和运行

请使用对应项目已有的 Python 环境和依赖版本。
Qwen 需要[报告](../2026-10-26/README.zh-CN.md)中固定的 SGLang、QSA 源码版本。
MOSS 用例导入 `kohakumoss_kernels`。探针不加载模型权重。
运行前，请确保显存充足，并隔离生产流量。

worker 将自身 PyTorch allocator 限制为 1400 MiB。
此限制不管理生产服务，也不能阻止外部请求。
每次实验使用新的输出目录：

```sh
CUDA_VISIBLE_DEVICES=0 python worker.py --project moss --output /tmp/moss-operators
CUDA_VISIBLE_DEVICES=0 python worker.py --project qwen --output /tmp/qwen-operators
CUDA_VISIBLE_DEVICES=0 python paired_gemm.py --output /tmp/moss-gemm-paired
```

## 样本和 profiler 设置

输出包含各次 CUDA event 样本、有限值检查和部分数值诊断。
普通算子各使用 21 个 CUDA-graph event 样本。
Qwen 还在一次 96 MiB cache-eviction 读取后记录 31 个样本。
小算子的 hot-cache 时间不能代表完整模型的层耗时。

成对 GEMM 采用七轮交替扫描；每轮每种实现测量五次。
这些样本存在相关性。

counter 模式用 NVTX range `operator_probe` 包围一次操作。
公开 Qwen counter 使用 application replay、cache-control none 和 clock-control none。
range 前显式读取数据以驱逐缓存。
请将 profiler 耗时与普通 CUDA event 耗时分开解读。

本地审计保留了最初 HC/GDN kernel replay 的缓存偏差，并改用 application replay 修正采集。

## 范围和限制

512-expert MoE 使用合成 packed W4 权重、group128、top10，以及补齐到 384 的 TP2 本地 intermediate。
此测试不验证生产权重，也不覆盖全部 padding 值。
`dgrad` 使用连续合成权重测试 backward GEMM 维度，不覆盖所有生产 transpose stride。
Triton 候选尚未完成训练集成验证，也没有已验证的 backward 替换。

解读结果前，请阅读[结果和限制](../2026-10-26/README.zh-CN.md)。
公开包不包含私有流量 guard/controller、主机配置、凭据或启动镜像。
