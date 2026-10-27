[English](README.md) | [简体中文](README.zh-CN.md)

# Supermicro H13SSL-N：双 48 GiB AD102

此适配包含 mochgolf 已实测的本地修改。
基础版本为 `elias-gaeros/gpu-unlock` 提交 `4ec490d49c1cc292c0b4cd5ce5a801b5d2c396dc`。
AD102 payload 和原始 `gpu_unlock` 模块保持不变。
已验收路径在原始解锁模块前加载独立诊断模块，清除平台遗留的 BME。

开发期间还离线审查过另一份 hardened-BME 补丁。
该补丁未用于已验收的 A/B/A 或双卡部署；此适配也不使用它替换原始模块。

## 已测配置

| 组件 | 原生验收配置 |
|---|---|
| 主板 / BIOS | Supermicro H13SSL-N / 3.5 |
| GPU | 两张 AD102 `10de:2684`，改装 48 GiB，每张报告 49,140 MiB |
| PCI function | `0000:41:00.0`、`0000:01:00.0` |
| 控制台 | ASPEED `0000:c6:00.0`；两张 NVIDIA 均非 boot VGA |
| 内核 | `7.0.0-34-generic` |
| 驱动 | 本地定制 `nvidia-open-p2p/595.84`，支持 48 GiB/P2P；**不是原版 595.84** |
| 默认功耗 | 每卡 450 W；部署未修改此值 |
| 固件生成 | 上游固定的 610.43.03 资源 |

DMI、BIOS、容量和 PCI 检查仍固定到上述配置。
验收不覆盖类似主板、其他 BIOS、原装 24 GiB 卡或其他插槽布局。
独立的 NVIDIA 驱动补丁是已有依赖，不包含在此仓库中。

## 组件和行为

- `gpu_bme_diag.c` 和 `bme_diag_core.h` 每次处理一个明确指定的 function。
  它们要求未绑定、D0 的 AD102、已测冷固件状态，以及无待处理事务。
  若 PCI command 为 7，诊断模块只写入一次 3，随后读回。
  其他已采样状态必须不变。
  模块不启动固件、不分配 DMA、不复位设备、不绑定驱动，也不写 Tensor selector。
  写入结果不确定时立即停止；重试不会重新启用传入固件的 MASTER。
- `gpu_cold_probe.c` 使用上游纯解析器及只读 BAR/config 映射收集驱动前状态。
  **不要在 NVIDIA 已占用的 GPU 上运行此工具。** 提醒程序使用启动时保存的记录。
- `initramfs/experiment_init_top.sh` 实现已验收的双卡流程、成功检查和失败停止。
  它必须先于原始 udev trigger 运行，且 NVIDIA、nouveau 模块均未加载。
- `initramfs/persist_early.sh.in` 保留已部署的持久化逻辑。
  仅将私有 root 设备和 UUID 替换为必填占位符。
- `initramfs/verify_unlock_log.sh` 要求每张卡都具备成功、清理、FLR 和 selector 保留证据。
  `insmod` 返回成功本身不足以验收。
- `stage_overlay.py` 是经过离线验证的新公开 wrapper。
  它填充 root 占位符、验证模块/固件输入，并准备全新目录。
  它不安装镜像，也不修改 GRUB。
- `provenance.json` 记录哈希，并区分原生实测源码和参数化发布模板。

若在硬件动作前未通过冷状态检查，hook 可返回原始 udev 流程。
它会记录 `stock-fallback-no-hardware-action`，这不表示解锁成功。
发生硬件动作后，任何失败都会停止后续启动并保存证据。
fallback 分支通过了 chroot 测试。

本机已测热重启满足冷状态检查，并完成了完整解锁。
尚未在真实硬件上强制触发非冷状态 fallback 分支。

## 构建和离线检查

在仓库根目录准备匹配头文件、C 编译器和上游生成固件，然后运行：

```sh
make test ASSETS=/path/to/generated/610.43.03/assets
make -C kernel/gpu_unlock KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl KDIR=/lib/modules/7.0.0-34-generic/build
make -C ports/supermicro-h13ssl test
```

测试包含 21 个 BME 事务/故障用例、19 个提醒测试。
存在固件资源时，还会执行 42 个 fake-PCI 采集/证据检查。
这些测试不访问真实 PCI 设备。
没有生成固件的 CI 会明确跳过 42 用例的 collector fixture。

主机测试结果不能替代硬件验收。

准备 overlay 前，请审查二进制文件并取得其 SHA-256。
仅匹配 vermagic 不足以确认二进制可信。
使用已审查输入填写以下示例：

```sh
python3 ports/supermicro-h13ssl/stage_overlay.py \
  --output build/h13ssl-overlay \
  --root-device /dev/REPLACE_WITH_ROOT_PARTITION \
  --root-uuid REPLACE_WITH_ROOT_FILESYSTEM_UUID \
  --firmware-assets /path/to/generated/assets \
  --unlock-module kernel/gpu_unlock/gpu_unlock.ko \
  --unlock-sha256 REPLACE_WITH_REVIEWED_SHA256 \
  --diag-module ports/supermicro-h13ssl/gpu_bme_diag.ko \
  --diag-sha256 REPLACE_WITH_REVIEWED_SHA256 \
  --cold-probe build/h13ssl/gpu_cold_probe
```

## 启动镜像要求

原始部署使用单独构建的镜像，保留原始 microcode 前缀和全部 initramfs 文件。
它在 `scripts/init-top/ORDER` 中将 `00_gpu_ab` 插到原始 `udev` 前。
可见的 safe-A 启动项保持不变，并保留独立控制台恢复能力。

持久化 hook 运行前，固定 root 分区上必须已有 `/var/backups/gpu-unlock-ab-events`。
此目录必须归 root 所有，权限为 0700。
把 overlay 复制到运行中的机器，不等于完成安装。

公开 wrapper 和模板渲染通过了离线及构建检查。
发布时没有安装它们，也没有再次执行固件。
源事务和启动流程仅在上述配置完成原生验收。

## 验收和性能

冷锁定 A1、解锁 B1、再次冷锁定 A2 确认了目标性能提升。
第二张实体卡始终锁定，作为对照。
后续双卡部署通过原生检查、普通热重启和冷启动。
测量值、负面结果和应用限制见[基准报告](../../benchmarks/2026-10-26/README.zh-CN.md)。

可选[开机/SSH 提醒](../../monitoring/README.zh-CN.md)报告缺失或失败证据，不再次执行硬件事务。
