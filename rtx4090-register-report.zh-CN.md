[English](rtx4090-register-report.md) | [简体中文](rtx4090-register-report.zh-CN.md)

# RTX 4090 AD102 历史实验

**2026-10-23，一张 RTX 4090 的 FP16/BF16 Tensor、FP32 累加吞吐约翻倍。**
override 在 FLR、原版 NVIDIA 初始化和 CUDA 负载后仍然保留。

| 指令模式 | 基线 | 解锁后，20k 迭代 | 解锁后，40k 迭代 |
|---|---:|---:|---:|
| FP16 / FP32 累加 | 165.6 TF/s | **331.6 TF/s** | **330.8 TF/s** |
| BF16 / FP32 累加 | 165.5 TF/s | **330.6 TF/s** | **330.3 TF/s** |
| FP16 / FP16 累加 | 325.7 TF/s | 306.3 TF/s | 331.6 TF/s |
| INT8 / INT32 累加 | 661.6 TOP/s | 661.4 TOP/s | 659.5 TOP/s |
| `dp4a` | 164.5 TOP/s | 164.4 TOP/s | 164.1 TOP/s |
| 标量 FP32 `ffma` | 79.1 TF/s | 79.1 TF/s | 79.1 TF/s |

AD102 payload 及构建分析来自 [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)。
Linux loader 和启动打包源于 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)。
本工作集成公开 payload、选择 AD102 资源、增加事务检查，并测量 RTX 4090。
本工作不主张发现 AD102 链。

## 历史报告范围

本报告覆盖一张实体卡、一次成功冷上电。
基线采集早于该次上电，不是在成功解锁启动中原位取得的基线。
两次测量使用相同 kernel、launch geometry、计时方法和构建参数。
成功固件实测发生于发布清理前。

截至历史报告日期，清理后模块有主机验证，但尚无独立硬件确认。
独立冷启动复现和代表性数值负载验证仍待完成；清理后的模块保留正常 `targets=` 接口。

后续[本地双卡实验](benchmarks/2026-10-26/README.zh-CN.md)采用不同硬件、内核和驱动。
它不能追溯算作此历史原版驱动实验的复现。
[证据说明](docs/evidence/rtx4090/README.zh-CN.md)提供原始基准文本和选取的脱敏寄存器日志。
这些摘录不是完整机器日志。

## 1. 配置和输入

| 项目 | 值 |
|---|---|
| 设备 | NVIDIA GeForce RTX 4090, `10de:2684`, AD102, 128 个 SM，compute capability 8.9 |
| 芯片寄存器 | `PMC_BOOT_0 = 0x192000a1` |
| 内核 | Linux `7.2.4` |
| 确认用驱动 | 未修改的 NVIDIA `615.78.08` |
| 生成固件的输入 | 固定的 NVIDIA `610.43.03` 源码和二进制包 |
| AD102 payload | `v67-ad102-610.43.03-four-plm.bin`, 64,000 字节 |
| Payload SHA-256 | `44c36b2d6b3424e53e18f3e55db85c833655de071ce66ce42749588a4a7dc8cb` |
| Booter 资源 | `booter_load_ad102.bin`, 57,672 字节 |
| Booter SHA-256 | `6ee05b20e1dc244c08c052f36ef28469b8d09f4955d1fe33e48a179e11a7fd49` |
| 基准构建 | `nvcc -O3 -arch=sm_89` |
| 功耗上限 / 报告的最大 SM 时钟 | 450 W / 3135 MHz |

执行前，全部九个生成资源与 manifest 固定哈希一致。
复现的 AD102 payload 还与公开生成器及附带 payload 逐字节一致。
完整性检查见 [generate_v67.py](firmware/generate_v67.py)、[extract_boot_assets.py](firmware/extract_boot_assets.py) 和 [manifest](firmware/artifacts-610.43.03.json)。
[NOTICE.md](firmware/NOTICE.md)记录许可证和固定的上游版本。

