/** Duplication map, after Lin et al. 2026 ("ReSTIR PT Enhanced"): per pixel, the fraction of the other
    pixels in its 17x17 window whose final reservoir holds the very same sample. Next frame, Temporal
    Reuse lowers that pixel's M cap toward 1 as the fraction rises (VR_DUP_CAP), so a sample that reuse
    has already spread over a neighbourhood stops accumulating confidence there.

    Why this and not more mutations: when p_hat is close to the integrand, as it is here, a pixel's
    estimate is close to its reservoir's normalization (runningSum / M), which the mutations keep by
    construction (Sawhney et al. 2024, Eq. 17). Pixels that resampled from the same inputs share that
    normalization, and only sharing less removes it (the spec's root-cause section).
*/
#include "HostDeviceSharedDefinitions.slangh"
__exported import Reservoir;
import Utils.Math.HashUtils;

cbuffer CB
{
    uint2 gResolution;
}

StructuredBuffer<Reservoir> gReservoirs;
RWStructuredBuffer<float> gDuplication;

static const int kGroup = 16;
static const int kRadius = 8;
static const int kTile = kGroup + 2 * kRadius;
static const float kOthers = float((2 * kRadius + 1) * (2 * kRadius + 1) - 1);

groupshared uint sIds[kTile][kTile];

/// Final Shading's sampleIdentity hash, 0 for an empty reservoir or outside the image. Two pixels get the
/// same value exactly when they hold the same sample: the shifts copy the depth and the light sample
/// verbatim.
uint sampleId(int2 p)
{
    if (any(p < 0) || any(p >= int2(gResolution))) return 0u;
    const Reservoir r = gReservoirs[p.y * gResolution.x + p.x];
    if (!(r.runningSum > 0.f)) return 0u;
    uint h = jenkinsHash(asuint(r.depth));
    h = jenkinsHash(h ^ asuint(r.lightUV.x));
    h = jenkinsHash(h ^ asuint(r.lightUV.y));
    h = jenkinsHash(h ^ asuint(r.lightID));
    return max(h, 1u);
}

[numthreads(16, 16, 1)]
void main(uint3 groupId : SV_GroupID, uint3 threadId : SV_GroupThreadID)
{
    // The group's 16x16 pixels plus an 8-pixel apron: each thread loads a 2x2 block of the 32x32 tile.
    const int2 base = int2(groupId.xy) * kGroup - kRadius;
    for (int dy = 0; dy < 2; dy++)
        for (int dx = 0; dx < 2; dx++)
        {
            const int2 t = int2(threadId.xy) * 2 + int2(dx, dy);
            sIds[t.y][t.x] = sampleId(base + t);
        }
    GroupMemoryBarrierWithGroupSync();

    const int2 pixel = int2(groupId.xy) * kGroup + int2(threadId.xy);
    if (any(pixel >= int2(gResolution))) return;
    const int2 c = int2(threadId.xy) + kRadius;
    const uint own = sIds[c.y][c.x];
    uint count = 0;
    if (own != 0u)
    {
        for (int ny = -kRadius; ny <= kRadius; ny++)
            for (int nx = -kRadius; nx <= kRadius; nx++)
                count += sIds[c.y + ny][c.x + nx] == own ? 1u : 0u;
        count -= 1u; // itself
    }
    gDuplication[pixel.y * gResolution.x + pixel.x] = float(count) / kOthers;
}
