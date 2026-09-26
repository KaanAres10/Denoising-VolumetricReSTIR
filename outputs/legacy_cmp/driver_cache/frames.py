import sys, zstandard, json
out = {}
for p in sys.argv[2:]:
    b = open(p, "rb").read(); d = zstandard.ZstdDecompressor(); i = 0; L = []
    while True:
        j = b.find(b"\x28\xb5\x2f\xfd", i)
        if j < 0: break
        try:
            obj = d.decompressobj(); data = obj.decompress(b[j:j + 64 * 1024 * 1024]); used = min(len(b) - j, 64 * 1024 * 1024) - len(obj.unused_data)
        except Exception:
            i = j + 4; continue
        L.append([j, used, len(data), data[:4].hex(), b"\x7fELF" in data, data[16:24][::-1].hex() if data[:4] == b"STR\0" else ""])
        i = j + max(used, 4)
    out[p[-24:]] = L
json.dump(out, open(sys.argv[1], "w"))
print({k: len(v) for k, v in out.items()})
