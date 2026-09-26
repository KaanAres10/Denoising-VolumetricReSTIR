"""For each hash record, the next ELF kernel in file order: which compile a DXIL hash got, and how often."""
import sys, struct, zstandard, collections
src = sys.argv[1]; want = {bytes.fromhex(h)[::-1]: h[:8] for h in sys.argv[2:]}
b = open(src, "rb").read()
d = zstandard.ZstdDecompressor()
i = 0; pending = None; out = collections.defaultdict(list)
while True:
    j = b.find(b"\x28\xb5\x2f\xfd", i)
    if j < 0: break
    try:
        obj = d.decompressobj(); data = obj.decompress(b[j:j + 64 * 1024 * 1024]); used = min(len(b) - j, 64 * 1024 * 1024) - len(obj.unused_data)
    except Exception:
        i = j + 4; continue
    i = j + max(used, 4)
    if len(data) < 20000:
        for p, h in want.items():
            if p in data: pending = (h, j)
    k = data.find(b"\x7fELF")
    if k >= 0 and pending:
        e = data[k:]
        shoff = struct.unpack_from("<Q", e, 0x28)[0]; shentsize, shnum, shstrndx = struct.unpack_from("<HHH", e, 0x3A)
        secs = [struct.unpack_from("<IIQQQQIIQQ", e, shoff + q * shentsize) for q in range(shnum)]
        so = secs[shstrndx][4]; regs = sass = loc = sh = 0
        for s in secs:
            nm = e[so + s[0]: e.index(b"\0", so + s[0])]
            if nm.startswith(b".text."): regs = s[7] >> 24; sass = s[5] // 16
            elif nm.startswith(b".nv.local."): loc = s[5]
            elif nm.startswith(b".nv.shared."): sh = s[5]
        out[pending[0]].append((pending[1], j, regs, sass, loc, sh))
        pending = None
for h, L in out.items():
    print(h)
    for r in L: print("   hash@%09x elf@%09x regs %3d sass %6d local %4d shared %6d" % r)
