"""Offline dual-device proof tests; production binary never touches hardware here."""
import hashlib,json,struct,subprocess,sys
from pathlib import Path
stage=Path(sys.argv[1]).resolve()
assert stage.is_dir() and not list(stage.iterdir()), 'Use a new empty fixture directory'
source_root=Path(__file__).resolve().parents[3]
port=Path(__file__).resolve().parents[1]
src=stage/'src';src.mkdir()
import shutil
for name in ('prep_610.c','prep_610.h','layout_610.c','layout_610.h','vbios_610.c','vbios_610.h','gfw_eval.c','gfw_eval.h','diagnostic.h'):
 shutil.copy2(source_root/'kernel/gpu_unlock'/name,src/name)
shutil.copy2(source_root/'tests/vbios_fixture.h',src/'vbios_fixture.h')
shutil.copy2(port/'gpu_cold_probe.c',src/'gpu_cold_probe.c')
shutil.copy2(port/'initramfs/verify_unlock_log.sh',src/'verify_unlock_log.sh')
shutil.copy2(port/'tests/native-unlock-golden.log',src/'native-unlock-golden.log')
fake=stage/'fake-pci';fake.mkdir();assets=Path(sys.argv[2]).resolve();checks=[]
def run(a):return subprocess.run([str(x) for x in a],capture_output=True,text=True,timeout=60)
def record(n):checks.append(n)
exe=stage/'fixture-probe'
# The production sampler intentionally requires root. Only this private fake-PCI
# executable wraps geteuid; the published sampler and its privilege guard stay
# byte-for-byte unchanged, and PCI_SYSFS_ROOT is still this temporary fixture.
uid_shim=src/'fixture_uid.c';uid_shim.write_text('#include <sys/types.h>\nuid_t __wrap_geteuid(void){return 0;}\n')
p=run(['gcc','-O2','-Wall','-Wextra','-Werror','-static','-I',src,'-DPCI_SYSFS_ROOT="'+str(fake)+'"','-DPROBE_ASSETS="'+str(assets)+'"',*[src/x for x in ['gpu_cold_probe.c','prep_610.c','layout_610.c','vbios_610.c','gfw_eval.c']],uid_shim,'-Wl,--wrap=geteuid','-o',exe]);assert p.returncode==0,p.stderr
gen=src/'fixture_gen.c';gen.write_text('#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\ntypedef uint8_t u8;typedef uint32_t u32;\n#include "vbios_fixture.h"\nint main(void){u8 rom[4096];vbios_fixture(rom,6);return fwrite(rom,1,sizeof(rom),stdout)!=sizeof(rom);}\n')
p=run(['gcc','-O2',gen,'-o',stage/'fixture-gen']);assert p.returncode==0,p.stderr
rom=bytearray(subprocess.check_output([str(stage/'fixture-gen')]));struct.pack_into('<H',rom,292,0x400)
bdfs=['0000:41:00.0','0000:01:00.0']
regs={0:0x192000a1,0x118128:1,0x118234:255,0x110100:0x10,0x823804:0x200,0x823818:0x1249249,0x82381c:0x22222222,0x823820:2,0x1183a4:49140,0x1fa7c8:1,0x1fa82c:0,0x1fa830:0}
for bdf in bdfs:
 d=fake/bdf;d.mkdir();c=bytearray(256);struct.pack_into('<I',c,0,0x268410de);struct.pack_into('<H',c,4,7)
 c[0x34]=0x40;c[0x40]=1;c[0x41]=0x50;c[0x50]=0x10;struct.pack_into('<I',c,0x54,1<<28)
 (d/'config').write_bytes(c);(d/'power_state').write_text('D0\n');(d/'reset_method').write_text('flr bus\n')
 with (d/'resource0').open('wb') as f:f.truncate(16<<20)
 with (d/'resource0').open('r+b') as f:
  for off,val in regs.items():f.seek(off);f.write(struct.pack('<I',val))
  f.seek(0x300000);f.write(rom)
