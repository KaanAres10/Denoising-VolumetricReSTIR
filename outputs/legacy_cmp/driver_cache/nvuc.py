"""Extract the SASS from an NVuc cache entry and disassemble it.  nvuc.py <cache file> <hex offset> <out.sass>"""
import sys, zstandard, struct, subprocess, re, collections
b = open(sys.argv[1], "rb").read(); j = int(sys.argv[2], 16)
nv = zstandard.ZstdDecompressor().decompressobj().decompress(b[j:j + (1 << 26)])
assert nv[:4] == b"NVuc", nv[:4]
size, off = struct.unpack_from("<II", nv, 164); smem = struct.unpack_from("<I", nv, 116)[0]
raw = sys.argv[3] + ".bin"; open(raw, "wb").write(nv[off:off + size])
nd = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvdisasm.exe"
txt = subprocess.run([nd, "-b", "SM120", raw], capture_output=True, text=True).stdout
open(sys.argv[3], "w").write(txt)
ins = [l for l in txt.splitlines() if re.match(r"\s*/\*[0-9a-f]+\*/", l)]
maxr = max((int(r) for l in ins for r in re.findall(r"\bR(\d+)\b", l)), default=0)
c = collections.Counter(re.match(r"\s*/\*[0-9a-f]+\*/\s+(@!?U?P\w+\s+)?([A-Z0-9]+)", l).group(2) for l in ins)
print("%s: instr %d  max R%d  smem %d  TEX %d LDCU %d LDC %d LDS %d STS %d LDL %d STL %d BRA %d" % (sys.argv[3].split("/")[-1], len(ins), maxr, smem, c["TEX"], c["LDCU"], c["LDC"], c["LDS"], c["STS"], c["LDL"], c["STL"], c["BRA"]))
