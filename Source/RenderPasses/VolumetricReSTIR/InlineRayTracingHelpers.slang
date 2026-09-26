import Scene.Scene;
import Scene.Shading;
import Scene.RaytracingInline;             // getCommittedTriangleHit + gScene.rtAccel inline ray tracing
__exported import Rendering.Materials.IMaterialInstance; // re-export BSDFSample/ShadingData helpers to importers
import Utils.Math.MathHelpers;
#include "Utils/Math/MathConstants.slangh"
import Utils.Sampling.SampleGenerator;
import Utils.Geometry.GeometryHelpers;

// ---------------------------------------------------------------------------------------------
// [Falcor 8.0 port] Surface-scene inline ray tracing + surface shading, used when the pass runs
// with mUseSurfaceScene (SURFACE_SCENE) — i.e. the Bistro / Emerald Square scenes. The Falcor 4.x
// material API (evalBSDF, ShadingData.emissive/.N, prepareShadingData(materials[],...)) was
// replaced by the 8.0 MaterialSystem / IMaterialInstance. This file bridges the pass's original
// surface interface (SurfaceHitInfo / computeSurfaceShadingInfo / isEmissive / evalBSDFCosine) onto
// the 8.0 material system so the shaders can stay otherwise unchanged. Ray tracing uses the scene's
// own acceleration structure gScene.rtAccel (no separate host binding needed in 8.0).
// ---------------------------------------------------------------------------------------------

float3 computeScatterRayOrigin(float3 posW, float3 faceN)
{
    return computeRayOrigin(posW, faceN);
}

/** A surface hit. Raw fields kept in the original (Falcor 4.x) layout so that the reservoir, which
    stores/reconstructs a hit as { meshInstanceID, primitiveID, barycentrics, rayT }, keeps working.
    Note gScene's GeometryInstanceID.index == InstanceID() + GeometryIndex(), i.e. exactly what the
    fork stored as meshInstanceID, so it round-trips into an 8.0 TriangleHit. */
struct SurfaceHitInfo
{
    uint    meshInstanceID;
    uint    primitiveIndex;
    float2  barycentrics;
    float   rayT;

    static const uint kInvalidIndex = 0xffffffff;

    static SurfaceHitInfo createInvalidHitInfo() { return { kInvalidIndex, kInvalidIndex, float2(0), FLT_MAX }; }
    [mutating] void setInvalid() { rayT = FLT_MAX; }
    bool isValidHit() { return rayT != FLT_MAX; }

    float3 getBarycentricWeights() { return float3(1.f - barycentrics.x - barycentrics.y, barycentrics.x, barycentrics.y); }

    TriangleHit getTriangleHit()
    {
        TriangleHit th;
        th.instanceID = { meshInstanceID };
        th.primitiveIndex = primitiveIndex;
        th.barycentrics = barycentrics;
        return th;
    }
};

/** Shading data for a surface hit. Bundles the 8.0 ShadingData (for BSDF eval) with the few derived
    values (world position, shading normal, emission) the pass shaders read directly, so the original
    `shadingInfo.posW/.N/.emissive` accesses keep working. */
struct SurfaceShadingData
{
    ShadingData sd;
    float3 posW;
    float3 N;
    float3 emissive;
};

uint getSurfaceMaterialInstanceHints()
{
    return 0u;
}

// Alpha test for a non-opaque candidate, as the 4.x fork did in both queries below: a masked material's
// cut-out texels (foliage, fences) let the ray through. The port had dropped it (committing every
// non-opaque candidate), so alpha-cut geometry occluded as solid cards in every shadow and visibility ray,
// and the estimator's own primary hits disagreed with the G-buffer, which does alpha-test. The same test as
// Falcor's RaytracingInline.slang. Costs ~3% of the bistro full-scene estimator (+2 ms at 1080p); volume-only
// frames trace no surfaces.
//
// VR_PRE_FORK_PARITY=1 compiles this out again, and the light-sample offset in VolumeUtils.slang with it:
// the code the locked rb_v9p captures were made with, for byte-identity checks against them
// (VR_SLANG_ARGS="-DVR_PRE_FORK_PARITY=1"; mask_check.sh sets it).
#ifndef VR_PRE_FORK_PARITY
#define VR_PRE_FORK_PARITY 0
#endif
bool isCandidateAlphaDiscarded<let Flags : int>(RayQuery<Flags> q)
{
    const TriangleHit hit = getCandidateTriangleHit(q);
    const VertexData v = gScene.getVertexData(hit);
    return gScene.materials.alphaTest(v, gScene.getMaterialID(hit.instanceID), 0.f);
}

// Find the closest surface hit along a ray.
SurfaceHitInfo FindSurfaceHit(float3 rayOrigin, float3 rayDir, float RayTMin, float RayTMax)
{
    RayDesc ray;
    ray.Origin = rayOrigin;
    ray.Direction = rayDir;
    ray.TMin = max(0, RayTMin);
    ray.TMax = RayTMax;

    RayQuery<RAY_FLAG_NONE> q;
    q.TraceRayInline(gScene.rtAccel, RAY_FLAG_NONE, 0xff, ray);

    while (q.Proceed())
    {
        if (q.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE && (VR_PRE_FORK_PARITY || !isCandidateAlphaDiscarded(q)))
            q.CommitNonOpaqueTriangleHit();
    }

    SurfaceHitInfo h = SurfaceHitInfo.createInvalidHitInfo();
    if (q.CommittedStatus() == COMMITTED_TRIANGLE_HIT)
    {
        h.meshInstanceID = q.CommittedInstanceID() + q.CommittedGeometryIndex();
        h.primitiveIndex = q.CommittedPrimitiveIndex();
        h.barycentrics = q.CommittedTriangleBarycentrics();
        h.rayT = q.CommittedRayT();
    }
    return h;
}