## 2. 机制

冷卡及仅完成 FWSEC-FRTS 后，主机直接写 feature 权限和 speed selector 均无效。
缺少的是由具备所需权限的认证固件执行的受保护寄存器写入。

AD103 项目公开了基于已解密 debug-booter 分析的 AD102-family V67 数据 payload。
其中的指令地址提供了所需的明文推导信息。
Linux 模块加载未修改的签名 production booter；SEC2 在 GPU 内认证和解密它。
构造的 signature data 覆盖 stack slot，将返回重定向到 booter 内已有的认证指令。

这些指令执行受保护写入；主机没有向认证镜像加入可执行代码。

成功运行表明所选地址适用于已测 production booter。
它不能证明 debug 与 production 的完整明文镜像相同。
此仓库不分发已解密固件镜像。

事务顺序如下：

1. 认领符合条件的冷卡，保存 PCI 状态，分配 DMA 缓冲区。
2. 在 GSP Falcon 上运行板载 ROM 的签名 FWSEC-FRTS，建立 firmware reservation。
3. 在 SEC2 上用构造的 V67 signature data 启动签名 AD102 booter。
   链依次作用于 WPR_CFG、FBPA、WPR、FEAT 权限，请求 mailbox marker `0x67b00001`，随后停止。
4. 主机写 selector 前，要求 marker、SEC2 HALT、可访问的 PCI/BAR，以及预期 WPR_CFG/WPR/FEAT 权限。
5. 应用 SS0 `0x88888888` 和 SS1 `0x8`，检查读回，并要求九个 effective speed-select 字段均为零。
6. 执行 PCIe FLR，检查 reset containment 和 FEAT/selector 保留状态，恢复 PCI 并释放资源。
7. 初始化原版 NVIDIA 驱动，检查寄存器，并测量相同指令模式。

公开模型中的写入顺序为 WPR_CFG（`0x1fa7cc`）、FBPA（`0x9a0148`）、WPR（`0x1fa7c4`）、FEAT（`0x823804`）。
权限变化和终止 marker 支持链已执行；没有独立总线追踪确认内部 store 顺序。
FBPA 未变化，也不是成功的必需判据。

payload 共 `0xfa00` 字节，由重复的 `0x0000019c` word 组成，在 `0xf948` 到 `0xf9fc` 间打补丁。
文件偏移 `0xf94c`、`0xf950` 分别为 canary 和 return slot。
按模型复制基址 `0x600`，它们对应 DMEM `0xff4c`、`0xff50`。
AD102 FEAT target word 位于文件偏移 `0xf9cc`，GA102 使用 `0xf960`。

文件偏移与 DMEM 地址属于不同坐标。

## 3. 观察到的固件事务

成功事务前未加载 NVIDIA 驱动。
该次上电恰好执行一次 FWSEC start、一次 AD102 SEC2 start 和一次 FLR。
legacy capture 和 host-write probe 均关闭；公开模块已移除这些研究路径。

| 阶段 | 所需证据 | 观察结果 |
|---|---|---|
| 资源完整性 | payload 和 booter 与固定哈希一致 | 通过 |
| 冷状态 | 无绑定驱动、bus mastering 关闭、WPR2 关闭、FEAT 权限关闭 | 通过 |
| FWSEC | scratch `0`，符合预期的 FRTS/WPR2 reservation | 通过 |
| Payload | marker `0x67b00001`、SEC2 HALT、所需权限、PCI/BAR 可访问 | 通过 |
| Selector | SS0/SS1 `0x88888888`/`0x8`，effective readout 为零 | 通过 |
| 复位 | FLR `0`，FEAT/selector 保留，WPR2 关闭，DMA 已隔离 | 通过 |
| 驱动 | 原版驱动初始化后 FEAT/selector/readout 值相同 | 通过 |
| 性能 | 提升超出基线波动，并有标量/整数对照 | 通过 |

