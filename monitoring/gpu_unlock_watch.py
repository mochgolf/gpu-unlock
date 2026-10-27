#!/usr/bin/python3 -I
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only GPU-unlock evidence checks; root writes only a small /run status."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

CONFIG = Path('/etc/gpu-unlock-watch.json')
CACHE = Path('/run/gpu-unlock-watch/status.json')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}


def command(args, timeout=3):
    r = subprocess.run(args, capture_output=True, text=True, env=ENV, timeout=timeout)
    if r.returncode:
        raise RuntimeError(args[0] + ' returned ' + str(r.returncode))
    return r.stdout


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def trusted(path, directory=False):
    p = Path(path)
    s = p.lstat()
    if s.st_uid != 0 or s.st_mode & 0o022 or p.is_symlink():
        raise ValueError('Untrusted owner/mode: ' + str(p))
    if directory and not stat.S_ISDIR(s.st_mode):
        raise ValueError('Not a directory: ' + str(p))


def live_facts():
    facts = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
             'hostname': os.uname().nodename, 'kernel': os.uname().release,
             'nvidia_loaded': Path('/sys/module/nvidia').is_dir(),
             'unlock_loaded': Path('/sys/module/gpu_unlock').is_dir(),
             'cmdline': Path('/proc/cmdline').read_text().strip()}
    for module in ['nvidia', 'gpu_unlock']:
        for field in ['version', 'srcversion']:
            p = Path('/sys/module') / module / field
            facts[module + '_' + field] = p.read_text().strip() if p.exists() else None
    p = Path('/sys/module/gpu_unlock/parameters/targets')
    facts['targets'] = p.read_text().strip().split(',') if p.exists() else []
    return facts


def collect(config):
    facts = live_facts()
    errors = []
    boot = facts['boot_id']
    if not re.fullmatch(r'[0-9a-f-]{36}', boot):
        raise ValueError('Invalid boot ID')
    receipt = Path(config['receipt_root']) / (boot + '-handoff')
    try:
        trusted(receipt.parent, directory=True)
        trusted(receipt, directory=True)
        facts['receipt'] = {key: (receipt / key).read_text().strip()
                            for key in ['boot_id', 'revision', 'mode', 'early-status']}
        sums = receipt / 'SHA256SUMS'
        trusted(sums)
        checked = {}
        for line in sums.read_text().splitlines():
            match = re.fullmatch(r'([a-f0-9]{64}) [ *](?:\./)?([^/]+)', line)
            if not match or match[2] in ['.', '..']:
                raise ValueError('Invalid receipt checksum entry')
            p = receipt / match[2]
            trusted(p)
            checked[match[2]] = digest(p) == match[1]
        required = {'boot_id', 'revision', 'mode', 'early-status', 'post-unlock.json', 'unlock.log'}
        facts['receipt_checksums_ok'] = required <= set(checked) and all(checked.values())
        facts['register_receipt'] = json.loads((receipt / 'post-unlock.json').read_text())
        facts['unlock_log'] = (receipt / 'unlock.log').read_text()
    except (OSError, ValueError, KeyError) as e:
        errors.append('当前启动的解锁凭据不可用: ' + type(e).__name__)
    try:
        facts['journal'] = command(['journalctl', '-k', '-b', '--no-pager', '-o', 'cat'])
    except (OSError, subprocess.SubprocessError, RuntimeError):
        errors.append('无法读取当前启动的内核日志')
    try:
        facts['grub'] = dict(line.split('=', 1) for line in command(
            ['grub-editenv', '/boot/grub/grubenv', 'list']).splitlines() if '=' in line)
        text = Path('/boot/grub/grub.cfg').read_text()
        facts['grub_uses_saved_entry'] = 'set default="${saved_entry}"' in text
        facts['grub_has_entry'] = "--id '" + config['default_entry'] + "'" in text
        facts['boot_file_hashes'] = {}
        for p, expected in config['boot_file_hashes'].items():
            facts['boot_file_hashes'][p] = digest(p) == expected
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
        errors.append('无法核验下一次启动的默认项或解锁镜像')
    if facts['nvidia_loaded']:
        try:
            rows = csv.reader(command(['nvidia-smi', '--query-gpu=uuid,pci.bus_id,driver_version',
                                       '--format=csv,noheader,nounits']).splitlines())
            facts['gpus'] = {}
            for uuid, bdf, driver in rows:
                domain, bus, slot = bdf.strip().lower().split(':')
                key = f'{int(domain, 16):04x}:{bus}:{slot}'
                facts['gpus'][key] = {'uuid': uuid.strip(), 'driver': driver.strip()}
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
            errors.append('NVML 无法确认双卡身份或驱动版本')
    facts['collection_errors'] = errors
    return facts


