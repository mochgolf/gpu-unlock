[English](README.md) | [简体中文](README.zh-CN.md)

# GPU unlock：Supermicro 双 RTX 4090 适配

此 fork 包含 mochgolf 已实测的 H13SSL-N 适配，目标是两张改装 48 GiB AD102 显卡。
上游 `gpu_unlock` 模块和 AD102 payload 保持不变。
本地适配增加了独立 Bus Master Enable（BME）诊断模块、pre-udev 启动流程、开机/SSH 提醒和公开测试证据。

| 文档 | 用途 |
|---|---|
| [硬件适配](ports/supermicro-h13ssl/README.zh-CN.md) | 已测硬件、构建步骤、启动流程和限制 |
| [开机/SSH 提醒](monitoring/README.zh-CN.md) | 状态检查和提醒配置 |
| [本地基准报告](benchmarks/2026-10-26/README.zh-CN.md) | 受控 A/B/A、MOSS、Qwen 和算子测试 |
| [算子探针](benchmarks/operators/README.zh-CN.md) | 合成负载工具和测量限制 |
| [RTX 4090 历史报告](rtx4090-register-report.zh-CN.md) | 独立的上游单卡实验 |

本地受控 BF16/FP32 测得 **164.5 → 325.95 → 164.5 TFLOP/s**，即约 1.98 倍。
BF16 cuBLAS 8192³ 提升约 18.8%，4096³ 基本不变。
采用相同 offload 策略时，MOSS 历史训练吞吐对比提升约 11%。
NUMA 绑定、日志和其他条件也有变化，因此不能把全部提升归因于解锁。

近期相同配置的 Qwen C1 解码基本不变，已测输入长度下为 86–89 token/s。
Triton 对比属于独立的软件实现改进。

本机配置为 H13SSL-N BIOS 3.5、内核 `7.0.0-34-generic` 和定制 `nvidia-open-p2p/595.84`。
每张卡为 48 GiB，功耗上限为 450 W。
本次验收不覆盖其他主板、BIOS、原装 24 GiB 显卡或原版 595.84 驱动。
使用固定配置的诊断工具前，请先阅读硬件适配文档。

公开 wrapper 只准备文件，不安装或激活启动镜像。
下文根目录的安装目标仍采用上游打包流程。

## 文档写法

英文文档采用约 80% 程度的 ASD-STE100 风格。
这里的比例表示写法强度，不是实测合规分数，也不表示完全符合标准。
重写采用短句、直接指令和一致术语，保留专业名称、命令、寄存器值及证据边界。
参见 [ASD-STE100 官方规范](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf)。

每篇技术文档均提供对应中文版本。许可证声明保留原文。

## 独立的上游结果：GPU unlock 1.0.0

上游模块在原版 NVIDIA 驱动启动前应用 SM speed-select override。
其历史实验使用一张 `10de:2684` AD102 RTX 4090，完成了一次成功的冷上电。

| 模式 | 解锁前 | 解锁后 |
|---|---:|---:|
| FP16 → FP32 累加 | 165.6 TF/s | 331.6 TF/s |
| BF16 → FP32 累加 | 165.5 TF/s | 330.6 TF/s |

override 在 PCIe Function Level Reset（FLR）、原版 NVIDIA `615.78.08` 初始化和 CUDA 基准后仍然保留。
INT8、`dp4a` 和标量 FP32 保持在基线附近。
该固件实测发生于发布清理之前。
截至历史报告撰写时，清理后的模块仍待独立冷启动复现和应用数值验证。

后续本地实验采用不同硬件和定制驱动，属于单独的验收结果。
参见[历史报告](rtx4090-register-report.zh-CN.md)和[证据说明](docs/evidence/rtx4090/README.zh-CN.md)。

AD102 payload 和 debug-booter 分析来自 [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)。
Linux 集成源于 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)。公开 payload 是结果成立的关键。

## 支持目标和机制

RTX 4090 `10de:2684` 自动选择 AD102 资源。
模块保留原有 GeForce/CMP GA102/GA104 设备列表和 GA102 payload。
上游报告过 RTX 3090 成功；本次 AD102 工作没有重新验证所有旧型号。
模块拒绝其他 Ada ID、专业 RTX A 系列和数据中心型号。

共用 Ada 固件不能证明其他显卡受支持。

RTX 4090 流程运行签名固件，检查 payload marker 和所需权限。
随后写入 SS0 `0x88888888` 和 SS1 `0x8`，并在 NVIDIA 绑定前执行 FLR。
流程要求 FLR 前后的 effective speed-select readout 均符合预期。
这条上游路径不需要 NVIDIA 驱动补丁或 UEFI 应用。

本地 48 GiB 适配则另行依赖已有的定制 NVIDIA 驱动。
payload 的指令地址来自已公开的解密 debug-booter 分析。
GPU 在内部认证和解密 production booter。

## 构建和安装上游软件包

安装对应发行版的软件包及构建依赖：

```sh
make install-arch   # makepkg -sif
make install-deb    # apt-get build-dep, dpkg-buildpackage, apt-get install
make install-rpm    # dnf builddep, rpmbuild, dnf install
```

`make arch`、`make deb` 和 `make rpm` 只构建，不安装。
构建使用已提交的 `HEAD`；Debian 和 RPM 产物分别写入 `build/deb`、`build/rpm`。
请安装匹配的内核头文件和可用的 DKMS 工具链。

