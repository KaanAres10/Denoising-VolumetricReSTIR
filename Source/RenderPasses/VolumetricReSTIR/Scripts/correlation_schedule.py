"""When correlation_pose.py seeds its chains and which frames it captures. Pure Python, so it can be
tested outside Mogwai (tests/test_correlation_schedule.py).

A chain starts from a history reset with `frameSeed`, renders `warm` frames of warm-up, then captures
`per_chain` frames `spacing` apart. Chains run back to back. Every random stream in the estimator is
seeded from the frame count, and a chain advances the frame count by one per frame, so each chain owns
the frame-count range [seed, seed + length): ranges that overlapped would replay the same random
numbers, and once the history was forgotten the two chains would render the same images. The seeds are
therefore spaced `seed_stride` apart, which must exceed every chain's length.

An optional burst (for the temporal autocorrelation) is one more chain that, after its warm-up,
captures `burst` consecutive frames.
"""

# Shaders seed with numTotalRounds * frameCount + round in 32-bit ints, numTotalRounds <= ~8.
MAX_FRAME_COUNT = 250_000_000


def build_schedule(f0, chains, per_chain, warm, spacing, burst=0, seed_base=100_000, seed_stride=None):
    """f0 is the clock frame just rendered; the first chain's first frame is f0 + 1.

    Returns {"chains": [{"seed", "first", "length", "frames"}], "burst": {...} or None,
             "total": frames to render, "stride": seed_stride}.
    """
    if chains < 1 or per_chain < 1 or warm < 0 or spacing < 1 or burst < 0:
        raise ValueError("chains, per_chain, spacing >= 1 and warm, burst >= 0 required")
    chain_len = warm + (per_chain - 1) * spacing + 1
    burst_len = warm + burst if burst else 0
    longest = max(chain_len, burst_len)
    if seed_stride is None:
        seed_stride = (longest // 10_000 + 1) * 10_000
    if seed_stride <= longest:
        raise ValueError("seed_stride %d must exceed the longest chain (%d frames), or chains would "
                         "share random numbers" % (seed_stride, longest))
    if seed_base < 0 or seed_base + (chains + 1) * seed_stride > MAX_FRAME_COUNT:
        raise ValueError("seeds up to %d overflow the shaders' 32-bit seeds (limit %d)"
                         % (seed_base + (chains + 1) * seed_stride, MAX_FRAME_COUNT))

    out = {"chains": [], "burst": None, "stride": seed_stride}
    first = f0 + 1
    for c in range(chains):
        frames = [first + warm + k * spacing for k in range(per_chain)]
        out["chains"].append({"seed": seed_base + c * seed_stride, "first": first,
                              "length": chain_len, "frames": frames})
        first += chain_len
    if burst:
        out["burst"] = {"seed": seed_base + chains * seed_stride, "first": first, "length": burst_len,
                        "frames": list(range(first + warm, first + warm + burst))}
        first += burst_len
    out["total"] = first - (f0 + 1)
    return out


def parse_rows(spec, height):
    """VR_STRIP_ROWS "y0:y1" -> (y0, y1): the band of image rows a space-time strip keeps, inside the frame."""
    try:
        y0, y1 = (int(v) for v in spec.split(":"))
    except ValueError:
        raise ValueError("strip rows %r: want y0:y1" % spec) from None
    if not 0 <= y0 < y1 <= height:
        raise ValueError("strip rows %d:%d outside a frame %d rows high, or empty" % (y0, y1, height))
    return y0, y1


def strip_frames(schedule, frames):
    """The frames a space-time strip keeps: the last chain's capture frame, then the frames-1 that follow it in the
    same chain (no reset), so the strip's first row is that chain's captured frame. Not with a burst, which would
    run after that chain."""
    if frames < 1:
        raise ValueError("a strip needs at least one frame")
    if schedule["burst"]:
        raise ValueError("a strip continues the last chain; a burst would run after it")
    last = schedule["chains"][-1]["frames"][-1]
    return list(range(last, last + frames))
