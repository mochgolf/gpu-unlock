[English](README.md) | [简体中文](README.zh-CN.md)

# RTX 4090 历史证据摘录

这些文件支持 [2026-10-23 单卡报告](../../../rtx4090-register-report.zh-CN.md)。
该实验使用一张 RTX 4090，完成一次成功冷上电。
固件实测发生于发布清理前；截至历史报告日期，清理后的模块仍待独立硬件复现。
后续[本地双卡实验](../../../benchmarks/2026-10-26/README.zh-CN.md)采用不同配置，不能追溯算作历史原版驱动实验的复现。

| 文件 | 内容 |
|---|---|
| [baseline.txt](baseline.txt) | 原始基准 stdout，20,000 次迭代，每模式重复三次 |
| [unlocked-20000.txt](unlocked-20000.txt) | 原始解锁后 stdout，20,000 次迭代，每模式重复三次 |
| [unlocked-40000.txt](unlocked-40000.txt) | 原始解锁后复测 stdout，40,000 次迭代，每模式重复三次 |
| [registers.txt](registers.txt) | 选取的冷状态、固件、payload、selector、FLR、独立卸载后、驱动后和基准后消息 |
| [telemetry-summary.json](telemetry-summary.json) | 两次解锁后运行期间，100 ms 遥测采样的摘要 |
| [SHA256SUMS](SHA256SUMS) | 上述证据文件的校验和 |

## 摘录保留了什么

基准文本保持原样。原始 `TF/s` 标签也包含整数速率，报告将其标为 `TOP/s`。
每次 multiply-accumulate 计为两次操作，不采用 sparsity 倍率。
基线采集早于成功解锁的冷上电。
解锁前后的 kernel、launch shape、计时方法和构建参数相同；发布清理仅澄清注释。

寄存器摘录保留原始值和消息内容。
删除项仅为墙钟时间戳、PCI 位置前缀，以及主机分配的 BAR0 地址/长度元数据。
章节标签标明采样阶段。
遥测摘要删除原始墙钟起止字段，保留全部 32 个样本及其中 26 个活跃样本的范围和均值。

功耗范围包含进入负载的过渡，不是逐 kernel 峰值。
这些文件是证据摘录，不是完整机器日志归档。

## 核验文件

在此目录运行：

```sh
sha256sum -c SHA256SUMS
```

AD102 payload 来自 [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)。
Linux loader 源于 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)。
来源和许可证见报告及[固件声明](../../../firmware/NOTICE.md)。
