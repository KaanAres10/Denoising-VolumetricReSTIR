/** Mutate Samples: Metropolis-Hastings moves on every pixel's reservoir sample after temporal reuse
    (Sawhney et al. 2024, "Decorrelating ReSTIR Samplers via MCMC Mutations"), to decorrelate what
    spatiotemporal reuse shares.

    This first version only carries the pass's interface and changes nothing: the host plumbing is
    checked on its own (byte-identical output with the pass dispatched) before the kernel lands.
*/
__exported import ReSTIRHelper;
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;

cbuffer CB
{
    uint2 gResolution;
    int gFrameCount;
    int gNumTotalRounds;
    int gMutationCount;
    uint gStrategyMask;                  // bit 0 light-vertex, bit 1 depth
    float gLightStepMin, gLightStepMax;  // torus step in u, Kelemen magnitudes
    float gDirStepMin, gDirStepMax;      // radians
    float gDepthStepMin, gDepthStepMax;  // in ray-march steps (volumeDesc.tStep * volumeWorldScaling)
    bool gCollectStats;
    SamplingOptions gSamplingOptions;
    EnvMapSampler envMapSampler;
    EmissiveLightSampler emissiveSampler;
}

RWStructuredBuffer<Reservoir> gCurReservoirs;
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
RWStructuredBuffer<uint> gMutationStats;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
#endif

#ifndef VR_GROUP_X
#define VR_GROUP_X 16
#endif
#ifndef VR_GROUP_Y
#define VR_GROUP_Y 16
#endif
[numthreads(VR_GROUP_X, VR_GROUP_Y, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    if (any(DTid.xy >= gResolution)) return;
    // Never true when the host dispatches (mMutationCount > 0); it keeps every resource referenced.
    if (gMutationCount < 0)
    {
        const int pixelId = getPixelID(int2(DTid.xy), gResolution);
        Reservoir r = gCurReservoirs[pixelId];
        gMutationStats[0] = asuint(r.M + gCurExtraBounceReservoirs[0].wi_dist.x);
    }
}
