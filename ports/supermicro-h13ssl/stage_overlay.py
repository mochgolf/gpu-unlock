#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stage an initramfs overlay in a NEW directory; never install or touch PCI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def run(args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=20)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--root-device', required=True)
    ap.add_argument('--root-uuid', required=True)
    ap.add_argument('--firmware-assets', type=Path, required=True)
    ap.add_argument('--unlock-module', type=Path, required=True)
    ap.add_argument('--unlock-sha256', required=True)
    ap.add_argument('--diag-module', type=Path, required=True)
    ap.add_argument('--diag-sha256', required=True)
    ap.add_argument('--cold-probe', type=Path, required=True)
    ap.add_argument('--kernel', default='7.0.0-34-generic')
    a = ap.parse_args()
    if not re.fullmatch(r'/dev/[A-Za-z0-9_./:-]+', a.root_device) or '..' in a.root_device.split('/'):
        ap.error('invalid root device')
    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', a.root_uuid):
        ap.error('root UUID must be an explicit filesystem UUID')
    out = a.output.absolute()
    if out.exists() or out.is_symlink():
        ap.error('output must not exist')
    resolved = out.resolve()
    for protected in ['/boot', '/etc', '/usr', '/sys', '/proc', '/dev', '/run', '/lib', '/bin', '/sbin']:
        if resolved == Path(protected) or Path(protected) in resolved.parents:
            ap.error('output must be a separate staging directory')
    here = Path(__file__).resolve().parent
    pins = json.loads((here / 'firmware-pins.json').read_text())
    for name, digest in pins.items():
        if sha(a.firmware_assets / name) != digest:
            ap.error('pinned firmware mismatch: ' + name)
    for module, expected in [(a.unlock_module, a.unlock_sha256), (a.diag_module, a.diag_sha256)]:
        if not re.fullmatch(r'[a-f0-9]{64}', expected) or sha(module) != expected:
            ap.error('module digest mismatch')
        if not run(['modinfo', '-F', 'vermagic', module]).startswith(a.kernel + ' '):
            ap.error('module/kernel mismatch')
    symbols = run(['nm', '-u', a.diag_module])
    if re.search(r'request_firmware|dma_alloc|pci_reset|pcie_flr|pci_set_master|iowrite|writel|pci_enable_device', symbols):
        ap.error('diagnostic includes forbidden firmware/reset/DMA/device-enable symbols')
    if 'INTERP' in run(['readelf', '-l', a.cold_probe]):
        ap.error('cold probe must be statically linked')
    for path in [here / 'initramfs/experiment_init_top.sh', here / 'initramfs/verify_unlock_log.sh']:
        run(['/bin/sh', '-n', path])
    rendered = (here / 'initramfs/persist_early.sh.in').read_text().replace('@ROOT_DEVICE@', a.root_device).replace('@ROOT_UUID@', a.root_uuid)
    out.mkdir(parents=True)
    overlay = out / 'overlay'
    for d in ['gpu-ab/lib', 'gpu-ab/persist-root', 'scripts/init-top', 'usr/lib/firmware/gpu-unlock/610.43.03']:
        (overlay / d).mkdir(parents=True, exist_ok=True)
    for name in pins:
        shutil.copy2(a.firmware_assets / name, overlay / 'usr/lib/firmware/gpu-unlock/610.43.03' / name)
    (overlay / 'gpu-ab/firmware').symlink_to('../usr/lib/firmware/gpu-unlock/610.43.03')
    for source, name in [(a.unlock_module, 'gpu_unlock.ko'), (a.diag_module, 'gpu_bme_diag.ko'), (a.cold_probe, 'gpu_cold_probe')]:
        shutil.copy2(source, overlay / 'gpu-ab' / name)
    shutil.copy2('/usr/bin/sha256sum', overlay / 'gpu-ab/sha256sum.bin')
    for dep in set(re.findall(r'(/[^\s()]+)', run(['ldd', '/usr/bin/sha256sum']))):
        shutil.copy2(dep, overlay / 'gpu-ab/lib' / Path(dep).name)
    loader = overlay / 'gpu-ab/lib/ld-linux-x86-64.so.2'
    if not loader.is_file():
        raise RuntimeError('This port requires the tested x86_64 loader layout')
    (overlay / 'gpu-ab/sha256sum').write_text('#!/bin/sh\nexec /gpu-ab/lib/ld-linux-x86-64.so.2 --library-path /gpu-ab/lib /gpu-ab/sha256sum.bin "$@"\n')
    (overlay / 'gpu-ab/persist_early.sh').write_text(rendered)
    shutil.copy2(here / 'initramfs/verify_unlock_log.sh', overlay / 'gpu-ab/verify_unlock_log.sh')
    shutil.copy2(here / 'initramfs/experiment_init_top.sh', overlay / 'scripts/init-top/00_gpu_ab')
    for p in [overlay / 'gpu-ab/sha256sum', overlay / 'gpu-ab/persist_early.sh', overlay / 'gpu-ab/verify_unlock_log.sh', overlay / 'gpu-ab/gpu_cold_probe', overlay / 'scripts/init-top/00_gpu_ab']:
        p.chmod(0o755)
    run(['/bin/sh', '-n', overlay / 'gpu-ab/persist_early.sh'])
    hashes = {str(p.relative_to(overlay)): sha(p) for p in overlay.rglob('*') if p.is_file() and not p.is_symlink()}
    (overlay / 'gpu-ab/SHA256SUMS').write_text(''.join(d + '  /' + name + '\n' for name, d in sorted(hashes.items())))
    report = {'status': 'staged_only', 'overlay': str(overlay), 'kernel': a.kernel,
              'module_sha256': {'unlock': sha(a.unlock_module), 'diagnostic': sha(a.diag_module)},
              'files': hashes, 'hardware_actions': 0, 'boot_files_installed': False,
              'note': 'Merge into a COPY of the original initramfs and place 00_gpu_ab before the original udev in ORDER. Preserve original safe-A recovery. This tool does not do either operation.'}
    (out / 'manifest.local.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
