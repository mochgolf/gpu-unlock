#!/bin/sh
set -eu
source_log=$1
if grep -Eqi "unlock failed|firmware load failed|retaining|keeping its DMA|firmware did not stop|gpu_unlock: failure|NVRM: Xid" "$source_log"; then exit 1; fi
for bdf in 0000:41:00.0 0000:01:00.0; do
  log=$source_log.$bdf.proof
  grep -F "$bdf:" "$source_log" > "$log"
[ "$(grep -Ec "$bdf: gpu_unlock: unlocked$" "$log")" = 1 ]
if grep -Eqi 'unlock failed|firmware load failed|retaining|keeping its DMA|firmware did not stop|gpu_unlock: failure|NVRM: Xid' "$log"; then exit 1; fi
# The original fork intentionally retains DMA until FLR containment. Only this
# exact in-flight message is normal; successful final cleanup is required below.
if grep -Ei 'retained' "$log" | grep -Ev "$bdf: PCIe FLR begin: BME=0 DMA retained, chip=0x192000a1$" | grep -q .; then exit 1; fi

grep -Eq 'AD102 payload result: boot=0 halt=0 marker=0x67b00001 expected=0x67b00001 marker_ok=1 required_permissions=1 .* halted=1 ' "$log"
grep -Eq 'PCIe FLR returned: result=0$' "$log"
grep -Eq 'post-FLR GFW result: error=0 ' "$log"
grep -Eq 'post-FLR SEC2 reset released, GSP halted, BME=0 pending=0 WPR2=[0-9a-f]{8}:00000000 SS0=88888888 SS1=00000008$' "$log"
grep -Eq 'driver probe resources: phase=handoff empty=1$' "$log"
grep -Eq 'AD102 post-FLR: .* valid=1 full=1$' "$log"
grep -Eq 'FWSEC result: scratch=(0|0x[0-9a-f]{1,4}) expected_hi16=0$' "$log"
grep -Eq 'FWSEC WPR2: low=.* high=.* expected_page=.* end=' "$log"
done
