[English](README.md) | [简体中文](README.zh-CN.md)

# Read-only boot and SSH reminder

The accepted local installation uses a boot service and an Ubuntu PAM/MOTD hook.
Healthy status produces no warning. Missing or inconsistent evidence produces a warning and inspection commands.
The checker loads no module, runs no CUDA kernel, and accesses no MMIO.

It does not change power settings or reboot.
Automatic checks do not depend on temporary passwordless sudo for a user.

## Configure and install

The example configuration is intentionally incomplete.
Enter your hostname, two GPU UUIDs, and the hashes of your reviewed boot files.
Until these values are complete, verification must fail.
Keep the pinned kernel, driver/module build, and deployment revision consistent with the accepted installation.

After acceptance, update the checks for that installation. Do not remove checks to hide a warning.

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

## Inspect status

```sh
gpu-unlock-status                  # unprivileged cache plus live module/binding checks
sudo gpu-unlock-status --json      # fresh complete evidence/configuration check
gpu-unlock-status --demo           # clearly marked warning demo; no status writes
journalctl -u gpu-unlock-watch.service -b
```

The root checker requires checksummed, root-protected early register receipts and per-card success logs from the current boot ID.
It also checks current module/NVML identity, driver/kernel versions, GRUB selection, and boot-image integrity.
A loaded module, VRAM capacity, or old boot receipt alone is insufficient.
Output distinguishes a next-boot configuration warning from a current-boot evidence failure.

The known profiler-only `pSmIssueThrottleCtrl` unsupported-query assertion is not an unlock failure.
Xid, GPU drop-off, and unlock-failure records produce warnings.

Unprivileged output requires a root cache from this boot that is at most 15 minutes old.
The login hook refreshes the cache as root.
It prints warnings but always returns success, so it cannot deny login.
`.hushlogin`, disabled PAM/MOTD, or an existing authenticated SSH control connection can suppress MOTD.

Non-interactive SSH, SCP, and SFTP standard output stays unchanged.

## Validation and limits

The installed service ran on the current boot. A fresh interactive SSH login also passed the check.
A private mount-namespace test supplied a mismatching kernel configuration.
The installed SSH hook and boot command then warned automatically, without changing the host configuration or cache.

All 19 state/notification tests passed on Windows and Linux.
This reminder validation did not include a new physical reboot to test the startup trigger.

The reminder checks state. It does not continuously measure performance.
Stored post-unlock MMIO receipts cannot prove detection of every later silent hardware change.
Login runs no live MMA or MMIO probe.

References: [Ubuntu PAM/MOTD](https://ubuntu.com/server/docs/reference/other-tools/pam-motd/) and
[systemd.service](https://www.freedesktop.org/software/systemd/man/258/systemd.service.html).