// Return true if anything occludes the ray segment.
bool FindIfOccluded(float3 rayOrigin, float3 rayDir, float RayTMin, float RayTMax, bool cullNonOpaqueGeometry = false)
{
    RayDesc ray;
    ray.Origin = rayOrigin;
    ray.Direction = rayDir;
    ray.TMin = max(0, RayTMin);
    ray.TMax = RayTMax;

    uint rayFlags = RAY_FLAG_SKIP_CLOSEST_HIT_SHADER | RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH;
    if (cullNonOpaqueGeometry) rayFlags |= RAY_FLAG_CULL_NON_OPAQUE;

    RayQuery<RAY_FLAG_SKIP_CLOSEST_HIT_SHADER | RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH> q;
    q.TraceRayInline(gScene.rtAccel, rayFlags, 0xff, ray);

    while (q.Proceed())
    {
        if (q.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE && (VR_PRE_FORK_PARITY || !isCandidateAlphaDiscarded(q)))
            q.CommitNonOpaqueTriangleHit();
    }

    return q.CommittedStatus() == COMMITTED_TRIANGLE_HIT;
}

// Build 8.0 ShadingData + emission for a surface hit.
SurfaceShadingData computeSurfaceShadingInfo(SurfaceHitInfo hitInfo, float3 viewDir)
{
    SurfaceShadingData r;
    r.sd = {};
    r.posW = float3(0.f);
    r.N = float3(0.f);
    r.emissive = float3(0.f);
    if (!hitInfo.isValidHit()) return r;

    const TriangleHit triangleHit = hitInfo.getTriangleHit();
    const VertexData v = gScene.getVertexData(triangleHit);
    const uint materialID = gScene.getMaterialID(triangleHit.instanceID);
    ShadingData sd = gScene.materials.prepareShadingData(v, materialID, viewDir);
    sd.V = viewDir;
    // Offset the shading point off the surface along the face normal. The 4.x fork did this here
    // (computeSurfaceShadingInfo) and the port dropped it, leaving computeScatterRayOrigin defined
    // but never called -- dead code is what gave it away.
    //
    // It is NOT cosmetic. Every shadow ray in this pass is built as { shadingInfo.posW, dir, 0, d },
    // i.e. tMin = 0, so without the offset the ray starts exactly ON the surface it must leave and
    // self-intersects at t ~ 0. Visibility comes back 0 and the pixel is left black. Measured on the
    // bistro orbit: surface pixels with NO contribution 34.38% (4.x) vs 55.90% (unfixed 8.0), while
    // the plume is unaffected (32.79% vs 30.67%) because a medium scatter point has no surface to
    // self-intersect. That sparsity is what the denoiser then has to reconstruct from, which is why
    // the gap showed up as blur + temporal instability on SURFACES rather than in the smoke.
    sd.posW = computeScatterRayOrigin(sd.posW, sd.frontFacing ? sd.faceN : -sd.faceN);

    r.sd = sd;
    r.posW = sd.posW;
    r.N = sd.frame.N;
    // Emission read directly rather than through getMaterialInstance(...).getProperties(sd).emission.
    // Same value: of Falcor 9's materials only StandardMaterial emits, and its instance computes
    // exactly this -- the emissive texture at sd.uv with the default sampler and LOD 0, times
    // emissiveFactor, on the front face only. What it saves is building a whole material instance
    // (every texture of the material sampled) just to read one field, whose live state raised
    // register pressure in every pass that shades a surface hit.
    r.emissive = (sd.frontFacing && sd.mtl.getMaterialType() == MaterialType::Standard)
        ? gScene.materials.evalEmissive(materialID, sd.uv) : float3(0.f);
    return r;
}

bool isEmissive(SurfaceShadingData ssd)
{
    return any(ssd.emissive > 0.f);
}

// Evaluate BSDF * cos(theta) for a light direction L (8.0 IMaterialInstance.eval already folds in the cosine).
float3 evalBSDFCosine(SurfaceShadingData ssd, float3 L, inout SampleGenerator sg)
{
    let lod = ExplicitLodTextureSampler(0.f);
    let mi = gScene.materials.getMaterialInstance(ssd.sd, lod, getSurfaceMaterialInstanceHints());
    return mi.eval(ssd.sd, L, sg);
}

// Importance-sample the surface BSDF. Fills BSDFSample.wo (sampled direction), .pdf, .weight.
bool sampleBSDF(SurfaceShadingData ssd, inout SampleGenerator sg, out BSDFSample result)
{
    let lod = ExplicitLodTextureSampler(0.f);
    let mi = gScene.materials.getMaterialInstance(ssd.sd, lod, getSurfaceMaterialInstanceHints());
    return mi.sample(ssd.sd, sg, result, true);
}