FWSEC 返回 scratch `0`、WPR2 low/high `0x05ff2000:0x05ff2e00`。
SEC2 启动约 234 ms 后，payload gate 完成，报告 mailbox `0x67b00001`、CPUCTL `0x10` 及所需权限。
随后主机 selector 写入将 effective readout 从 `0x00410080` 变为零。

| 寄存器 | 冷状态 | payload 后、selector 前 | FLR 和模块卸载后 |
|---|---|---|---|
| WPR_CFG PLM `0x001fa7cc` | `0x0004cb8f` | `0xfffff0ff` | `0x0004cb8f` |
| FBPA PLM `0x009a0148` | `0xffffff0f` | `0xffffff0f` | `0xffffff0f` |
| WPR PLM `0x001fa7c4` | `0x0004cb8f` | `0xffffffff` | `0x0004cb8f` |
| FEAT PLM `0x00823804` | `0xffffff8f` | `0xffffffff` | `0xffffffff` |
| SS0 `0x0082381c` | `0x44023025` | `0x44023025` | `0x88888888` |
| SS1 `0x00823820` | `0x00000007` | `0x00000007` | `0x00000008` |
| Effective readout `0x00823818` | `0x00410080` | `0x00410080` | `0x00000000` |

冷状态与独立卸载后采样之间，31 个 feature-cluster word 中只有四个变化：FEAT PLM、SS0、SS1 和 effective readout。
OTP word 中 `FMLA32`、`IMLA2`、`IMLA4` 仍为 `1`。
这是 feature override，不是重写 OTP fuse。
FLR 恢复 WPR、WPR_CFG，而 FEAT 保持 override。

FBPA 不变不能证明该次 store 无必要，也不能证明寄存器物理只读。

模块恢复 PCI command `0x3`，检查 GSP HALT、WPR2 关闭及无待处理事务，释放 DMA，且未保留模块引用。
模块卸载完成后才进行独立只读采样。
随后原版 NVIDIA `615.78.08` 初始化 GPU。
驱动初始化和 CUDA 基准后的采样均显示 FEAT PLM `0xffffffff`、SS0 `0x88888888`、SS1 `0x8`、effective readout 为零。

收集的确认阶段内核日志中未发现 NVIDIA Xid/error。

参见 [registers.txt](docs/evidence/rtx4090/registers.txt)。
模块加载返回成功本身不足以证明解锁；逐卡错误可能只记日志，不使模块初始化失败。
本结果依据阶段读回和独立采样。

## 4. 基准方法和限制

[CUDA 基准](diagnostics/bench/mma_bench.cu)测量指令发射吞吐，不是端到端 GEMM 或应用速度。
计时循环将操作数和 accumulator 保持在寄存器中，循环内无内存流量。
方法如下：

- FP16/FP16、FP16/FP32、BF16/FP32、INT8/INT32 使用 WMMA m16n16k16。
- 每 warp 有八条独立 Tensor accumulator chain；标量 `dp4a`、FP32 FMA 使用 32 条 chain。
- 在 128 个活跃 SM 上运行 1,056 个 block，每 block 256 thread，即八个 warp。
- 每次 CUDA-event 计时 launch 前预热一次；每模式计时三次，报告最佳值。
- 基线和首次解锁运行各 20,000 次迭代，解锁复测为 40,000 次。

发布清理只修改历史注释；kernel、launch geometry、操作计数、计时和参数均与实测一致。
完成解锁和驱动接管后，在 CUDA、NVIDIA 已加载的环境运行：

```sh
mkdir -p build
nvcc -O3 -arch=sm_89 -o build/mma_bench diagnostics/bench/mma_bench.cu
build/mma_bench 20000 3
build/mma_bench 40000 3
```

