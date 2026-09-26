"""Decompress every zstd frame in an NVIDIA GLCache .bin and report what is inside (ELF images etc)."""
import sys, os, zstandard
src, out = sys.argv[1], sys.argv[2]
b = open(src, "rb").read()
os.makedirs(out, exist_ok=True)
d = zstandard.ZstdDecompressor()
i = 0; n = 0; elf = 0
while True:
    j = b.find(b"\x28\xb5\x2f\xfd", i)
    if j < 0: break
    try:
        obj = d.decompressobj()
        data = obj.decompress(b[j:])
    except Exception as e:
        i = j + 4; continue
    used = len(b[j:]) - len(obj.unused_data)
    n += 1
    k = data.find(b"\x7fELF")
    tag = "ELF@%d" % k if k >= 0 else ""
    if k >= 0: elf += 1
    open(os.path.join(out, "f%04d_%08x.bin" % (n, j)), "wb").write(data)
    if n <= 40 or k >= 0 and elf <= 40: print("frame %d at %d: %d -> %d bytes %s" % (n, j, used, len(data), tag))
    i = j + max(used, 4)
print("frames", n, "with ELF", elf)
