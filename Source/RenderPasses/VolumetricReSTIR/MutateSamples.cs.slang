/** Mutate Samples: Metropolis-Hastings moves on every pixel's reservoir sample after temporal reuse
    (Sawhney et al. 2024, "Decorrelating ReSTIR Samplers via MCMC Mutations"), to decorrelate what
    spatiotemporal reuse shares. Single scattering, round 1:

      - light-vertex perturbation (their Sec. 4.2): an emissive triangle's area-uniform u steps on the torus
        (the triangle stays fixed); an env-map direction rotates by a log-uniform angle about itself;
      - propagation perturbation of the scatter depth along the camera ray (Pauly et al. 2000, Sec. 5.1).

    Both proposals are symmetric in the measure p_hat is a density in (dt x area, dt x solid angle; see
    Scripts/tests/test_mutation_measures.py), so a step accepts with min(1, p_hat(z) / p_hat(x)). p_hat is
    the temporal pass's own target (spatial sampling options, deterministic trackers only -- the host
    guards that), and the result is written back per Eq. 16: W(z) = p_hat(x0) / p_hat(z) W(x0).

    Not globally ergodic, by design: moves never change lightID or the sample type, and bounded depth steps
    cannot cross an empty gap wider than the largest step. Unbiasedness needs only detailed balance within
    the reachable set and an unbiased W(x0), not ergodicity.
*/
__exported import ReSTIRHelper;
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;
import Utils.Math.MathHelpers;
#include "Utils/Math/MathConstants.slangh"

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
#include "SpecializeOptions.slangh"
#if VR_SPECIALIZE
static const SamplingOptions kSamplingOptions = VR_SAMPLING_OPTIONS;
#define SAMPLING_OPTIONS specializeOptions(kSamplingOptions, gSamplingOptions)
#else
#define SAMPLING_OPTIONS gSamplingOptions
#endif

RWStructuredBuffer<Reservoir> gCurReservoirs;
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
RWStructuredBuffer<uint> gMutationStats;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
#endif

static const uint kLight = 0;
static const uint kDepth = 1;

/// Records the primary-ray visibility of an evaluation (the camera ray's transmittance up to the sample's
/// depth, which does not depend on the light), so moves that keep the depth reuse it.
struct CachingVisibilityProvider : IExternalVisibilityProvider
{
    float data = -1.f;
    float getVisibility(int bounce) { return bounce == 0 ? data : -1.f; }
    [mutating] void putVisibility(int bounce, float visibility) { if (bounce == 0) data = visibility; }
    [mutating] void Initialize() { data = -1.f; }
};

void stat(uint i) { if (gCollectStats) InterlockedAdd(gMutationStats[i], 1u); }

/// Which strategies can move this sample. Depends only on the sample's TYPE, which no move changes.
uint applicable(Reservoir r)
{
    const bool selfEmission = r.lightID == kSelfEmissionLightID;
    const bool inMedium = r.depth != kRayTMax;
#ifdef SURFACE_SCENE
    const bool hasShadingPoint = true;     // kRayTMax = surface hit; an invalid hit gives p_hat = 0
#else
    const bool hasShadingPoint = inMedium; // kRayTMax = background, no light sample
#endif
    const int lightCount = (int)gScene.getLightCount();
    const bool env = r.lightID < 0 && !selfEmission; // -1; delta (analytic) lights are never moved
    const bool emissiveTri = r.lightID >= lightCount;
    uint mask = 0;
    if (hasShadingPoint && !selfEmission && (env || emissiveTri)) mask |= 1u << kLight;
    if (inMedium) mask |= 1u << kDepth;
    return mask & gStrategyMask;
}

/// Kelemen 2002 magnitude with a random sign: symmetric about 0.
float kelemenStep(float lo, float hi, float2 u)
{
    const float s = hi * exp(-log(hi / lo) * u.x);
    return u.y < 0.5f ? s : -s;
}

