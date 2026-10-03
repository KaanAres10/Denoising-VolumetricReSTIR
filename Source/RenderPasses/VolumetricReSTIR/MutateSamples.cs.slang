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

    Round 1.5, light re-selection (strategy bit 2, spec V-B9): an INDEPENDENCE move that draws a fresh light
    sample at the medium sample's scatter point from the renderer's own light samplers -- a light kind
    uniformly among the enabled ones, then the env direction by importance, a point light by its unshadowed
    contribution at the scatter point (spec V-B10; uniformly with gSelectWeightedAnalytic off), or an
    emissive triangle by the emissive sampler and a uniform point on it -- and accepts with
    min(1, p_hat(z) q(x) / (p_hat(x) q(z))). q is a density in p_hat's own mixed measure: solid angle (env),
    a point mass (analytic), area (emissive). With a luminance target a pixel's colour is the colour of the
    light its sample chose, and reuse clumps that choice (emerald: sky-blue or lamp-orange pixels); only a
    move that changes the light reaches it. Medium samples only: there the scatter point is exact, and the
    emissive sampler's back-face test at a wrong shading point would make the proposal asymmetric.

    Free-flight depth (strategy bit 3, spec V-B10): an INDEPENDENCE move on the scatter depth alone. It draws a
    fresh distance along the camera ray from the renderer's own initial distance sampler (analytic free flight on
    the initial candidates' grid, up to the surface), so it jumps across empty gaps and back to the front of the
    medium, which the bounded depth steps cannot. q(t) = sigma_t(t) T(0, t) on that grid, evaluated at the current
    depth by the same march stopped there (FreeFlightPdfAdapterGVDB). Accepts with min(1, p_hat(z) q(x) /
    (p_hat(x) q(z))), whose sigma T factors nearly cancel: what is left is how the light's contribution changes
    along the ray. A proposal that escapes (no scatter before the surface) proposes nothing; its probability does
    not depend on the state, so the step is a self-transition.

    Without the last two, not globally ergodic, by design: the other moves never change lightID or the sample
    type, and bounded depth steps cannot cross an empty gap wider than the largest step. Unbiasedness needs only
    detailed balance within the reachable set and an unbiased W(x0), not ergodicity.

    Two bounces (spec 2026-10-03-two-bounce-mutations-design.md): with MAX_BOUNCES > 1 the light moves act at the
    vertex the light connects from (x2 after an extra bounce), and BounceMoves.slang adds direction, distance and
    rebounce moves on the extra bounce; the pass writes the accepted extra bounce back to the pixel's own entry.
*/
__exported import ReSTIRHelper;
import VolumeTrackingAdapterGVDB; // IVolumeTrackingAdapterGVDB, for the free-flight density
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;
import Utils.Math.MathHelpers;
import Rendering.Lights.LightHelpers; // samplePointLight / sampleDirectionalLight: the weighted analytic proposal
#include "Utils/Math/MathConstants.slangh"