构建通过 HTTPS 下载固定的 NVIDIA `610.43.03` 输入，并核验 SHA-256。
`make inputs` 准备缓存；`make firmware` 从缓存生成资源；`make assets` 执行两者。
默认缓存为 `$HOME/.cache/gpu-unlock`。
可用 `CACHE=`、`INPUTS=` 和 `ASSETS=` 更改路径。

在干净 chroot 中构建 Debian 包时，将 `GPU_UNLOCK_INPUTS` 指向输入缓存。
`dpkg-buildpackage` 本身不下载输入。

`make dist` 归档、Debian 源码包和 `.nosrc.rpm` 均不包含 NVIDIA 归档或生成的固件。
输入和资源布局见[固件说明](firmware/README.zh-CN.md)。

## 启用上游启动路径

软件包将模块和固件加入 initramfs，在 NVIDIA 绑定前运行。
只有内核命令行选择目标后，模块才会启用：

```text
gpu_unlock.targets=0000:03:00.0
gpu_unlock.targets=0000:03:00.0,0000:04:00.0
gpu_unlock.targets=all
```

以上 PCI 地址仅为示例。请使用 `lspci -D` 输出的完整 PCI 名称。
`all` 选择所有受支持且未绑定的显卡，包括旧 GA102/GA104 目标。
选择单卡时使用明确地址。不要混用 `all` 和地址。
模块会记录并忽略无效条目。

软件包支持以下 initramfs 生成器：

- **mkinitcpio：** `/etc/mkinitcpio.conf.d/zz-gpu-unlock.conf` 将 `gpu_unlock` 放在 `MODULES` 中 `nvidia` 的前面。
  若无 NVIDIA，则放在末尾。安装时会重建镜像。
  自定义 `-c` 配置或 preset `_config` 会绕过 drop-in。
  此时请在该配置的 `MODULES` 中手动把 `gpu_unlock` 放到 `nvidia` 前。
- **initramfs-tools：** 使用 `/usr/share/initramfs-tools/modules.d/gpu-unlock.conf`。
- **dracut：** 使用 `/usr/lib/dracut/dracut.conf.d/gpu-unlock.conf`。

软件包不添加 `softdep nvidia pre:` 规则。
Kmod 只采用首条匹配的 soft dependency，因此可能与其他软件包冲突。

**首次尝试前，请完全关机，再开机。**
显卡必须处于本次上电后未被 GPU 驱动初始化的状态。热重启不能保证此状态。
模块跳过已绑定、已断电或启用 bus mastering 的显卡，并拒绝显示先前使用痕迹的固件状态。
NVIDIA 绑定后再手动加载模块不能解锁。

手动尝试冷卡解锁前，不要运行 `nvidia-smi`、CUDA、NVML 或 `nvidia-modprobe`。
这些工具可能按模块名加载 NVIDIA。普通 modprobe blacklist 不能阻止显式按名加载。
软件包的 initramfs 流程无需手动准备固件或设置研究参数。

上游流程在 FLR 前立即移除 firmware framebuffer；显示器会黑屏，直到 `nvidia-drm` 接管。
历史单卡实验没有验证显示接管或多卡运行。
本地双卡验收使用独立的 ASPEED 控制台。

## 检查或停用

启动后检查内核日志和 PCI 绑定：

```sh
journalctl -k -b | grep gpu_unlock
lspci -nnk -s 0000:03:00.0  # replace the example address
```

模块已加载或 `modprobe` 返回成功，均不能单独证明解锁成功。
每张目标卡都必须具备 `gpu_unlock: unlocked`、payload、selector 和 post-FLR 检查记录。
历史报告还提供独立寄存器和性能确认。
可选采样器位于 `diagnostics/peek`，CUDA 指令基准位于 `diagnostics/bench`。

固件事务运行期间，不要加载第二个 BAR0 采样器。

若固件未停止且模块保留 DMA 缓冲区，请先关机，再尝试。
固件可能仍在使用缓冲区；此时不要强制卸载模块。

要停用后续尝试，请从内核命令行移除 `gpu_unlock.targets=`。
只停用一次启动时，可在 bootloader 编辑器中移除它。
卸载软件包会删除模块和 initramfs 集成。
完全关机可恢复新鲜的硬件状态。

## 开发、归属和许可证

`make test` 运行不访问 GPU 的主机测试。
具备生成固件时，测试还会在模拟硬件上覆盖完整事务。
`make LLVM=1 -C kernel/gpu_unlock` 使用 LLVM 和当前内核头文件构建。

Linux 模块和打包源于 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)。
AD102 four-PLM payload 使用 [TOTORONG 的生成器和 debug-booter 分析](https://huggingface.co/TOTORONG/AD103_win_unlocker)。
GA102 V67 链源于 [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock)。
早期 CMP 工作、NVIDIA loader 代码、Nouveau 和 [envytools](https://github.com/envytools/envytools) 也为本工作提供依据。

模块、打包和 payload 集成采用 GPL-2.0-only。NVIDIA 固件仍采用自身条款。
来源及保留的声明见 [firmware/NOTICE.md](firmware/NOTICE.md) 和 [licenses/](licenses/)。
