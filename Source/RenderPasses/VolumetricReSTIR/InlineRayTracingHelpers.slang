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
        if (q.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE)
        {
            // TODO(surface-scene): alpha test via gScene.materials.
            q.CommitNonOpaqueTriangleHit();
        }
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
        if (q.CandidateType() == CANDIDATE_NON_OPAQUE_TRIANGLE)
        {
            q.CommitNonOpaqueTriangleHit();
        }
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

    let lod = ExplicitLodTextureSampler(0.f);
    let mi = gScene.materials.getMaterialInstance(sd, lod, getSurfaceMaterialInstanceHints());

    r.sd = sd;
    r.posW = sd.posW;
    r.N = sd.frame.N;
    r.emissive = mi.getProperties(sd).emission;
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
