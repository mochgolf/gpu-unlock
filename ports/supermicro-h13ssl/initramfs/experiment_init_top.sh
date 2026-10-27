#!/bin/sh
set -eu
case "${1:-}" in prereqs) exit 0;; esac
out=/run/initramfs/gpu-ab
mkdir -m 0700 "$out"
cat /proc/sys/kernel/random/boot_id > "$out/boot_id"
stop_boot() {
    echo "$*" > "$out/failure-reason"
    dmesg > "$out/kernel-failure.log" || true
    /gpu-ab/persist_early.sh failure || echo 'GPU-AB failure persistence unavailable' > /dev/console
    echo "GPU-AB STOP: $*; no NVIDIA handoff. Select the first GRUB safety A entry for recovery; the persistent default is dual unlock." > /dev/console
    cat "$out/failure-reason" "$out/cold.json" "$out/normalized.json" 2>/dev/null > /dev/console || true
    dmesg | tail -100 > /dev/console || true
    while :; do sleep 10; done
}
grep -q 'gpu_deploy.revision=dual-v1' /proc/cmdline || stop_boot wrong-revision
echo dual-production-v1 > "$out/mode"
echo dual-v1 > "$out/revision"
/gpu-ab/sha256sum -c /gpu-ab/SHA256SUMS > "$out/integrity.log" 2>&1 || stop_boot integrity
for module in nvidia nouveau gpu_unlock gpu_peek gpu_bme_diag; do
    [ ! -d "/sys/module/$module" ] || stop_boot unexpected-module
done
[ "$(cat /sys/bus/pci/devices/0000:41:00.0/boot_vga)" = 0 ] || stop_boot target-boot-vga
[ "$(cat /sys/bus/pci/devices/0000:01:00.0/boot_vga)" = 0 ] || stop_boot control-boot-vga
if ! /gpu-ab/gpu_cold_probe --cold-candidate "$out" > "$out/cold.json" 2> "$out/probe.stderr"; then
    # A persistent default must also permit ordinary warm boots. Before any PCI
    # command/firmware action, a non-cold card can safely take the original udev
    # path. This is a stock-driver fallback, never reported as unlock success.
    dmesg > "$out/kernel-before-action.log"
    /gpu-ab/persist_early.sh pre || stop_boot fallback-pre-persistence
    echo stock-fallback-no-hardware-action > "$out/early-status"
    echo "<4>GPU-DEPLOY STOCK FALLBACK: cold preconditions unavailable; no PCI command or firmware action; original udev handoff" > /dev/kmsg
    /gpu-ab/persist_early.sh handoff || stop_boot fallback-handoff-persistence
    exit 0
fi
dmesg > "$out/kernel-before-action.log"
/gpu-ab/persist_early.sh pre || stop_boot pre-action-persistence
for bdf in 0000:41:00.0 0000:01:00.0; do
    insmod /gpu-ab/gpu_bme_diag.ko target=$bdf allow_clear=1 >> "$out/diag.stdout" 2>> "$out/diag.stderr" || stop_boot diagnostic-init-$bdf
    dmesg > "$out/diag.log"
    [ "$(grep -Fc "$bdf: gpu_bme_diag: QUALIFIED target=$bdf only" "$out/diag.log")" = 1 ] || stop_boot diagnostic-proof-$bdf
    rmmod gpu_bme_diag || stop_boot diagnostic-unload
    [ ! -d /sys/module/gpu_bme_diag ] || stop_boot diagnostic-still-loaded
done
/gpu-ab/gpu_cold_probe --post-bme-diag "$out" > "$out/normalized.json" 2> "$out/normalized.stderr" || stop_boot normalized-state
/gpu-ab/persist_early.sh normalized || stop_boot normalized-persistence
    /gpu-ab/persist_early.sh b-begin || stop_boot pre-firmware-persistence
    insmod /gpu-ab/gpu_unlock.ko targets=0000:41:00.0,0000:01:00.0 > "$out/insmod.stdout" 2> "$out/insmod.stderr" || stop_boot unlock-insmod
    dmesg > "$out/unlock.log"
    /gpu-ab/verify_unlock_log.sh "$out/unlock.log" || stop_boot unlock-proof
    /gpu-ab/gpu_cold_probe --post-unlock "$out" > "$out/post-unlock.json" 2> "$out/post-unlock.stderr" || stop_boot unlock-state
    /gpu-ab/persist_early.sh b-return || stop_boot post-firmware-persistence

echo "<6>GPU-DEPLOY VERIFIED: revision=dual-v1 targets=0000:41:00.0,0000:01:00.0; original udev handoff" > /dev/kmsg
echo passed > "$out/early-status"
/gpu-ab/persist_early.sh handoff || stop_boot handoff-persistence
