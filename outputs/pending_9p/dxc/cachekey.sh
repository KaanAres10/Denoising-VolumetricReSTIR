#!/bin/bash
# Is gfx's .shadercache keyed on the DXC version? Trace volume-only with DXC 1.7 and the cache kept
# (fills it), then swap in DXC 1.8.2505 WITHOUT touching the cache and trace again. Spatial Reuse
# compiles to 168 registers on DXC 1.7 and 128 on 1.8: 168 in the second trace means 1.7's DXIL was
# served from the cache. Also counts cache entries before and after each run.
# Result (2026-09-26): keyed. The kept-cache DXC 1.8 run wrote new entries and traced the same as a run
# with the cache emptied (ck_2505_fresh); Spatial Reuse's 168 there is DXC 1.8 on specialized code.
R=/c/research/Denoising-VolumetricReSTIR; B=$R/build/windows-vs2022/bin/Release; D=$R/outputs/pending_9p/dxc
cd $R
tasklist 2>/dev/null | grep -i mogwai && { echo "Mogwai running, abort"; exit 1; }
trap 'cp -p $D/dxc17/* $B/' EXIT
n() { find $B/.shadercache -type f 2>/dev/null | wc -l; }
cp -p $D/dxc17/* $B/
echo "cache entries before: $(n)"
KEEP_CACHE=1 bash outputs/legacy_cmp/knob_trace.sh ck_17
echo "cache entries after DXC 1.7 run: $(n)"
cp -p $D/dxc2505/* $B/
KEEP_CACHE=1 bash outputs/legacy_cmp/knob_trace.sh ck_2505_kept
echo "cache entries after DXC 1.8.2505 run, cache kept: $(n)"
echo "CACHEKEY DONE"