cbuffer CB
{
    uint2 gResolution;
    int gFrameCount;
    int gNumTotalRounds;
    int gMutationCount;
    uint gStrategyMask;                  // bit 0 light-vertex, bit 1 depth, bit 2 light re-selection, bit 3 free flight
    float gLightStepMin, gLightStepMax;  // torus step in u, Kelemen magnitudes
    float gDirStepMin, gDirStepMax;      // radians
    float gDepthStepMin, gDepthStepMax;  // in ray-march steps (volumeDesc.tStep * volumeWorldScaling)
    int gFlightMipLevel;                 // the initial distance sampler's grid (initialOptions.visibilityMipLevel)
    bool gSelectWeightedAnalytic;        // re-selection: point lights by their contribution here (else uniformly)
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
#if MAX_BOUNCES > 1
RWStructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs; // the bounce moves write the pixel's entry back
#else
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
#endif
RWStructuredBuffer<uint> gMutationStats;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
#endif

static const uint kLight = 0;
static const uint kDepth = 1;
static const uint kSelect = 2;
static const uint kFlight = 3;
static const int kMaxBrickSteps = 128; // VolumeTrackingAdapterGVDB.slang's MAX_BRICK_STEPS (a define, so not imported)

/// Records the primary-ray visibility of an evaluation (the camera ray's transmittance up to the sample's
/// depth, which does not depend on the light), so moves that keep the depth reuse it.
struct CachingVisibilityProvider : IExternalVisibilityProvider
{
    float data = -1.f;  // segment 0: camera -> x1
    float data1 = -1.f; // segment 1: x1 -> x2 (two bounces)
    float getVisibility(int bounce) { return bounce == 0 ? data : (bounce == 1 ? data1 : -1.f); }
    [mutating] void putVisibility(int bounce, float visibility) { if (bounce == 0) data = visibility; else if (bounce == 1) data1 = visibility; }
    [mutating] void Initialize() { data = -1.f; data1 = -1.f; }
};

void stat(uint i) { if (gCollectStats) InterlockedAdd(gMutationStats[i], 1u); }

/// The light kinds the re-selection proposes from, each with probability 1 / count: the enabled ones the
/// scene has.
struct LightKinds
{
    bool env, analytic, emissive;
    float pKind;
};

LightKinds lightKinds()
{
    const SamplingOptions o = SAMPLING_OPTIONS;
    LightKinds k;
    k.env = o.useEnvironmentLights;
    k.analytic = o.useAnalyticLights && gScene.getLightCount() > 0;
    k.emissive = o.useEmissiveLights && !gScene.lightCollection.isEmpty();
    const uint count = uint(k.env) + uint(k.analytic) + uint(k.emissive);
    k.pKind = count > 0 ? 1.f / float(count) : 0.f;
    return k;
}

/// Falcor's ndir_to_oct_equal_area_unorm (MathHelpers.slang), written without its in-place swizzle
/// `p = 1.f - p.yx`: in this compile path that statement aliases (p.y = 1 - p.x, then p.x = 1 - p.y with the NEW
/// p.y), which sends every lower-hemisphere direction to the wrong texel -- measured: walk uv (0.9975, 0.0020),
/// inverse (0.5020, 0.0020). The exact inverse of oct_to_ndir_equal_area_unorm, which EnvMapSampler::sample() uses.
float2 octEqualAreaUnorm(float3 n)
{
    const float r = sqrt(1.f - abs(n.z));
    const float phi = atan2(abs(n.y), abs(n.x));
    const float py = r * phi * M_2_PI;
    const float px = r - py;
    float2 p = n.z < 0.f ? float2(1.f - py, 1.f - px) : float2(px, py); // reflect over the diagonal below
    p *= sign(n.xy);
    return p * 0.5f + 0.5f;
}

/// The env sampler's density at world direction dir, per steradian, read the way EnvMapSampler::sample() reads its
/// own: the importance texel that holds the direction's equal-area octahedral coordinates, by index.
/// EnvMapSampler::evalPdf goes through Falcor's inverse map (see octEqualAreaUnorm) and, measured on the plume's
/// sky, disagreed with sample()'s pdf for 99.5% of lower-hemisphere directions, biasing this move by -0.4%.
float envPdf(float3 dir)
{
    const float2 uv = octEqualAreaUnorm(gScene.envMap.toLocal(dir));
    const uint2 dim = uint2(1.f / envMapSampler.importanceInvDim + 0.5f);
    const uint2 texel = min(uint2(uv * float2(dim)), dim - 1u);
    const float average = envMapSampler.importanceMap.Load(int3(0, 0, envMapSampler.importanceBaseMip));
    return envMapSampler.importanceMap.Load(int3(texel, 0)) / average * M_1_4PI;
}

static const float kAnalyticUniformMix = 0.05f; // share of the analytic proposal kept uniform: q > 0 for every light
static const uint kWeightedMaxLights = 256;      // beyond this many analytic lights, propose uniformly (O(N) per step)

/// A point or directional light's weight in the re-selection proposal at scatter point p seen along wo: its
/// unshadowed contribution there (Falcor's samplePointLight: intensity x spot falloff / distance^2) times the phase
/// function -- p_hat without the light's transmittance and the factors every light shares. Deterministic, so the
/// move can evaluate q for the current light and the proposed one alike. Other analytic types: their luminance.
float analyticWeight(uint i, float3 p, float3 wo)
{
    const LightData light = gScene.getLight(i);
    AnalyticLightSample ls;
    bool valid = false;
    if (light.type == (uint)LightType::Point) valid = samplePointLight(p, light, ls);
    else if (light.type == (uint)LightType::Directional) valid = sampleDirectionalLight(p, light, ls);
    else return luminance(light.intensity);
    if (!valid) return 0.f;
    MediumInteraction mi = { p, wo, gScene.volumeDesc.PhaseFunctionConstantG, true };
    const float w = luminance(ls.Li) * mi.phaseFunction(mi.wo, ls.dir);
    return (isnan(w) || isinf(w)) ? 0.f : max(w, 0.f);
}

/// The analytic part of the re-selection proposal at one scatter point: light i with probability
/// (1 - kAnalyticUniformMix) w_i / sum(w) + kAnalyticUniformMix / N (Scripts/tests/test_mutation_measures.py,
/// TestWeightedAnalyticProposal) -- or uniformly (gSelectWeightedAnalytic off, too many lights, sum(w) = 0).
/// Uniform proposals were accepted 6% of the time among 48 lanterns: most lights are far from a given point.
struct AnalyticProposal
{
    float3 p, wo;
    uint count;
    float sum;
    bool weighted;
};

AnalyticProposal analyticProposal(float3 p, float3 wo, bool enabled)
{
    AnalyticProposal a;
    a.p = p;
    a.wo = wo;
    a.count = gScene.getLightCount();
    a.sum = 0.f;
    a.weighted = enabled && gSelectWeightedAnalytic && a.count > 0 && a.count <= kWeightedMaxLights;
    if (a.weighted)
        for (uint i = 0; i < a.count; i++) a.sum += analyticWeight(i, p, wo);
    if (!(a.sum > 0.f) || isinf(a.sum)) a.weighted = false;
    return a;
}

float analyticPmf(AnalyticProposal a, uint i)
{
    const float uniform = 1.f / float(a.count);
    if (!a.weighted) return uniform;
    return (1.f - kAnalyticUniformMix) * analyticWeight(i, a.p, a.wo) / a.sum + kAnalyticUniformMix * uniform;
}

/// One u, split between the uniform share and an inverse-CDF walk over the weights; a rounding overshoot lands on
/// the last light with a positive weight.
uint sampleAnalytic(AnalyticProposal a, float u)
{
    if (!a.weighted || u < kAnalyticUniformMix)
    {
        const float v = a.weighted ? u / kAnalyticUniformMix : u;
        return min(uint(v * float(a.count)), a.count - 1);
    }
    float target = (u - kAnalyticUniformMix) / (1.f - kAnalyticUniformMix) * a.sum;
    uint last = a.count - 1;
    for (uint i = 0; i < a.count; i++)
    {
        const float w = analyticWeight(i, a.p, a.wo);
        if (w > 0.f) last = i;
        target -= w;
        if (target < 0.f) return i;
    }
    return last;
}

/// The re-selection proposal's density at light sample (lightID, lightUV) seen from the scatter point p, in the
/// measure p_hat is a density in: solid angle (env), a point mass (analytic), area (emissive triangle).
float selectPdf(int lightID, float2 lightUV, float3 p, LightKinds k, AnalyticProposal ap)
{
    const int lightCount = (int)gScene.getLightCount();
    if (lightID < 0) return k.env ? k.pKind * envPdf(gScene.envMap.uvToWorld(lightUV)) : 0.f;
    if (lightID < lightCount) return k.analytic ? k.pKind * analyticPmf(ap, uint(lightID)) : 0.f;
    if (!k.emissive) return 0.f;
    const uint tri = uint(lightID - lightCount);
    return k.pKind * emissiveSampler.evalTriangleSelectionPdf(p, float3(0.f), false, tri) / gScene.lightCollection.getTriangle(tri).area;
}

/// Draws the re-selection proposal into z's light fields. False: no light sample (a back-facing emissive
/// triangle, a NaN direction) -- a rejected proposal, which keeps the move symmetric since q never depends on
/// the current state.
bool proposeLight(float3 p, LightKinds k, AnalyticProposal ap, inout SampleGenerator sg, inout Reservoir z, out float envSamplerPdf)
{
    envSamplerPdf = -1.f; // the env sampler's own density for an env proposal (diagnostic: vs selectPdf)
    const uint count = uint(k.env) + uint(k.analytic) + uint(k.emissive);
    const uint pick = min(uint(sampleNext1D(sg) * float(count)), count - 1);
    // The pick-th enabled kind, in the order env, analytic, emissive. No side effects inside conditions: the
    // shader's && does not short-circuit, so `k.env && pick-- == 0` decremented pick with env disabled too, and
    // every proposal fell through to the (empty) emissive branch -- 0 of 50M accepted on bunnyrgb.
    uint kind = 3, n = 0;
    if (k.env) { if (pick == n) kind = 0; n++; }
    if (k.analytic) { if (pick == n) kind = 1; n++; }
    if (k.emissive) { if (pick == n) kind = 2; n++; }
    if (kind == 0)
    {
        EnvMapSample es;
        envMapSampler.sample(sampleNext2D(sg), es);
        envSamplerPdf = k.pKind * es.pdf;
        // Diagnostics (VR_MUT_STATS): envPdf and Falcor's evalPdf at the sampled direction vs sample()'s own pdf,
        // split by hemisphere -- how the octahedral-inverse miscompile (see octEqualAreaUnorm) was found.
        if (gCollectStats)
        {
            const float3 local = gScene.envMap.toLocal(es.dir);
            if (abs(envPdf(es.dir) / es.pdf - 1.f) > 1e-3f) stat(local.z >= 0.f ? 16 : 17);
            if (local.z < 0.f) stat(18);
            if (abs(envMapSampler.evalPdf(es.dir) / es.pdf - 1.f) > 1e-3f) stat(19);
        }
        if (any(isnan(es.dir))) return false;
        z.lightID = -1;
        z.lightUV = gScene.envMap.worldToUv(es.dir);
        return true;
    }
    if (kind == 1)
    {
        z.lightID = (int)sampleAnalytic(ap, sampleNext1D(sg));
        z.lightUV = float2(0.f);
        return true;
    }
    if (kind != 2) return false;
    // Emissive: the sampler picks the triangle (its selection pdf is what selectPdf evaluates); the point on it
    // is drawn here, uniform in the area-uniform u the reservoir stores.
    TriangleLightSample ls;
    if (!emissiveSampler.sampleLight(p, float3(0.f), false, sg, ls)) return false;
    z.lightID = (int)(ls.triangleIndex + gScene.getLightCount());
    z.lightUV = sampleNext2D(sg);
    return true;
}

/// The density of the renderer's initial distance sampler (VolumeTrackingAdapterGVDB.slang's
/// SampleMediumAnalyticAdapterGVDB, nearest sampler) at tTarget: sigma_t(t) T(0, t), by the same traversal, voxel
/// lookups and optical-thickness sums, stopped at the point instead of at a sampled distance. 0 where the sampler
/// never lands: outside the volume, or in an empty node the traversal skips.
///
/// It marches the sampler's own ray to its own end and stops itself at the point. Cutting the ray at the point
/// instead (tMax = t) changes the traversal: VolumeTrackingGVDB advances dda.t.x by epsilon (0.01, in t) after each
/// brick and ends the march once that passes tMax, so a point within epsilon after a brick's entry was never reached
/// -- q = 0 for 7.4% of the plume's proposals and 11% of its current states (VR_MUT_STATS), while the sampler lands
/// there. On the full ray: 20 of 30M proposals differ, by float rounding next to a voxel boundary.
struct FreeFlightPdfAdapterGVDB : IVolumeTrackingAdapterGVDB
{
    float pdf;
    float opticalThickness;
    float tFar;
    float tTarget; // the point, set before the march (the march runs the sampler's own ray, to its own end)
    uint reason;   // diagnostics: 0 found in a voxel, 1 beyond the volume, 2 march ended before it, 3 never reached a brick
    float sigmaFound, tauBefore, tEntry, tExit; // diagnostics: the voxel the point is in

    [mutating] void InitializeValues()
    {
        pdf = 0.f;
        opticalThickness = 0.f;
        tFar = 0.f;
        tTarget = 0.f;
        reason = 3;
        sigmaFound = tauBefore = tEntry = tExit = 0.f;
    }

    [mutating] void SetRayInfo(float tNear_, float tFar_, VolRay ray_)
    {
        tFar = tFar_;
    }

    [mutating] void ExecuteStartStep() {}

    [mutating] bool ExecuteMainStep(in HDDAState dda, float3 vmin_leaf, float3 o, float4 brickDensityBounds, int mipLevel, inout float t, inout SampleGenerator sg)
    {
        if (tTarget > tFar) { reason = 1; return true; } // beyond the volume
        HDDAState dda_leaf = dda;
        dda_leaf.PrepareLeaf(vmin_leaf);
        const AtlasMip atlasMip = loadAtlasMip(mipLevel);
        for (int iter = 0; iter < kMaxBrickSteps && all(dda_leaf.p >= 0 && dda_leaf.p < atlasMip.resolution()); iter++)
        {
            dda_leaf.Next();
            const float maxDeltaT = min(tFar - t, dda_leaf.t.y - t);
            const float currentTMax = min(tFar, dda_leaf.t.y);
            const float sigma_t = DensityInAtlas(dda_leaf.p + o + 0.5f, mipLevel, false, atlasMip) * gScene.volumeDesc.sigma_t;
            // The sampler lands in this voxel at t + dT < its exit: the point is in it if it lies before the exit.
            if (tTarget < dda_leaf.t.y)
            {
                pdf = sigma_t * exp(-(opticalThickness + (tTarget - t) * sigma_t));
                reason = 0;
                sigmaFound = sigma_t;
                tauBefore = opticalThickness;
                tEntry = t;
                tExit = dda_leaf.t.y;
                return true;
            }
            opticalThickness += maxDeltaT * sigma_t;
            t = currentTMax;
            if (t >= tFar) { reason = 2; return true; }
            dda_leaf.Step();
        }
        return false;
    }

    [mutating] void ExecuteEndStep() {}
};

/// q(t) of the free-flight move: the initial distance sampler's density at depth t along ray, on its grid, up to
/// ray.tMax (the surface, or none).
float flightPdf(VolRay ray, float t, inout SampleGenerator sg, out FreeFlightPdfAdapterGVDB e)
{
    FreeFlightPdfAdapterGVDB a;
    a.InitializeValues();
    a.reason = 1;
    if (t > 0.f && t < ray.tMax)
    {
        a.tTarget = t;
        a.reason = 3;
        VolumeTrackingGVDB(ray, gFlightMipLevel, sg, a, false); // the adapter draws no random numbers
    }
    e = a;
    return a.pdf;
}

/// Diagnostics (VR_MUT_STATS): the first proposal whose evaluated density disagrees with the sampler's beyond float
/// rounding, as float bits in stats 40-48 (stat 39 = taken).
void captureFlight(float z, float qz, float trz, FreeFlightPdfAdapterGVDB e)
{
    uint old;
    InterlockedCompareExchange(gMutationStats[39], 0u, 1u, old);
    if (old != 0u) return;
    gMutationStats[40] = asuint(z);
    gMutationStats[41] = asuint(qz);
    gMutationStats[42] = asuint(trz);
    gMutationStats[43] = asuint(e.pdf);
    gMutationStats[44] = asuint(e.sigmaFound);
    gMutationStats[45] = asuint(e.tauBefore);
    gMutationStats[46] = asuint(e.tEntry);
    gMutationStats[47] = asuint(e.tExit);
    gMutationStats[48] = e.reason;
}

/// Kelemen 2002 magnitude with a random sign: symmetric about 0.
float kelemenStep(float lo, float hi, float2 u)
{
    const float s = hi * exp(-log(hi / lo) * u.x);
    return u.y < 0.5f ? s : -s;
}

#if MAX_BOUNCES > 1
#include "BounceMoves.slang"
typedef OverrideArrayDataProvider MutationDataProvider;
#else
typedef StructuredBufferArrayDataProvider MutationDataProvider;
#endif

/// Which strategies can move this sample, from its type: medium or not, and its light kind -- which only the
/// re-selection changes, so the loop asks again for the current state (an inapplicable pick is a self-transition).
/// b: the sample's extra bounce (two bounces; unused at one).
uint applicable(Reservoir r, ExtraBounceReservoir b)
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
    if (inMedium) mask |= (1u << kDepth) | (1u << kFlight);
    // Any light sample in the medium (a point light too), but not an emission path: its p_hat is the medium's
    // own emission, a kind the proposal never draws.
    const bool lightSample = r.lightID == -1 || r.lightID >= 0;
    if (inMedium && lightSample && decodePathTag(r.sampledPixel) != 1) mask |= 1u << kSelect;
#if MAX_BOUNCES > 1
    if (decodeMaxIndirectBounces(r.sampledPixel) == 1)
    {
        // Tag 1: lightID / lightUV hold x2's position, not a light. A surface x2: the re-selection needs a medium vertex.
        if (decodePathTag(r.sampledPixel) == 1) mask &= ~((1u << kLight) | (1u << kSelect));
        else if (decodeWiDist(b.wi_dist, false).w == kRayTMax) mask &= ~(1u << kSelect);
        if (inMedium) mask |= bounceMoves(r, b);
    }
#endif
    return mask & gStrategyMask;
}

