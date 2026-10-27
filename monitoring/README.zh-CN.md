[English](README.md) | [简体中文](README.zh-CN.md)

# 只读开机和 SSH 提醒

已验收的本地安装使用开机服务和 Ubuntu PAM/MOTD hook。
状态健康时不显示警告；证据缺失或不一致时，显示警告和检查命令。
检查器不加载模块、不运行 CUDA kernel、不访问 MMIO，也不修改功耗或重启。
自动检查不依赖用户临时配置的免密 sudo。

## 配置和安装

示例配置故意保留不完整状态。
请填写本机 hostname、两个 GPU UUID，以及已审查启动文件的哈希。
填写完成前，验证必须失败。
固定内核、driver/module build 和部署版本必须与已验收安装一致。

验收新安装后，再更新对应检查值。不要删除检查来隐藏警告。

```sh
mkdir -p build
cp monitoring/config.example.json build/monitor-config.local.json
# Review and fill build/monitor-config.local.json locally.
sudo install -Dm755 monitoring/gpu_unlock_watch.py /usr/local/libexec/gpu-unlock-watch.py
sudo install -Dm755 monitoring/gpu-unlock-status /usr/local/bin/gpu-unlock-status
sudo install -Dm644 build/monitor-config.local.json /etc/gpu-unlock-watch.json
sudo install -Dm755 monitoring/99-gpu-unlock-watch /etc/update-motd.d/99-gpu-unlock-watch
sudo install -Dm644 monitoring/gpu-unlock-watch.service /etc/systemd/system/gpu-unlock-watch.service
sudo systemd-analyze verify /etc/systemd/system/gpu-unlock-watch.service
sudo systemctl daemon-reload
sudo systemctl enable --now gpu-unlock-watch.service
```

## 查看状态

```sh
gpu-unlock-status                  # unprivileged cache plus live module/binding checks
sudo gpu-unlock-status --json      # fresh complete evidence/configuration check
gpu-unlock-status --demo           # clearly marked warning demo; no status writes
journalctl -u gpu-unlock-watch.service -b
```

root 检查器要求当前 boot ID 的早期寄存器记录和逐卡成功日志。
早期记录必须具备校验和及 root 权限保护。
它还检查当前 module/NVML 标识、驱动/内核版本、GRUB 选择和启动镜像完整性。
只有模块已加载、显存容量正确或存在旧启动记录，均不足以通过检查。

输出会区分“下次启动配置警告”和“本次启动证据失败”。
已知仅在 profiler 期间出现的 `pSmIssueThrottleCtrl` 不支持查询断言，不算解锁失败。
Xid、GPU 掉线和解锁失败记录会触发警告。

非特权输出要求 root 缓存属于当前启动，且不超过 15 分钟。
登录 hook 会以 root 刷新缓存。
它会输出警告，但始终返回成功，因此不会拒绝登录。
`.hushlogin`、禁用 PAM/MOTD 或复用已认证的 SSH control connection，均可能抑制 MOTD。

非交互 SSH、SCP 和 SFTP 的标准输出保持不变。

## 验证和限制

已安装服务在当前启动运行过；新的交互式 SSH 登录也完成了检查。
私有 mount namespace 测试提供了不匹配的内核配置。
已安装 SSH hook 和开机命令随后自动报警，未修改主机配置或缓存。
19 个状态/通知测试在 Windows 和 Linux 上全部通过。

此次提醒验证没有另行进行物理重启来测试开机触发器。

提醒程序检查状态，不持续测量性能。
保存的解锁后 MMIO 记录，不能保证发现所有后续静默硬件变化。
登录时不会运行实时 MMA 或 MMIO 探针。

机制参考：[Ubuntu PAM/MOTD](https://ubuntu.com/server/docs/reference/other-tools/pam-motd/) 和
[systemd.service](https://www.freedesktop.org/software/systemd/man/258/systemd.service.html)。
