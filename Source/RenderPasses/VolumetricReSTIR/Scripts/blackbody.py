"""The emission colour GVDB volumes glow with (VolumeBase.slang ConvertTempToColor, before LeScale): the 128-row table
data/LUT/BlackBodyRadiationRGB_50K-6400K.txt -- physical radiance, row i at 50 + 50 i kelvin -- filtered linearly, as
the shader's linear sampler reads it. Shared by vr_graph (inside Mogwai: no imports beyond the standard library) and
make_volumes (which places lights by what a volume emits)."""
import os

LUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "data", "LUT",
                        "BlackBodyRadiationRGB_50K-6400K.txt")
_ROWS = []


def rows():
    if not _ROWS:
        with open(LUT_PATH) as fh:
            _ROWS.extend(tuple(float(v) for v in line.split()) for line in fh if line.strip())
        del _ROWS[128:]
    return _ROWS


def lut(kelvin):
    """The table's RGB at `kelvin` (clamped to 50..6400 K)."""
    r = rows()
    x = min(max((min(kelvin, 6400.0) - 50.0) / 50.0, 0.0), 127.0)
    i = min(int(x), 126)
    f = x - i
    if f == 0.0:
        return r[i]
    return tuple(a + f * (b - a) for a, b in zip(r[i], r[i + 1]))


def kelvin(temperature, cutoff, scale):
    """The kelvin a grid temperature is read at: (T - cutoff) x scale, at most 6400 (ConvertTempToColor)."""
    return min(6400.0, (temperature - cutoff) * scale)
