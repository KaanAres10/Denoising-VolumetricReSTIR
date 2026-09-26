import sys, os, struct, glob
out = sys.argv[2]; os.makedirs(out, exist_ok=True)
for p in sorted(glob.glob(os.path.join(sys.argv[1], "f*.bin"))):
    b = open(p, "rb").read()
    k = b.find(b"\x7fELF")
    if k < 0: continue
    e = b[k:]
    cls = e[4]
    if cls == 2:
        shoff = struct.unpack_from("<Q", e, 0x28)[0]; shentsize, shnum = struct.unpack_from("<HH", e, 0x3A)
    else:
        shoff = struct.unpack_from("<I", e, 0x20)[0]; shentsize, shnum = struct.unpack_from("<HH", e, 0x2E)
    size = shoff + shentsize * shnum
    name = os.path.basename(p)[:-4] + ".cubin"
    open(os.path.join(out, name), "wb").write(e[:size])
    print(name, "elf class", cls, "size", size, "of", len(e), "pre-ELF bytes", k)
