"""For each driver ELF: register count (from the .text section header), local/shared sizes, and the raw
.text dumped for nvdisasm -b SM120."""
import sys, os, struct, glob, subprocess
CU = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvdisasm.exe"
for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.cubin"))):
    e = open(p, "rb").read()
    shoff = struct.unpack_from("<Q", e, 0x28)[0]; shentsize, shnum, shstrndx = struct.unpack_from("<HHH", e, 0x3A)
    secs = [struct.unpack_from("<IIQQQQIIQQ", e, shoff + i * shentsize) for i in range(shnum)]
    so = secs[shstrndx][4]
    nm = lambda o: e[so + o: e.index(b"\0", so + o)].decode()
    info = {}
    for s in secs:
        n = nm(s[0])
        if n.startswith(".text."):
            info["regs"] = s[7] >> 24; info["text"] = s[5]
            raw = p[:-6] + ".text.bin"; open(raw, "wb").write(e[s[4]: s[4] + s[5]])
            info["raw"] = raw
        elif n.startswith(".nv.local."): info["local"] = s[5]
        elif n.startswith(".nv.shared."): info["shared"] = s[5]
    print("%-28s regs %3s  sass %6d instr  local %4s  shared %s" % (os.path.basename(p), info.get("regs"), info.get("text", 0) // 16, info.get("local", 0), info.get("shared", 0)))
