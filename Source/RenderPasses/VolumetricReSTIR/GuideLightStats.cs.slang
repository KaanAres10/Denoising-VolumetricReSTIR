/** Light-share statistics for the depth/motion-vector guides. It reads only finished results (the
    shaded frame, the reservoirs final shading just used, the primary-ray transmittance), and by default
    nothing in the estimator reads what it writes, so ReSTIR's sampling, reuse and shading cannot change
    because of it. The one opt-in exception is mTemporalReprojectByLightShare: next frame's temporal
    reuse then uses it to choose which layer's motion to follow (TemporalReuse.cs.slang).

    Per pixel it records (medium light, coverage, surface light, transmittance), blended into a
    running average. Its mips then give NEIGHBOURHOOD means, and two ratios of them are the local
    radiances GenerateFeatures needs to decide which layer a pixel mostly shows:
        medium light per unit coverage      Lm = mean(medium light)  / mean(coverage)
        surface light per unit transmittance Ls = mean(surface light) / mean(transmittance)
    Ratios of means over a window are stable even though each pixel's own split is all-or-nothing:
    ReSTIR keeps one sample per pixel, so a pixel's whole colour lands in whichever layer that sample
    came from -- the same classification final shading's volumeColor/surfaceColor split uses.
*/
#include "Utils/Math/MathConstants.slangh"
#define DEVICE_NEED_INCLUDE
#include "HostDeviceSharedDefinitions.slangh"

cbuffer CB
{
    uint2   gResolution;
    // Weight of this frame in the running average; 1 restarts it (first frame, resize).
    float   gBlend;
}

Texture2D<float4> gColor;                       // the shaded frame (accumulated_color)
StructuredBuffer<Reservoir> gFinalReservoirs;   // the reservoirs final shading shaded
StructuredBuffer<ReservoirFeatures> gFeatures;  // primary-ray transmittance (deterministic)
RWTexture2D<float4> gStats;                     // mip 0

[numthreads(16, 16, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    if (any(DTid.xy >= gResolution)) return;
    const uint pixelId = DTid.y * gResolution.x + DTid.x;

    float lum = dot(gColor[DTid.xy].rgb, float3(0.2126f, 0.7152f, 0.0722f));
    if (!(lum >= 0.f) || isinf(lum)) lum = 0.f;   // the frame is sanitised already; stay safe anyway

    // Same test final shading uses for its split: a sample at depth kRayTMax (FLT_MAX) is a surface or
    // background sample, anything nearer scattered in the medium.
    const bool inMedium = gFinalReservoirs[pixelId].depth < FLT_MAX;
    const float T = saturate(gFeatures[pixelId].transmittance);

    const float4 cur = float4(inMedium ? lum : 0.f, 1.f - T, inMedium ? 0.f : lum, T);
    gStats[DTid.xy] = gBlend >= 1.f ? cur : lerp(gStats[DTid.xy], cur, gBlend);
}