def command(bdf,v):
 p=fake/bdf/'config';b=bytearray(p.read_bytes());struct.pack_into('<H',b,4,v);p.write_bytes(b)
def reg(bdf,off,v):
 with (fake/bdf/'resource0').open('r+b') as f:f.seek(off);f.write(struct.pack('<I',v))
out=stage/'fixture-cold';out.mkdir()
def probe(mode='--post-unlock'):
 before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in fake.rglob('*') if p.is_file()}
 p=run([exe,mode,out]);assert p.stdout,(p.returncode,p.stderr);r=json.loads(p.stdout)
 assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in fake.rglob('*') if p.is_file()},'probe wrote PCI inputs'
 return p.returncode,r
rc,r=probe('--cold-candidate');assert rc==0 and r['policy_pass'] and [d['mask'] for d in r['devices']]==[8,8];record('cold-BME7-both-recorded')
command(bdfs[0],3);rc,r=probe('--post-bme-diag');assert rc==2;record('one-normalized-only-rejected')
command(bdfs[1],3);rc,r=probe('--post-bme-diag');assert rc==0 and r['eligible'];record('both-normalized-3-accepted')
for bdf in bdfs:
 reg(bdf,0x823820,3);rc,r=probe('--post-bme-diag');assert rc==2;reg(bdf,0x823820,2);record('normalization-fingerprint-drift-'+bdf)
for i,bdf in enumerate(bdfs):
 for off,val in {0x823804:0xffffffff,0x823818:0,0x82381c:0x88888888,0x823820:8}.items():reg(bdf,off,val)
 rc,r=probe();assert (rc==0)==(i==1);record('post-unlock-card-count-'+str(i+1))
for bdf in bdfs:
 for off,bad,good in [(0x823804,0x200,0xffffffff),(0x823818,1,0),(0x82381c,0x22222222,0x88888888),(0x823820,2,8),(0x1fa828,0x10,0),(0x1fa7cc,123,0),(0x9a0148,123,0),(0x1fa7c4,123,0)]:
  reg(bdf,off,bad);rc,r=probe();assert rc==2,(bdf,hex(off),r);reg(bdf,off,good);record('post-register-drift-'+bdf+'-'+hex(off))
 command(bdf,7);rc,r=probe();assert rc==2;command(bdf,3);record('post-BME-reenabled-'+bdf)
 (fake/bdf/'driver').symlink_to(fake);rc,r=probe();assert rc==2;(fake/bdf/'driver').unlink();record('bound-driver-'+bdf)
 (fake/bdf/'power_state').write_text('D3hot\n');rc,r=probe();assert rc==2;(fake/bdf/'power_state').write_text('D0\n');record('D3-'+bdf)
# Native single-card golden, replicated to the other pinned BDF. Each card must
# independently contain every receipt; deleting a single receipt must reject.
gold=(src/'native-unlock-golden.log').read_text();dual=gold+'\n'+gold.replace(bdfs[0],bdfs[1])
variants={'both-native-good':dual,'one-card-only':gold,'global-error':dual+'\nfirmware did not stop; keeping its DMA buffers until power off\n'}
for bdf in bdfs:
 for old,new in [('marker_ok=1','marker_ok=0'),('post-FLR GFW result: error=0','post-FLR GFW result: error=-1'),('phase=handoff empty=1','phase=handoff empty=0'),('valid=1 full=1','valid=0 full=0'),('WPR2=1ffffe00:00000000','WPR2=1ffffe00:00000010')]:
  variants[bdf+old]='\n'.join(line.replace(old,new) if bdf+':' in line else line for line in dual.splitlines())
for label,body in variants.items():
 path=stage/('proof-'+str(len(checks))+'.log');path.write_text(body)
 p=run(['/bin/sh',src/'verify_unlock_log.sh',path]);assert (p.returncode==0)==(label=='both-native-good'),(label,p.stderr);record(label)
(stage/'offline-tests.json').write_text(json.dumps({'checks':checks,'hardware_accesses':0,'all_assertions_passed':True},indent=2))
print(json.dumps({'checks':len(checks),'pass':True}))
