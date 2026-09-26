"""Scan an NVIDIA driver cache file for zstd frames holding CUDA-style ELF kernels; dump each ELF and
report its register count, SASS size, local/shared sizes. usage: scan_nvph.py <file> <outdir>"""
import sys, os, struct, zstandard
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
b = open(src, "rb").read()
d = zstandard.ZstdDecompressor()
i = 0; n = 0; rows = []
while True:
    j = b.find(b"\x28\xb5\x2f\xfd", i)
    if j < 0: break
    try:
        obj = d.decompressobj(); data = obj.decompress(b[j:j + 64 * 1024 * 1024])
        used = min(len(b) - j, 64 * 1024 * 1024) - len(obj.unused_data)
    except Exception:
        i = j + 4; continue
    i = j + max(used, 4)
    k = data.find(b"\x7fELF")
    if k < 0: continue
    e = data[k:]
    try:
        shoff = struct.unpack_from("<Q", e, 0x28)[0]; shentsize, shnum, shstrndx = struct.unpack_from("<HHH", e, 0x3A)
        secs = [struct.unpack_from("<IIQQQQIIQQ", e, shoff + q * shentsize) for q in range(shnum)]
        so = secs[shstrndx][4]
        nm = lambda o: e[so + o: e.index(b"\0", so + o)].decode(errors="replace")
    except Exception:
        continue
    info = {"regs": None, "text": 0, "local": 0, "shared": 0}
    for s in secs:
        m = nm(s[0])
        if m.startswith(".text."): info["regs"] = s[7] >> 24; info["text"] = s[5]; info["toff"] = s[4]
        elif m.startswith(".nv.local."): info["local"] = s[5]
        elif m.startswith(".nv.shared."): info["shared"] = s[5]
    n += 1
    name = "k%04d_%09x" % (n, j)
    size = shoff + shentsize * shnum
    open(os.path.join(out, name + ".elf"), "wb").write(e[:size])
    if info["text"]:
        open(os.path.join(out, name + ".text.bin"), "wb").write(e[info["toff"]: info["toff"] + info["text"]])
    rows.append((name, info["regs"], info["text"] // 16, info["local"], info["shared"], e[0x30]))
for r in rows:
    if r[2] >= 1000: print("%-18s regs %4s sass %6d local %5d shared %6d sm %d" % r)
print("kernels", len(rows))
