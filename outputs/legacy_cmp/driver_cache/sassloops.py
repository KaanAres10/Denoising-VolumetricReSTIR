"""Loops in an nvdisasm listing: backward BRA -> [target, branch]. Prints loops with TEX, size, op mix."""
import sys, re, collections
L = []
for l in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = re.match(r"\s*/\*([0-9a-f]+)\*/\s+(.*?)\s*(&|\?|$)", l)
    if m: L.append((int(m.group(1), 16), m.group(2).strip()))
addr = {a: i for i, (a, _) in enumerate(L)}
loops = []
for i, (a, t) in enumerate(L):
    m = re.search(r"BRA(?:\.\w+)*\s+(?:`\(\.L_x_\d+\)\s*)?0x([0-9a-f]+)", t)
    if m:
        tgt = int(m.group(1), 16)
        if tgt <= a and tgt in addr: loops.append((addr[tgt], i))
loops = sorted(set(loops), key=lambda x: x[1] - x[0])
for s, e in loops:
    body = [t for _, t in L[s:e + 1]]
    ntex = sum(1 for t in body if re.search(r"\bTEX\b", t))
    if ntex:
        c = collections.Counter(re.match(r"(@!?U?P\w+\s+)?([A-Z0-9]+)", t).group(2) for t in body)
        regs = set(int(r) for t in body for r in re.findall(r"\bR(\d+)\b", t))
        print("loop %04x-%04x %4d instr TEX %2d  distinct R regs %3d  max R %3d  top %s" % (L[s][0], L[e][0], e - s + 1, ntex, len(regs), max(regs), c.most_common(8)))