def evaluate(config, facts):
    issues = []
    def issue(code, text, scope='current'):
        issues.append({'code': code, 'scope': scope, 'message': text})
    for key, label in [('hostname', '主机'), ('kernel', '内核'),
                       ('nvidia_version', 'NVIDIA 驱动'), ('nvidia_srcversion', '驱动构建'),
                       ('gpu_unlock_srcversion', '解锁模块构建')]:
        if facts.get(key) != config[key]:
            issue(key, label + '与已验收配置不一致')
    if not facts.get('nvidia_loaded'):
        issue('driver_missing', 'NVIDIA 驱动未加载')
    if not facts.get('unlock_loaded'):
        issue('unlock_missing', '解锁模块未加载，可能已回到原厂状态')
    if set(facts.get('targets', [])) != set(config['gpus']):
        issue('targets', '解锁模块目标没有覆盖已配置的两张卡')
    if config['cmdline_token'] not in facts.get('cmdline', '').split():
        issue('boot_entry', '本次启动未使用已验收的双卡解锁启动项')
    receipt = facts.get('receipt', {})
    if receipt.get('boot_id') != facts.get('boot_id'):
        issue('receipt_boot', '缺少本次 boot ID 的凭据，旧启动记录不能作为成功依据')
    if (receipt.get('revision') != config['revision'] or
            receipt.get('mode') != 'dual-production-v1' or receipt.get('early-status') != 'passed'):
        issue('early_check', '本次启动的双卡解锁验收未通过或不可确认')
    if facts.get('receipt_checksums_ok') is not True:
        issue('receipt_integrity', '当前启动凭据不完整或校验失败')
    reg = facts.get('register_receipt', {})
    devices = reg.get('devices', [])
    if (reg.get('mode') != 'post-unlock' or reg.get('policy_pass') is not True or
            len(devices) != 2 or {d.get('bdf') for d in devices} != set(config['gpus'])):
        issue('register_inventory', '解锁后的双卡寄存器回读凭据不完整')
    for dev in devices:
        registers = dev.get('registers', {})
        if any(registers.get(k) != v for k, v in config['registers'].items()):
            issue('register_state', str(dev.get('bdf')) + ' 的解锁寄存器回读不符合预期')
    for bdf, uuid in config['gpus'].items():
        gpu = facts.get('gpus', {}).get(bdf, {})
        if gpu.get('uuid') != uuid or gpu.get('driver') != config['nvidia_version']:
            issue('gpu_identity', bdf + ' 未由 NVML 确认为预期显卡/驱动')
        pattern = re.escape(bdf) + r': gpu_unlock: unlocked$'
        if not re.search(pattern, facts.get('unlock_log', ''), re.M):
            issue('card_success', bdf + ' 缺少本次启动的单卡解锁成功记录')
    journal = facts.get('journal', '')
    if config['journal_marker'] not in journal:
        issue('handoff', '当前内核日志缺少双卡验证及驱动接管成功标记')
    if len(re.findall(r'NVRM: loading NVIDIA UNIX', journal)) > 1:
        issue('driver_reload', '本次启动中出现驱动重载，需重新确认解锁状态')
    if re.search(r'NVRM: Xid|GPU has fallen off|gpu_unlock: unlock failed|GPU-DEPLOY.*(?:FAILED|FAILURE)', journal):
        issue('gpu_error', '当前启动出现 GPU/解锁失败记录，请检查内核日志')
    grub = facts.get('grub', {})
    if grub.get('saved_entry') != config['default_entry']:
        issue('default_entry', 'GRUB 默认项已离开双卡解锁项，下次可能不会自动应用', 'next_boot')
    if grub.get('next_entry', '') not in ['', config['default_entry']]:
        issue('next_entry', '存在一次性覆盖启动项，下次可能不会应用解锁', 'next_boot')
    if not facts.get('grub_uses_saved_entry') or not facts.get('grub_has_entry'):
        issue('grub_config', 'GRUB 已不按保存的双卡解锁默认项启动', 'next_boot')
    hashes = facts.get('boot_file_hashes', {})
    if not hashes or any(hashes.get(p) is not True for p in config['boot_file_hashes']):
        issue('boot_files', '已验收的解锁启动文件发生变化或无法读取', 'next_boot')
    for error in facts.get('collection_errors', []):
        issue('unknown', error, 'unknown')
    current_ok = not any(x['scope'] in ['current', 'unknown'] for x in issues)
    return {'schema': 1, 'state': 'ok' if not issues else 'warning' if current_ok else 'unconfirmed',
            'current_boot_confirmed': current_ok, 'issues': issues,
            'boot_id': facts.get('boot_id'), 'kernel': facts.get('kernel'),
            'nvidia_version': facts.get('nvidia_version'),
            'checked_utc': datetime.now(timezone.utc).isoformat(),
            'evidence_scope': 'Current-boot readback receipts and live module/NVML checks; no live MMA or MMIO probe'}