float pHat(Reservoir r, VolRay ray, inout SampleGenerator sg, MutationDataProvider dp,
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
#if MAX_BOUNCES > 1
    ExtraBounceReservoir xb = gCurExtraBounceReservoirs[r.extraBounceStartId]; // the chain's extra bounce
#else
    ExtraBounceReservoir xb = {}; // no extra bounce at one bounce
#endif
    const uint moves = applicable(r, xb);
    if (moves == 0) return; // every step would be a self-transition

    // A stream no other pass uses: other passes seed with gNumTotalRounds * gFrameCount + round < 2^31.
    SampleGenerator sg = SampleGenerator(pixelPos, uint(gNumTotalRounds * gFrameCount) | 0x80000000u);
    CameraRay cameraRay = computeRayPinholeScaled(gScene.camera, pixelPos, 1, 0.5f, gResolution);
    const VolRay ray = { cameraRay.origin, cameraRay.dir, 0, kRayTMax };
#ifdef SURFACE_SCENE
    VBufferItem vItem = gVBuffer[pixelId];
    const VolRay flightRay = { cameraRay.origin, cameraRay.dir, 0, vItem.rayT }; // as Generate Samples' candidates
#else
    const VolRay flightRay = ray;
#endif
    MutationDataProvider dp;
    dp.data = gCurExtraBounceReservoirs;
#if MAX_BOUNCES > 1
    dp.index = r.extraBounceStartId; // every p_hat in the chain sees x's extra bounce, not the buffer's
    dp.value = xb;
#endif

    CachingVisibilityProvider vis0;
    vis0.Initialize();
    const float p0 = pHat(r, ray, sg, dp, VBUFFERITEM vis0);
    if (!(p0 > 0.f)) { stat(4); return; }
    if (p0 != r.p_y) stat(5);

    Reservoir x = r;
    float px = p0;
    float primaryVis = vis0.data;
#if MAX_BOUNCES > 1
    float bounceVis = vis0.data1; // segment 1 of x
#endif
    const float depthUnit = gScene.volumeDesc.tStep * gScene.volumeWorldScaling;
    const uint enabledCount = countbits(gStrategyMask);
    const LightKinds kinds = lightKinds();
    float qFlight = -1.f; // q(x) of the free-flight move while x's depth stays; -1 = not evaluated yet

    for (int it = 0; it < gMutationCount; it++)
    {
        // Fixed, state-independent strategy probabilities; an inapplicable pick is a self-transition.
        const uint pick = min(uint(sampleNext1D(sg) * enabledCount), enabledCount - 1);
        uint s = firstbitlow(gStrategyMask);
        for (uint k = 0; k < pick; k++) s = firstbitlow(gStrategyMask & ~((2u << s) - 1u));
        if ((applicable(x, xb) & (1u << s)) == 0)
        {
        #if MAX_BOUNCES > 1
            if (s >= kDirection) stat(57); // a bounce move with nothing to move
        #endif
            continue;
        }

        Reservoir z = x;
        CachingVisibilityProvider visz;
        visz.Initialize();
    #if MAX_BOUNCES > 1
        if (s >= kDirection)
        {
            const float3 x1 = ray.origin + x.depth * ray.dir;
            const Bounce bx = readBounce(x, xb, x1);
            const uint k = s - kDirection; // 0 direction, 1 distance, 2 rebounce
            stat(49 + 2 * k);
            ExtraBounceReservoir zb = xb;
            float qx = 1.f, qz = 1.f;
            float3 zDir = bx.dir;
            float zDist = bx.dist;
            float3 zX2 = bx.x2;
            if (s == kRebounce)
            {
                if (!proposeRebounce(x1, -ray.dir, sg, zDir, zDist)) { stat(55); continue; } // escaped or reached a surface
                zX2 = x1 + zDist * zDir;
                qx = rebounceQ(x1, -ray.dir, bx.dir, bx.dist, bx.emissive, sg);
                if (!(qx > 0.f) || isinf(qx)) { stat(56); continue; }
            }
            else if (s == kDirection)
            {
                if (bx.emissive) zX2 = bx.x2 + isotropicStep(depthUnit, sg);
                else zDir = rotateDirection(bx.dir, sg);
            }
            else // kDistance
            {
                zDist = bx.dist + depthUnit * kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg));
                if (!(zDist > 0.f)) { stat(58); continue; } // p_hat = 0: rejected, never resampled
            }
            if (bx.emissive) encodeEmissivePosition(zX2, z.lightID, z.lightUV);
            else zb.wi_dist = encodeWiDist(float4(zDir, zDist));
            if (s == kRebounce)
            {
                const Bounce bz = readBounce(z, zb, x1); // the stored state: what p_hat sees
                qz = rebounceQ(x1, -ray.dir, bz.dir, bz.dist, bz.emissive, sg);
                if (!(qz > 0.f) || isinf(qz)) { stat(56); continue; }
            }
            MutationDataProvider dpz = dp;
            dpz.value = zb;
            visz.data = primaryVis; // x1 did not move
            const float pz = pHat(z, ray, sg, dpz, VBUFFERITEM visz);
            if (pz > 0.f && sampleNext1D(sg) * px * qz < pz * qx)
            {
                x = z;
                xb = zb;
                dp.value = xb;
                px = pz;
                bounceVis = visz.data1;
                stat(50 + 2 * k);
            }
            continue;
        }
    #endif
        if (s == kSelect)
        {
            // Independence move: the acceptance carries q(x) / q(z), both at the same scatter point.
        #if MAX_BOUNCES > 1
            // The light connects at the last vertex: x2 after an extra bounce, seen along -omega.
            const Bounce bs = readBounce(x, xb, ray.origin + x.depth * ray.dir);
            const float3 p = bs.x2;
            const float3 wo = bs.present ? -bs.dir : -ray.dir;
        #else
            const float3 p = ray.origin + x.depth * ray.dir;
            const float3 wo = -ray.dir;
        #endif
            if (kinds.pKind == 0.f) continue;
            stat(6);
            float envSamplerPdf;
            const AnalyticProposal ap = analyticProposal(p, wo, kinds.analytic);
            if (!proposeLight(p, kinds, ap, sg, z, envSamplerPdf)) { stat(8); continue; }
            const uint zKind = z.lightID < 0 ? 0 : (z.lightID < (int)gScene.getLightCount() ? 1 : 2);
            stat(11 + zKind);
            const float qx = selectPdf(x.lightID, x.lightUV, p, kinds, ap);
            const float qz = selectPdf(z.lightID, z.lightUV, p, kinds, ap);
            if (gCollectStats && envSamplerPdf >= 0.f)
            {
                stat(15);
                if (abs(qz - envSamplerPdf) > 1e-3f * envSamplerPdf) stat(14);
            }
            if (!(qx > 0.f) || !(qz > 0.f) || isinf(qx) || isinf(qz)) { stat(9); continue; }
            visz.data = primaryVis; // the depth did not move
        #if MAX_BOUNCES > 1
            visz.data1 = bounceVis; // nor did the extra bounce
        #endif
            const float pz = pHat(z, ray, sg, dp, VBUFFERITEM visz);
            if (!(pz > 0.f)) stat(10);
            if (pz > 0.f && sampleNext1D(sg) * px * qz < pz * qx)
            {
                x = z;
                px = pz;
                stat(7);
                stat(32 + zKind); // accepted, by the proposed light's kind: env, analytic, emissive
            }
            continue;
        }
        if (s == kFlight)
        {
            // Independence move on the depth: the acceptance carries q(x) / q(z), both on the same ray.
            stat(20);
            float hit[MaxInitialSampleCount];
            float qs[MaxInitialSampleCount];
            float trs[MaxInitialSampleCount];
            SampleMediumAnalyticGeneric(flightRay, sg, false, hit, gFlightMipLevel, qs, trs, 1);
            if (!(hit[0] > 0.f) || !(hit[0] < kRayTMax)) { stat(22); continue; } // escaped: no proposal
            z.depth = hit[0];
            const float qz = qs[0];
            if (qFlight < 0.f)
            {
                FreeFlightPdfAdapterGVDB ex;
                qFlight = flightPdf(flightRay, x.depth, sg, ex);
                // Diagnostics (VR_MUT_STATS): why q(x) is 0 -- beyond the volume, the march ended first, an empty
                // node, a voxel of zero density.
                if (gCollectStats && !(qFlight > 0.f)) stat(ex.reason == 0 ? 31 : 27 + ex.reason);
            }
            // Diagnostics (VR_MUT_STATS): the evaluator at the proposal vs the sampler's own density; beyond what
            // float rounding of z = t + dT explains (the exponent's error ~ sigma ulp(z)), the first case captured.
            if (gCollectStats)
            {
                FreeFlightPdfAdapterGVDB ez;
                const float qe = flightPdf(flightRay, z.depth, sg, ez);
                const float rel = abs(qe - qz) / qz;
                if (rel > 1e-3f)
                {
                    stat(23);
                    if (!(qe > 0.f)) stat(25);
                    const float sigma = qz / max(trs[0], 1e-30f);
                    const float ulp = asfloat(asuint(z.depth) + 1u) - z.depth;
                    if (rel > 4.f * sigma * ulp + 1e-4f) { stat(26); captureFlight(z.depth, qz, trs[0], ez); }
                }
            }
            if (!(qz > 0.f) || isinf(qz)) { stat(27); continue; }
            if (!(qFlight > 0.f)) { stat(24); continue; }
            const float pz = pHat(z, ray, sg, dp, VBUFFERITEM visz);
            if (pz > 0.f && sampleNext1D(sg) * px * qz < pz * qFlight)
            {
                x = z;
                px = pz;
                primaryVis = visz.data;
            #if MAX_BOUNCES > 1
                bounceVis = visz.data1;
            #endif
                qFlight = qz;
                stat(21);
            }
            continue;
        }
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
        #if MAX_BOUNCES > 1
            visz.data1 = bounceVis; // nor did the extra bounce
        #endif
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
        #if MAX_BOUNCES > 1
            bounceVis = visz.data1;
        #endif
            if (s == kDepth) qFlight = -1.f; // the depth moved
            stat(s == kLight ? 1 : 3);
        }
    }

    // Eq. 16 in this reservoir's representation W = runningSum / (p_y M):
    // W(z) = p_hat(x0)/p_hat(z) W(x0)  <=>  runningSum *= p_hat(x0)/p_y_old, p_y = p_hat(z).
    r.runningSum *= p0 / r.p_y;
    r.depth = x.depth;
    r.lightID = x.lightID; // the re-selection changes the light itself
    r.lightUV = x.lightUV;
    r.p_y = px;
    gCurReservoirs[pixelId] = r;
#if MAX_BOUNCES > 1
    gCurExtraBounceReservoirs[r.extraBounceStartId] = xb; // the extra bounce the chain ended on
#endif
}