每次 multiply-accumulate 计两次操作。
每个 WMMA call 按每 warp `16 × 16 × 16 × 2 = 8192` 次操作计算；`dp4a` 和标量 FMA 按 lane 计数。
程序所有模式均输出 `TF/s`，报告将整数结果改标为 `TOP/s`，不使用 sparsity 倍率。

生成代码检查在各循环中发现了预期指令：
`HMMA.16816.F16`、`HMMA.16816.F32`、`HMMA.16816.F32.BF16`、`IMMA.16816.S8.S8`、`IDP.4A.S8.S8`、`FFMA`。
更早的 10k、20k、40k 基线运行显示 FP32 累加、整数、标量速率稳定，支持确有计时工作而非被编译器删除。
accumulator 保持 live 以阻止消除；程序不将其数值与参考结果比较。

主要原始样本见 [baseline.txt](docs/evidence/rtx4090/baseline.txt)、
[unlocked-20000.txt](docs/evidence/rtx4090/unlocked-20000.txt)、[unlocked-40000.txt](docs/evidence/rtx4090/unlocked-40000.txt)。

| 模式 | 基线各次结果 | 解锁后 20k 各次结果 | 解锁后 40k 各次结果 |
|---|---|---|---|
| FP16 / FP16 | 306.3 / 306.3 / 325.7 | 306.3 / 306.3 / 306.3 | 331.6 / 331.6 / 330.9 |
| FP16 / FP32 | 165.6 / 165.6 / 165.6 | 331.6 / 331.6 / 331.6 | 330.8 / 330.8 / 330.8 |
| BF16 / FP32 | 165.4 / 165.5 / 165.5 | 329.5 / 330.6 / 329.6 | 330.3 / 328.3 / 328.2 |
| INT8 / INT32 | 661.5 / 661.6 / 661.4 | 661.4 / 661.3 / 661.3 | 659.5 / 659.4 / 659.4 |
| `dp4a` | 164.5 / 164.5 / 164.5 | 164.4 / 164.4 / 164.4 | 164.1 / 164.0 / 164.1 |
| 标量 FP32 | 79.1 / 79.1 / 79.1 | 79.1 / 79.0 / 79.1 | 79.0 / 79.1 / 79.1 |

20k 最佳样本中，FP16/FP32 提升 **2.002×**，BF16/FP32 提升 **1.998×**；更长复测确认了提升。
首组 FP16/FP16 在解锁前后均受时钟爬升影响，更长解锁运行达到 331.6 TF/s。
INT8、`dp4a`、标量 FP32 保持基线附近；结果不支持 INT8 吞吐翻倍。

两次解锁运行按 100 ms 间隔得到 32 个遥测样本，其中 26 个利用率非零。
活跃样本的 SM 时钟为 2550–2760 MHz、显存 10251 MHz、功耗 23.81–224.89 W、温度 35–52 °C。
低功耗值包含进入负载的过渡，采样不是逐 kernel 峰值。
功耗上限仍为 450 W，报告的最大 SM 时钟仍为 3135 MHz。

此次比较没有修改功耗上限、时钟设置或 NVIDIA 驱动代码。

## 5. 寄存器参考和早期观察

