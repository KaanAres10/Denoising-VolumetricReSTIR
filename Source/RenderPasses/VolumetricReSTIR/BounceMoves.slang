/** Two-bounce moves for MutateSamples.cs.slang (docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md),
    included only when MAX_BOUNCES > 1, so the one-bounce pass is textually unchanged.

    A 2-bounce sample is x1 at `depth` on the camera ray plus one extra bounce:
      - path tag 0: the pixel's ExtraBounceReservoir holds (omega, d) from x1 (encodeWiDist), the light connects at
        x2 = x1 + d omega, and p_hat is a density in dt1 domega dd (light measure); d == kRayTMax marks a surface x2;
      - path tag 1: x2 emits; its world position is packed into lightID / lightUV (encodeEmissivePosition) and p_hat
        carries 1/d^2: a density in dt1 dV(x2). There is no light sample.
    Moves (fixed strategy probabilities, an inapplicable pick a self-transition, as in the pass):
      - kDirection: rotate omega by a Kelemen angle about itself (symmetric in solid angle; the env move's math) --
        tag 1: an isotropic Kelemen step of x2 (symmetric in volume);
      - kDistance: d + a Kelemen step (symmetric in dd), tag 0 only;
      - kRebounce: an independence proposal, omega from the phase function at x1 and d by free flight along it
        (q = phase sigma_t T, / d^2 for tag 1), accepted with min(1, p_hat(z) q(x) / (p_hat(x) q(z))); a draw that
        escapes or reaches a surface is rejected. q is evaluated at STORED states (encoded then decoded), so the
        ratio sees what p_hat sees.
    Surface x2 vertices are never moved and never proposed: the kernel restricted to medium x2 keeps p_hat.
    Replicas: Scripts/tests/test_mutation_measures.py, TestTwoBounceMeasures. */

static const uint kDirection = 4;
static const uint kDistance = 5;
static const uint kRebounce = 6;

/// This pixel's extra-bounce entry as the chain's current state (or a proposal); every other entry from the buffer.
struct OverrideArrayDataProvider : IArrayDataProvider
{
    RWStructuredBuffer<ExtraBounceReservoir> data;
    int index;
    ExtraBounceReservoir value;
    ExtraBounceReservoir getData(int i) { return i == index ? value : data[i]; }
};

/// The extra bounce as the moves see it.
struct Bounce
{
    bool present;  // one extra bounce
    bool emissive; // path tag 1: x2 is a stored position
    bool surface;  // tag 0 with x2 on a surface
    float3 x2;     // tag 1: the stored position; tag 0: x1 + d omega
    float3 dir;    // omega (tag 0) or normalize(x2 - x1) (tag 1)
    float dist;    // d (tag 0) or |x2 - x1| (tag 1)
};

Bounce readBounce(Reservoir r, ExtraBounceReservoir b, float3 x1)
{
    Bounce o;
    o.present = decodeMaxIndirectBounces(r.sampledPixel) == 1;
    o.emissive = o.present && decodePathTag(r.sampledPixel) == 1;
    o.surface = false;
    o.x2 = x1;
    o.dir = float3(0.f, 0.f, 1.f);
    o.dist = 0.f;
    if (!o.present) return o;
    if (o.emissive)
    {
        o.x2 = decodeEmissivePosition(r.lightID, r.lightUV);
        const float3 v = o.x2 - x1;
        o.dist = length(v);
        o.dir = v / o.dist;
        return o;
    }
    const float4 wd = decodeWiDist(b.wi_dist, false);
    o.surface = wd.w == kRayTMax;
    o.dir = wd.xyz;
    o.dist = wd.w;
    o.x2 = x1 + o.dist * o.dir;
    return o;
}

/// The bounce moves that can act on this sample (masked by the caller with gStrategyMask).
uint bounceMoves(Reservoir r, ExtraBounceReservoir b)
{
    if (decodeMaxIndirectBounces(r.sampledPixel) != 1) return 0u;
    if (decodePathTag(r.sampledPixel) == 1) return (1u << kDirection) | (1u << kRebounce);
    if (decodeWiDist(b.wi_dist, false).w == kRayTMax) return 0u; // x2 on a surface: not moved
    return (1u << kDirection) | (1u << kDistance) | (1u << kRebounce);
}

/// The ray of the extra bounce from x1 along dir, up to the first surface (the extra bounce's distance sampler
/// in ComputeInitialSample.slang stops there too).
VolRay bounceRay(float3 x1, float3 dir)
{
#ifdef SURFACE_SCENE
    const float tMax = FindSurfaceHit(x1, dir, 0, kRayTMax).rayT;
#else
    const float tMax = kRayTMax;
#endif
    return { x1, dir, 0, tMax };
}

/// The env move's rotation (MutateSamples.cs.slang, kLight), here for omega: symmetric in solid angle.
float3 rotateDirection(float3 w, inout SampleGenerator sg)
{
    const float theta = abs(kelemenStep(gDirStepMin, gDirStepMax, sampleNext2D(sg)));
    const float phi = M_2PI * sampleNext1D(sg);
    const float3 t = perp_stark(w);
    const float3 b = cross(w, t);
    return normalize(cos(theta) * w + sin(theta) * (cos(phi) * t + sin(phi) * b));
}

/// A Kelemen length (in ray-march steps) in a uniform direction: symmetric in volume.
float3 isotropicStep(float unit, inout SampleGenerator sg)
{
    const float len = unit * abs(kelemenStep(gDepthStepMin, gDepthStepMax, sampleNext2D(sg)));
    return len * sample_sphere(sampleNext2D(sg));
}

/// q of the rebounce move at a stored extra bounce: phase(wo, dir) times the free-flight density at dist along the
/// bounce ray (per steradian per length); tag 1 divides by dist^2, p_hat being a density in volume there.
float rebounceQ(float3 x1, float3 wo, float3 dir, float dist, bool emissive, inout SampleGenerator sg)
{
    MediumInteraction mi = { x1, wo, gScene.volumeDesc.PhaseFunctionConstantG, true };
    FreeFlightPdfAdapterGVDB e;
    const float q = mi.phaseFunction(wo, dir) * flightPdf(bounceRay(x1, dir), dist, sg, e);
    return emissive ? q / (dist * dist) : q;
}

/// The rebounce draw: omega from the phase function, d from the free-flight sampler along it. False on an escape
/// or a surface: no medium vertex, a rejected proposal. qSampler: the sampler's own density at d (diagnostics).
bool proposeRebounce(float3 x1, float3 wo, inout SampleGenerator sg, out float3 dir, out float dist, out float qSampler)
{
    MediumInteraction mi = { x1, wo, gScene.volumeDesc.PhaseFunctionConstantG, true };
    dir = float3(0.f, 0.f, 1.f);
    mi.Sample_p(wo, dir, sampleNext2D(sg));
    const VolRay r = bounceRay(x1, dir);
    float hit[MaxInitialSampleCount];
    float qs[MaxInitialSampleCount];
    float trs[MaxInitialSampleCount];
    SampleMediumAnalyticGeneric(r, sg, false, hit, gFlightMipLevel, qs, trs, 1);
    dist = hit[0];
    qSampler = qs[0];
    return hit[0] > 0.f && hit[0] < r.tMax && hit[0] < kRayTMax;
}