float pHat(Reservoir r, VolRay ray, inout SampleGenerator sg, StructuredBufferArrayDataProvider dp,
           VBUFFERDECLARE inout CachingVisibilityProvider vis)
{
    const float p = evaluate_P_hat(ray, sg, envMapSampler, emissiveSampler, VBUFFERITEM dp, SAMPLING_OPTIONS, r, vis, false, true, false);
    return (isnan(p) || isinf(p)) ? 0.f : p;
}

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
    const int2 pixelPos = DTid.xy;
    printSetPixel(pixelPos);
    const int pixelId = getPixelID(pixelPos, gResolution);

    Reservoir r = gCurReservoirs[pixelId];
    // Empty or invalid reservoirs are never touched: the update below divides by p_y.
    if (!(r.runningSum > 0.f) || isinf(r.runningSum) || !(r.M > 0.f) || !(r.p_y > 0.f) || isinf(r.p_y)) { stat(4); return; }
    const uint moves = applicable(r);
    if (moves == 0) return; // every step would be a self-transition

    // A stream no other pass uses: other passes seed with gNumTotalRounds * gFrameCount + round < 2^31.
    SampleGenerator sg = SampleGenerator(pixelPos, uint(gNumTotalRounds * gFrameCount) | 0x80000000u);
    CameraRay cameraRay = computeRayPinholeScaled(gScene.camera, pixelPos, 1, 0.5f, gResolution);
    const VolRay ray = { cameraRay.origin, cameraRay.dir, 0, kRayTMax };
#ifdef SURFACE_SCENE
    VBufferItem vItem = gVBuffer[pixelId];
#endif
    StructuredBufferArrayDataProvider dp;
    dp.data = gCurExtraBounceReservoirs;

    CachingVisibilityProvider vis0;
    vis0.Initialize();
    const float p0 = pHat(r, ray, sg, dp, VBUFFERITEM vis0);
    if (!(p0 > 0.f)) { stat(4); return; }
    if (p0 != r.p_y) stat(5);

    Reservoir x = r;
    float px = p0;
    float primaryVis = vis0.data;
    const float depthUnit = gScene.volumeDesc.tStep * gScene.volumeWorldScaling;
    const uint enabledCount = countbits(gStrategyMask);

    for (int it = 0; it < gMutationCount; it++)
    {
        // Fixed, state-independent strategy probabilities; an inapplicable pick is a self-transition.
        const uint pick = min(uint(sampleNext1D(sg) * enabledCount), enabledCount - 1);
        uint s = firstbitlow(gStrategyMask);
        for (uint k = 0; k < pick; k++) s = firstbitlow(gStrategyMask & ~((2u << s) - 1u));
        if ((moves & (1u << s)) == 0) continue;

        Reservoir z = x;
        CachingVisibilityProvider visz;
        visz.Initialize();
        if (s == kLight)
        {
            if (x.lightID < 0) // environment map: rotate on the sphere, symmetric in solid angle
            {
                const float3 w = gScene.envMap.uvToWorld(x.lightUV);
                const float theta = abs(kelemenStep(gDirStepMin, gDirStepMax, sampleNext2D(sg)));
                const float phi = M_2PI * sampleNext1D(sg);
                const float3 t = perp_stark(w);
                const float3 b = cross(w, t);
                const float3 w2 = cos(theta) * w + sin(theta) * (cos(phi) * t + sin(phi) * b);
                z.lightUV = gScene.envMap.worldToUv(normalize(w2));
            }
            else // emissive triangle: torus step in the area-uniform u, same triangle
            {
                z.lightUV = frac(x.lightUV + float2(kelemenStep(gLightStepMin, gLightStepMax, sampleNext2D(sg)),
                                                    kelemenStep(gLightStepMin, gLightStepMax, sampleNext2D(sg))));
            }
            visz.data = primaryVis; // the depth did not move
            stat(0);
        }
        else // s == kDepth: Pauly's propagation perturbation along the camera ray
        {
            z.depth = x.depth + depthUnit * kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg));
            stat(2);
            if (!(z.depth > 0.f)) continue; // p_hat = 0: rejected, never resampled
        }
        const float pz = pHat(z, ray, sg, dp, VBUFFERITEM visz);
        if (pz > 0.f && sampleNext1D(sg) * px < pz)
        {
            x = z;
            px = pz;
            primaryVis = visz.data;
            stat(s == kLight ? 1 : 3);
        }
    }

    // Eq. 16 in this reservoir's representation W = runningSum / (p_y M):
    // W(z) = p_hat(x0)/p_hat(z) W(x0)  <=>  runningSum *= p_hat(x0)/p_y_old, p_y = p_hat(z).
    r.runningSum *= p0 / r.p_y;
    r.depth = x.depth;
    r.lightUV = x.lightUV;
    r.p_y = px;
    gCurReservoirs[pixelId] = r;
}