以下均为 BAR0 偏移。名称采用[公开 Ampere/CMP 参考](https://gist.github.com/nvlight/813a866dc69d417497a427f4208321ff)。
实验测量了这些偏移的值，但没有独立确认所有名称或字段映射。

| 偏移 | 名称 | 冷状态值 / 解释 |
|---|---|---|
| `0x00820000` | FUSECTRL | `0xe0040000` |
| `0x008200fc` | FUSE_SS_PLM | `0xffffffff` |
| `0x0082038c` | SECURE_FEAT_OVR_QUADRO_WR_SECURE | `1` |
| `0x0082059c` | FUSE_SS_FFMA | `0` |
| `0x008207d4` | FUSE_SS_FMLA16 | `0` |
| `0x008207d8` | FUSE_SS_FMLA32 | `1` |
| `0x008207dc` / `0x008207e0` | FUSE_SS_IMLA0 / IMLA1 | `0` / `0` |
| `0x008207e4` / `0x008207e8` / `0x008207ec` | FUSE_SS_IMLA2 / IMLA3 / IMLA4 | `1` / `0` / `1` |
| `0x00823804` | FEAT_OVR_PLM | `0xffffff8f`, 权限门控 |
| `0x00823814` | FEAT_READOUT_0 | `0x00000233` |
| `0x00823818` | FEAT_READOUT_1 | `0x00410080`, 九个 3-bit 字段，mask 为 `0x07ffffff` |
| `0x0082381c` | FEAT_OVR_SM_SPEED_SELECT | `0x44023025` （成功上电时） |
| `0x00823820` | FEAT_OVR_SM_SPEED_SELECT_1 | `0x7` |
| `0x00409664` / `0x00409668` | FECS selector / readout 副本 | `0xbadf5040` （冷状态及驱动绑定后） |
| `0x00504204` | SM_ISSUE_RATE_MODIFIER | `5`, （驱动未改变） |
| `0x001fa824` / `0x001fa828` | WPR2 low / high | `0x1ffffe00` / `0`（冷状态） |
| `0x00824140` / `0x008241e0` | booter / FWSEC fuse | `1` / `1` |

冷状态 `FEAT_READOUT_1` 从低字段到高字段解码为 `0 0 2 0 0 2 0 2 0`。
三个降速字段与具名 FMLA/IMLA fuse word 的对应关系尚未确定。
SS0 每个 nibble 的 bit 3 为 enable，其余三位为值；`8` 表示启用零值 override。
SS1 使用 4-bit selector，未单独测量其性能影响。

更早上电中，冷状态 SS0 的高字节会变化，但所有 override enable bit 均关闭；其含义尚未确认。

SEC2、FBIF、Falcon2 window 分别为 `0x00840000`、`0x00840600`、`0x00841000`。
GSP 对应地址为 `0x00110000`、`0x00110600`、`0x00111000`。
Falcon CPUCTL 偏移 `0x100` 用 `0x10` 表示 HALT；mailbox0/1 为 `0x040`/`0x044`。
EXIT 本身不能证明 payload 执行；负对照即使拒绝 host-written 指令也产生 EXIT。

必须同时具备明确 marker、HALT 和独立权限读回。

早期有界实验观察如下：

- 签名 payload 前，主机 PLM/selector 写入无效，包括仅成功完成 FWSEC-FRTS 后。
- GA102 booter 停止，但未开放 AD102 FEAT 权限；已展示结果需要 AD102 booter 和链。
- 已测 SEC2 模式未执行未签名 host microprogram。
  self-loop、DMEM store 和指令计时对照均无执行迹象，尽管存在 EXIT。
- 已测 PIO/DMA/tag/port 路径未提取出加载的 secure IMEM。
  secure read 返回 `0xdead5ec1`；可读 plain block 不能作为可执行代码取指；ROM 检查未得到 Falcon 明文镜像。
- 更早冷状态与驱动后采样中，31 个 feature-cluster word 不变。
  成功解锁进一步表明原版初始化保留已修改的 FEAT/selector 状态。

这些观察不能证明所有提取或认证攻击都不可能。
公开模块不包含研究 probe 和 capture 模块。

已测 AD102 booter 的 image size 为 `0xde00`，OS data 为 `0x7e00`/`0x6000`，application code offset/size 为 `0x100`/`0x7d00`。
signature patch offset 为 `0x7e10`。
GSP boot image 为 36,864 字节，descriptor code 为 `0x4800`、data 为 `0x800`。
ROM FWSEC DMEM 长度为 `0xd80`，需要向上取整为 14 个 256-byte DMA block。

传输检查必须允许此未对齐长度，同时检查取整后的边界。

## 6. 公开模块和复现

[README](README.zh-CN.md)说明软件包及 opt-in `gpu_unlock.targets=` 接口。
RTX 4090 `10de:2684` 自动选择 AD102 资源；已支持旧 GA102/GA104 ID 保留原路径，拒绝其他 Ada ID。
共用 Ada booter 归档不能证明每款 Ada 都能安全有效运行。

模块要求未绑定、已供电的卡、关闭 bus mastering，以及本次上电后符合条件的固件状态。
marker、HALT 或权限不符时，模块在应用 selector 前停止。
模块检查 FLR 前后 selector 读回和 effective readout，并检查 PCI identity、BAR 稳定性和 reset containment。
不可访问的全 1 MMIO 值，不能单独视为权限已开放。

若固件仍可能访问 DMA，且 reset containment 无法确认，模块会保留缓冲区和引用直到关机。
此时不要强制卸载。成功实测释放了这些资源；保留资源属于失败路径，不是正常接管的一部分。

复现前完全关机，让 initramfs 模块先于所有 GPU 驱动运行。
不要用 `nvidia-smi`、CUDA、NVML 或 `nvidia-modprobe` 检查解锁前状态；它们可能按名加载 NVIDIA。
普通 modprobe blacklist 不能阻止此行为。
保留内核日志，检查每个事务阶段。

`gpu_unlock` 运行时，不要用其他实验模块映射 BAR0。

历史实验在模块卸载后、以及后续 NVIDIA 绑定后进行了独立采样。
本地适配的另一工具 `gpu_cold_probe` 仅允许在驱动前运行；不要在 NVIDIA 已占用的 GPU 上运行它。

成功 FLR 接管后，初始化原版驱动，独立读取 selector 和 effective readout，再运行基准。
固件运行失败或保留资源后，必须关机再重试。
热重启不能保证新鲜冷卡状态。本报告不主张 override 能跨断电保留。

实验阶段通过 13 个主机测试，以及模块、只读采样器的 LLVM 构建。
测试覆盖完整模拟 AD102 事务，以及 marker、权限、HALT 顺序、selector、effective readout 等失败。
还覆盖 payload copy 损坏、metadata race 和 DMA 保留。
发布清理删除研究参数和 capture 路径，保留正常事务检查。

该历史清理版本通过九个主机测试，其中包括七个 C 组件和完整模拟 GA102/AD102 事务，还通过 LLVM 模块及采样器构建。
主机测试和构建不能替代硬件复现。

## 7. 归属和未完成工作

关键 AD102 参考为 [TOTORONG/AD103_win_unlocker](https://huggingface.co/TOTORONG/AD103_win_unlocker)，
包括 `source/firmware-tools/ad102_payload.py`、`docs/ANALYSIS.en.md`、booter 反汇编摘录和附带 four-PLM payload。
该项目在 RTX 4080/AD103 上报告 FP32 累加吞吐约翻倍。
这些外部结果用于归属和背景，不是本张 RTX 4090 的测量。

Linux 模块源于 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock)，GA102 V67 渊源包括 [WildFlash1st/cmp90hx-unlock](https://github.com/WildFlash1st/cmp90hx-unlock)。
Nouveau Falcon/GSP loader、NVIDIA open-module 源码和 [envytools](https://github.com/envytools/envytools) 支持了加载及寄存器分析。
来源、固定哈希及保留的 GPL/MIT 声明见 [NOTICE.md](firmware/NOTICE.md)、[manifest](firmware/artifacts-610.43.03.json)、[licenses/](licenses/)。
NVIDIA 固件继续采用自身条款。

截至历史报告日期，后续验证包括清理模块的独立冷上电复现、参考数值负载和更长持续负载。
未解技术问题仍包括 readout 字段映射、SS1 独立作用、各次 WPR/WPR_CFG/FBPA store 的必要性、
AD102 scrubber reservation 规则，以及已测 booter/显卡之外的兼容性。
