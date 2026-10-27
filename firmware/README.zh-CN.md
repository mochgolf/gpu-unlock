[English](README.md) | [简体中文](README.zh-CN.md)

# 固定的 610.43.03 固件

## 下载和核验输入

`make inputs` 运行 `fetch_artifacts.py`。
它下载 `artifacts-610.43.03.json` 固定的 NVIDIA open kernel-module 源码归档和 CachyOS `nvidia-utils` 包。
下载使用 HTTPS。脚本在文件进入缓存前核验 SHA-256，并在每次运行时重新检查缓存。
脚本不执行或安装下载文件。

## 生成资源

`make firmware` 为模块的 `gpu-unlock/610.43.03/` 固件路径生成九个文件：

- `generate_v67.py` 从软件包提取 `gsp_ga10x.bin` 和 NVIDIA 许可证。
  它还生成 `v67-ga102-610.43.03.bin`、`v67-ad102-610.43.03-four-plm.bin`，每个 payload 为 64,000 字节。
- `extract_boot_assets.py` 从源码归档提取 `booter_load_ga102.bin`、`gsp_boot_ga102.bin`、`gsp_boot_desc_ga102.bin`，以及对应的三个 AD102 文件。

两个脚本在写入输出前，都会按固定 SHA-256 检查所有输入和输出。
提取需要 Python 3 和 `zstd` 命令。

## AD102 payload 和运行时检查

manifest 将 AD102 payload 固定为 SHA-256 `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb`。
payload 复现公开的四次写入链，顺序为 WPR_CFG、FBPA、WPR、FEAT_OVR_PLM。
首个值为 `0xfffff0ff`，其余三个为 `0xffffffff`。
随后请求 mailbox0 marker `0x67b00001` 和清理。

应用 selector 前，运行时检查必须确认 marker、所需权限读回和 SEC2 HALT。

[RTX 4090 历史报告](../rtx4090-register-report.zh-CN.md)记录了单卡 production 执行、FLR/原版驱动后状态保留，以及约两倍 FP32 累加 Tensor 吞吐。
payload 和由明文推导的指令地址来自 [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)。
[本地双卡报告](../benchmarks/2026-10-26/README.zh-CN.md)属于另一套配置和验收。

## 文件偏移和 DMEM 地址

manifest 分别记录 payload 偏移和 DMEM 地址。
按模型的复制基址 `0x600`，payload canary 偏移 `0xf94c` 对应 DMEM `0xff4c`。
payload 返回槽偏移 `0xf950` 对应 DMEM `0xff50`。
AD102 FEAT_OVR_PLM 地址字位于 payload 偏移 `0xf9cc`；GA102 使用 `0xf960`。

来源和许可证见 [NOTICE.md](NOTICE.md)。