def notify_text(result, quiet=True):
    if result['state'] == 'ok':
        return '' if quiet else ('[GPU-UNLOCK OK] 本次启动的双卡解锁凭据及自动启动配置检查通过。\n'
                                '轻量状态检查；未运行算力压测。\n')
    heading = ('本次启动解锁凭据通过，但下次自动应用配置有变化' if result.get('current_boot_confirmed')
               else '未能确认双卡解锁生效，请勿假定已获得解锁算力')
    messages = list(dict.fromkeys(x['message'] for x in result['issues']))
    body = '\n'.join('  - ' + x for x in messages[:8])
    if len(messages) > 8:
        body += '\n  - 其余原因请运行 gpu-unlock-status --json 查看'
    return ('\n========== GPU-UNLOCK 提醒 / WARNING ==========\n' + heading + '\n' + body +
            '\n检查: gpu-unlock-status\n详情: sudo gpu-unlock-status --json\n'
            '日志: journalctl -u gpu-unlock-watch.service -b\n'
            '本脚本仅提醒，不加载模块、不更改功率、不自动重启。\n'
            '============================================\n')


def cached(config):
    trusted(CACHE.parent, directory=True)
    trusted(CACHE)
    result = json.loads(CACHE.read_text())
    live = live_facts()
    if result.get('boot_id') != live['boot_id']:
        raise ValueError('状态来自其他启动')
    result = {**result, 'issues': list(result['issues'])}
    checked = datetime.fromisoformat(result['checked_utc'])
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if age < -60 or age > 900:
        result['issues'].append({'code': 'stale', 'scope': 'unknown',
                                 'message': 'root 检查缓存已超过15分钟，请 sudo gpu-unlock-status 刷新'})
    for key in ['kernel', 'hostname', 'nvidia_version', 'nvidia_srcversion', 'gpu_unlock_srcversion']:
        if live.get(key) != config[key]:
            result['issues'].append({'code': 'live_drift', 'scope': 'current', 'message': '当前模块/版本与缓存不一致: ' + key})
    if not live['nvidia_loaded'] or not live['unlock_loaded'] or set(live['targets']) != set(config['gpus']):
        result['issues'].append({'code': 'live_module', 'scope': 'current', 'message': '当前驱动/解锁模块或双卡目标不完整'})
    for bdf in config['gpus']:
        p = Path('/sys/bus/pci/devices') / bdf / 'driver'
        if not p.exists() or p.resolve().name != 'nvidia':
            result['issues'].append({'code': 'live_binding', 'scope': 'current',
                                     'message': bdf + ' 当前未绑定 NVIDIA 驱动'})
    if result['issues']:
        result['state'] = 'unconfirmed' if any(x['scope'] in ['current', 'unknown'] for x in result['issues']) else 'warning'
        result['current_boot_confirmed'] = result['state'] == 'warning'
    result['read_from_root_cache'] = True
    return result


def save(result):
    CACHE.parent.mkdir(mode=0o755, exist_ok=True)
    trusted(CACHE.parent, directory=True)
    fd, name = tempfile.mkstemp(prefix='.status-', dir=CACHE.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.flush(); os.fchmod(f.fileno(), 0o644); os.fsync(f.fileno())
        os.replace(name, CACHE)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--notify', action='store_true', help='quiet if healthy; warn without failing SSH login')
    mode.add_argument('--boot', action='store_true', help='boot status: warning goes to journal/console')
    mode.add_argument('--json', action='store_true')
    mode.add_argument('--demo', action='store_true', help='display a clearly marked warning demo; never writes status')
    args = ap.parse_args(argv)
    if args.demo:
        print('[演示 / DEMO，不代表服务器当前故障]')
        print(notify_text({'state': 'unconfirmed', 'current_boot_confirmed': False,
                           'issues': [{'message': '演示：某张显卡缺少解锁成功凭据'}]}), end='')
        return 0
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('Check exceeded 12s')))
    signal.alarm(12)
    try:
        trusted(CONFIG)
        config = json.loads(CONFIG.read_text())
        result = evaluate(config, collect(config)) if os.geteuid() == 0 else cached(config)
    except Exception as e:
        result = {'schema': 1, 'state': 'unconfirmed', 'current_boot_confirmed': False,
                  'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'checked_utc': datetime.now(timezone.utc).isoformat(),
                  'issues': [{'code': 'checker_error', 'scope': 'unknown',
                              'message': '检查未完成，无法确认解锁状态: ' + type(e).__name__}]}
    finally:
        signal.alarm(0)
    if os.geteuid() == 0:
        try:
            save(result)
        except (OSError, ValueError):
            result['state'] = 'unconfirmed'; result['current_boot_confirmed'] = False
            result['issues'].append({'code': 'cache_write', 'scope': 'unknown', 'message': '无法保存本次启动检查结果'})
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(notify_text(result, quiet=args.notify or args.boot), end='')
    return 0 if args.notify or args.boot or result['state'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
