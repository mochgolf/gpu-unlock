# Read-only boot / SSH unlock reminder

The accepted local deployment runs a boot service and an Ubuntu PAM/MOTD hook.
Healthy status is quiet; missing or inconsistent unlock evidence prints a
warning and inspection commands. It does not load modules, run CUDA kernels,
touch MMIO, change power or reboot. Automatic checks do not depend on a user's
temporary passwordless-sudo rule.

The same logic is published here, with a deliberately incomplete example
configuration: **fill in your hostname, two GPU UUIDs and the hashes of your
reviewed boot files**. Until that is done, the example must fail verification.
Keep the pinned kernel, driver/module build and deployment revision aligned
with what you actually accepted. These are checks to update after acceptance,
not restrictions to remove to suppress an alert.

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

```sh
gpu-unlock-status                  # unprivileged cache plus live module/binding checks
sudo gpu-unlock-status --json      # fresh complete evidence/configuration check
gpu-unlock-status --demo           # clearly marked warning demo; no status writes
journalctl -u gpu-unlock-watch.service -b
```

The root checker combines this boot ID's checksummed, root-protected early
register receipts and per-card success logs with current module/NVML identity,
driver/kernel versions, GRUB selection and boot-image integrity. A loaded
module, VRAM size or old boot receipt is insufficient. A next-boot configuration
warning is distinguished from a current-boot evidence failure. The known
profiler-only `pSmIssueThrottleCtrl` unsupported-query assertion is not treated
as an unlock failure; Xid/drop-off/unlock-failure records are warnings.

Unprivileged manual output requires a root cache from this boot, at most 15
minutes old. The login hook refreshes it as root, outputs warnings but always
returns success so monitoring cannot deny a login. `.hushlogin`, disabled
PAM/MOTD, or reusing an authenticated SSH control connection can suppress MOTD.
Non-interactive SSH/SCP/SFTP standard output is not modified.

Native validation: the installed service was run on the current boot; a fresh
interactive SSH login was exercised. In a private mount namespace, a mismatching
kernel configuration made the installed SSH hook and boot command automatically
warn without modifying host configuration/cache. The 19 state/notification tests
also passed on Windows and Linux. A new physical reboot was not performed just
to test the reminder's startup trigger.

This is a lightweight state monitor, not continuous performance verification.
Stored post-unlock MMIO receipts do not prove that every later silent hardware
change will be detected. No live MMA or MMIO probe runs on login.

Mechanism references: [Ubuntu PAM/MOTD](https://ubuntu.com/server/docs/reference/other-tools/pam-motd/),
[systemd.service](https://www.freedesktop.org/software/systemd/man/258/systemd.service.html).
