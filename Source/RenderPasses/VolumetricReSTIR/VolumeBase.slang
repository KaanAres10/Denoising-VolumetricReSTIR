__exported import Scene.Scene;
#include "Utils/Math/MathConstants.slangh"
__exported import HostDeviceSharedConstants;

__exported import Scene.GVDB.gvdb;
__exported import Scene.GVDB.gvdbDda;
__exported import Utils.Sampling.SampleGenerator;

static const bool cbVDBUseTrilinear = true;

static const float kRayTMax = FLT_MAX;

Texture1D<float4> gBlackBodyRadiationTex;

// 0 - 7 normal mips
// 8 - 15 conservative mips

SamplerState gLinearSampler;
SamplerState gPointSampler;

ParameterBlock<VDBInfo> gvdb;

struct VolRay
{
    float3 origin;
    float3 dir;
    float tMin;
    float tMax;

    float3 at(float t)
    {
        return origin + dir * t;
    }
};

// [8.0 port] The fork added computeRayPinholeScaled / computeNonNormalizedRayDirPinholeScaled and a
// CameraRay struct to core Camera.slang. To avoid modifying 8.0's core Camera, they are replicated
// here as free functions taking the Camera by value (Camera exposes its CameraData as `data`).
struct CameraRay { float3 origin; float3 dir; float tMin; float tMax; };

float3 computeNonNormalizedRayDirPinholeOffset(Camera cam, uint2 pixel, float2 offsets, uint2 frameDim)
{
    float2 p = (float2(pixel) + offsets) / frameDim + float2(-cam.data.jitterX, cam.data.jitterY);
    float2 ndc = float2(2, -2) * p + float2(-1, 1);
    return ndc.x * cam.data.cameraU + ndc.y * cam.data.cameraV + cam.data.cameraW;
}

CameraRay computeRayPinholeScaled(Camera cam, uint2 pixel, int scale, float2 offset, uint2 frameDim)
{
    float2 pixelPos = (float2(pixel) + offset) * scale;
    CameraRay ray;
    ray.origin = cam.data.posW;
    ray.dir = normalize(computeNonNormalizedRayDirPinholeOffset(cam, int2(pixelPos), pixelPos - int2(pixelPos), frameDim));
    float invCos = 1.f / dot(normalize(cam.data.cameraW), ray.dir);
    ray.tMin = cam.data.nearZ * invCos;
    ray.tMax = cam.data.farZ * invCos;
    return ray;
}

float3 computeNonNormalizedRayDirPinholeScaled(Camera cam, uint2 pixel, int scale, float2 offset, uint2 frameDim)
{
    float2 pixelPos = (float2(pixel) + offset) * scale;
    return computeNonNormalizedRayDirPinholeOffset(cam, int2(pixelPos), pixelPos - int2(pixelPos), frameDim);
}

// Prev-frame (explicit ray-tracing frame) variants used by temporal reprojection.
// Previous-frame ray reconstruction. `jitter` MUST be the jitter the previous frame was rendered
// with: the reservoirs being re-evaluated were generated on that jittered ray, so evaluating p-hat
// on an unjittered one makes p-hat wrong for that domain. Talbot weights renormalise, so the usual
// cost is variance -- but where the wrong ray flips a hit to a miss (silhouettes) p-hat becomes
// exactly zero, the weights stop summing to one, and the result is genuinely biased.
// Passing jitter = 0 reproduces the previous behaviour exactly.
float3 computeNonNormalizedRayDirPinholeWithFrame(uint2 pixel, float2 offsets, uint2 frameDim, float3 cameraU, float3 cameraV, float3 cameraW, float2 jitter = float2(0, 0))
{
    float2 p = (float2(pixel) + offsets) / frameDim + float2(-jitter.x, jitter.y);
    float2 ndc = float2(2, -2) * p + float2(-1, 1);
    return ndc.x * cameraU + ndc.y * cameraV + cameraW;
}

CameraRay computeRayPinholeWithRayTracingFrameScaled(Camera cam, uint2 pixel, int scale, float2 offset, uint2 frameDim, float3 posW, float3 cameraU, float3 cameraV, float3 cameraW, float2 jitter = float2(0, 0))
{
    float2 pixelPos = (float2(pixel) + offset) * scale;
    CameraRay ray;
    ray.origin = posW;
    ray.dir = normalize(computeNonNormalizedRayDirPinholeWithFrame(uint2(pixelPos), pixelPos - int2(pixelPos), frameDim, cameraU, cameraV, cameraW, jitter));
    float invCos = 1.f / dot(normalize(cameraW), ray.dir);
    ray.tMin = cam.data.nearZ * invCos;
    ray.tMax = cam.data.farZ * invCos;
    return ray;
}

float3 computeWorldPositionWithRayTracingFrameScaled(Camera cam, uint2 pixel, int scale, float2 offset, uint2 frameDim, float3 posW, float3 cameraU, float3 cameraV, float3 cameraW, float depth, float2 jitter = float2(0, 0))
{
    float2 pixelPos = (float2(pixel) + offset) * scale;
    float3 origin = posW;
    float3 dir = normalize(computeNonNormalizedRayDirPinholeWithFrame(uint2(pixelPos), pixelPos - int2(pixelPos), frameDim, cameraU, cameraV, cameraW, jitter));
    return origin + depth * dir;
}

struct SceneLightSample
{
    // Light sample
    float3  dir;            ///< Direction from the shading point to the light sample in world space (normalized). This is used for BRDF evaluation.
    float   distance;       ///< Distance from the shading point to the light sample.
    float3  Li;             ///< Incident radiance at the shading point (unshadowed). Note: Already divided by the pdf and multiplied by MIS weight.
    float   pdf;            ///< Probability density function with respect to solid angle (pdf == 0 for invalid samples).
    float   pdfArea;
    // Shadow ray parameters
    float3  rayDir;         ///< VolRay direction for visibility evaluation (normalized). This may differ from 'dir' due to ray offsets.
    float   rayDistance;    ///< VolRay distance for visibility evaluation. This may differ from 'distance' due to ray offsets.
};


inline void CoordinateSystem(float3 v1, inout float3 v2, inout float3 v3) {
    if (abs(v1.x) > abs(v1.y))
        v2 = float3(-v1.z, 0, v1.x) / sqrt(v1.x * v1.x + v1.z * v1.z);
    else
        v2 = float3(0, v1.z, -v1.y) / sqrt(v1.y * v1.y + v1.z * v1.z);
    v3 = cross(v1, v2);
}

inline float3 SphericalDirection(float sinTheta, float cosTheta, float phi,
    float3 x, float3 y, float3 z) {
    return sinTheta * cos(phi) * x + sinTheta * sin(phi) * y + cosTheta * z;
}


float PhaseHG(float cosTheta, float g) {
    float denom = 1 + g * g + 2 * g * cosTheta;
    const float Inv4Pi = 0.07957747154594766788444188168626;
    return Inv4Pi * (1 - g * g) / (denom * sqrt(denom));
}

struct MediumInteraction
{
    float3 p;
    float3 wo;
    float g;
    bool isValid;

    float phaseFunction(float3 wo, float3 wi) {
        return PhaseHG(dot(wo, wi), g);
    }

    float Sample_p(float3 wo, inout float3 wi, float2 u) {
        float cosTheta;
        if (abs(g) < 1e-3)
            cosTheta = 1 - 2 * u[0];
        else {
            float sqrTerm = (1 - g * g) / (1 + g - 2 * g * u[0]);
            cosTheta = -(1 + g * g - sqrTerm * sqrTerm) / (2 * g);
        }

        float sinTheta = sqrt(max(0, 1 - cosTheta * cosTheta));
        float phi = 2 * M_PI * u[1];
        float3 v1, v2;
        CoordinateSystem(wo, v1, v2);
        wi = SphericalDirection(sinTheta, cosTheta, phi, v1, v2, wo);
        return PhaseHG(cosTheta, g);
    }

    VolRay SpawnRay(float3 d) {
        return { p, d, 0, kRayTMax };
    }
}

VolRay WorldToMedium(VolRay r, int mipLevel)
{
    float4x4 WorldToMediumMatrix = mul(gScene.volumeExternalWorldToModelMatrix, gvdb.invxform[mipLevel]);
    float4 o = mul(float4(r.origin, 1), WorldToMediumMatrix);
    float3 d = mul(float4(r.dir, 0), WorldToMediumMatrix).xyz;
    return { o.xyz / o.w, d.xyz, r.tMin, r.tMax }; 
}

float3 WorldToMedium(float3 p, int mipLevel)
{
    float4x4 WorldToMediumMatrix = mul(gScene.volumeExternalWorldToModelMatrix, gvdb.invxform[mipLevel]);
    float4 o = mul(float4(p, 1), WorldToMediumMatrix);
    return o.xyz / o.w;
}


float3 MediumToWorldVec(float3 v, int mipLevel)
{
    float4x4 MediumToWorldMatrix = mul(gvdb.xform[mipLevel], gScene.volumeExternalModelToWorldMatrix);
    return mul(float4(v, 0), MediumToWorldMatrix).xyz;
}

float3 MediumToWorld(float3 p, int mipLevel)
{
    float4x4 MediumToWorldMatrix = mul(gvdb.xform[mipLevel], gScene.volumeExternalModelToWorldMatrix);
    float4 p_ = mul(float4(p, 1), MediumToWorldMatrix);
    return p_.xyz / p_.w;
}

struct Bounds3f
{
    float3 pMin;
    float3 pMax;

    bool IntersectP(VolRay ray, inout float hitt0, inout float hitt1) {
        float t0 = 0, t1 = ray.tMax;
        for (int i = 0; i < 3; ++i) {
            float invRayDir = 1 / ray.dir[i];
            float tNear = (pMin[i] - ray.origin[i]) * invRayDir;
            float tFar = (pMax[i] - ray.origin[i]) * invRayDir;

            if (tNear > tFar)
            {
                float temp = tNear;
                tNear = tFar;
                tFar = temp;
            }

            t0 = tNear > t0 ? tNear : t0;
            t1 = tFar < t1 ? tFar : t1;
            if (t0 > t1) return false;
        }
        hitt0 = t0;
        hitt1 = t1;
        return true;
    }
}


bool IntersectVolumeBound(VolRay ray, inout float tMin, inout float tMax, int mipLevel, bool vertexCenter = false)
{
    Bounds3f b;

    b.pMin = gvdb.bmin[mipLevel];
    b.pMax = gvdb.bmax[mipLevel];
    if (vertexCenter)
    {
        b.pMin -= float3(0.5);
        b.pMax -= float3(0.5);
    }

    return b.IntersectP(ray, tMin, tMax);
}

float GetVolumeMaxDensity(int mipLevel)
{
    return gvdb.maxValue[mipLevel] * (gScene.volumeDesc.densityScaleFactorByScaling);
}

// velocity is specified in world space
float3 Velocity(float3 p, bool isLastFrame = false)
{
    return mul(float4(getVelocityAtPoint(gvdb, p, 0, gLinearSampler, isLastFrame), 0), gScene.volumeExternalModelToWorldMatrix).xyz;
}

float3 VelocityWorld(float3 pW, bool isLastFrame = false)
{
    int velocityGridOffset = isLastFrame ? kPrevFrameExtraGridOffset : 0;
    float3 p_Medium = WorldToMedium(pW, kVelocityGridId + velocityGridOffset);
    float3 indexSpaceVelocity = Velocity(p_Medium, isLastFrame);
    return indexSpaceVelocity;
}

float Temperature(float3 p, bool isLastFrame = false)
{
    int temperatureGridOffset = isLastFrame ? kPrevFrameExtraGridOffset : 0;
    if (cbVDBUseTrilinear)
        return getValueAtPoint(gvdb, kTemperatureGridId + temperatureGridOffset, p, 0, gLinearSampler);
    else
        return getValueAtPoint(gvdb, kTemperatureGridId + temperatureGridOffset, p, 0, gPointSampler);
}

float TemperatureWorldSpace(float3 pW, bool isLastFrame = false)
{
    float3 p_Medium = WorldToMedium(pW, kTemperatureGridId);
    return Temperature(p_Medium, isLastFrame);
}

// sample RGB black body spectrum from PBRT4
float3 ConvertTempToColor(float temp)
{
    temp = min(6400, (temp - gScene.volumeDesc.temperatureCutOff) * gScene.volumeDesc.temperatureScale);
    float queryPoint = (temp - 25) / 6400;
    return gScene.volumeDesc.LeScale * gBlackBodyRadiationTex.SampleLevel(gLinearSampler, queryPoint, 0).rgb;
}

float3 Emission(float3 p, bool isLastFrame=false)
{
    if (!isLastFrame && !gScene.volumeDesc.hasEmission || isLastFrame && !gScene.volumeDesc.lastFrameHasEmission) return 0.f;
    float temp = Temperature(p, isLastFrame);
    return ConvertTempToColor(temp);
}

float3 EmissionWorldSpace(float3 pW, bool isLastFrame = false)
{
    if (!isLastFrame && !gScene.volumeDesc.hasEmission || isLastFrame && !gScene.volumeDesc.lastFrameHasEmission) return 0.f;
    float3 p_Medium = WorldToMedium(pW, isLastFrame ? kTemperatureGridId + kPrevFrameExtraGridOffset: kTemperatureGridId);
    float temp = Temperature(p_Medium, isLastFrame);
    return ConvertTempToColor(temp);
}

float Density(float3 p, int mipLevel) {
    if (any(p < gvdb.bmin[mipLevel]) || any(p >= gvdb.bmax[mipLevel])) return 0.f;
    return getValueAtPoint(gvdb, mipLevel, p, 0, gLinearSampler) * (gScene.volumeDesc.densityScaleFactorByScaling);
}

float DensityWorldSpace(float3 p, int mipLevel)
{
    float3 p_Medium = WorldToMedium(p, mipLevel);
    return Density(p_Medium, mipLevel);
}

/** Gradient of the density field, returned in WORLD space.

    Central differences are taken in MEDIUM space, where voxels are unit-sized, so `step` is measured in
    voxels and needs no guess about the volume's world scale.

    The transform back is the matrix itself, NOT its inverse-transpose. That is the opposite of the rule
    for surface normals, and the difference is real: a surface normal is a covector defined by the plane
    it is perpendicular to, while this is the gradient of a scalar field. With the row-vector convention
    used here, p_m = p_w A, so f(p_w) = g(p_w A) gives d f / d p_w,i = sum_j A_ij dg/dp_m,j -- i.e.
    grad_w = A grad_m, a column-vector multiply.

    `Density` returns 0 outside the grid bounds, so at the medium's boundary the gradient points inward,
    which is the behaviour wanted from a stand-in normal there.
*/
float3 DensityGradientWorldSpace(float3 pW, int mipLevel, float step = 1.f)
{
    float4x4 WorldToMediumMatrix = mul(gScene.volumeExternalWorldToModelMatrix, gvdb.invxform[mipLevel]);
    float3 p_Medium = mul(float4(pW, 1), WorldToMediumMatrix).xyz;

    float3 g;
    g.x = Density(p_Medium + float3(step, 0, 0), mipLevel) - Density(p_Medium - float3(step, 0, 0), mipLevel);
    g.y = Density(p_Medium + float3(0, step, 0), mipLevel) - Density(p_Medium - float3(0, step, 0), mipLevel);
    g.z = Density(p_Medium + float3(0, 0, step), mipLevel) - Density(p_Medium - float3(0, 0, step), mipLevel);

    return mul(WorldToMediumMatrix, float4(g, 0)).xyz * (0.5f / max(step, 1e-6f));
}

void FetchEightVoxelsInAtlas(float3 p_atlas, int mipLevel, inout float4 densities[2]) {
    float3 anchor = floor(p_atlas - 0.5) + 0.5f;
    [unroll]
    for (int i = 0; i < 8; i++)
    {
        densities[i/4][i%4] = getValueAtlasCoord(gvdb, anchor + float3(i % 2, (i % 4) / 2, i / 4), mipLevel, gPointSampler) * gvdb.densityCompressScaleFactor[mipLevel] * (gScene.volumeDesc.densityScaleFactorByScaling);
    }
}

float DensityInAtlas(float3 p_atlas, int mipLevel, bool useLinearSampler) {
    if (useLinearSampler)
    {
        return getValueAtlasCoord(gvdb, p_atlas, mipLevel, gLinearSampler) * gvdb.densityCompressScaleFactor[mipLevel] * (gScene.volumeDesc.densityScaleFactorByScaling);
    }
    else
    {
        return getValueAtlasCoord(gvdb, p_atlas, mipLevel, gPointSampler) * gvdb.densityCompressScaleFactor[mipLevel] * (gScene.volumeDesc.densityScaleFactorByScaling);
    }
}

/** The per-mip atlas constants DensityInAtlas reads, loaded once per brick instead of once per step.
    `mipLevel` is a runtime index, so every one of these is a dynamically indexed constant-buffer load
    (plus an int->float conversion) that DXC leaves inside the march loop. Same values and the same
    operation order as DensityInAtlas, so the result is bit-identical.

    Per program: VR_HOIST_ATLAS=1 holds them in registers across the march; 0 (the default) keeps the
    per-step loads, reproducing the old code. The host turns it on for every estimator pass except
    Spatial Reuse on surface scenes, where the smaller kernel lands on the pass's register cliff
    (full scene 55.9 -> 62.3 ms; see VolumetricReSTIR.cpp).
*/
#ifndef VR_HOIST_ATLAS
#define VR_HOIST_ATLAS 0
#endif

struct AtlasMip
{
#if VR_HOIST_ATLAS
    int res;            ///< gvdb.res[mipLevel * 3]: brick resolution in voxels (bound of the per-brick march).
    float dimZ;         ///< gvdb.volInDimensions[mipLevel].z: depth of the first atlas texture.
    float3 invDim;      ///< gvdb.invVolInDimensions[mipLevel].
    float3 invDim2;     ///< gvdb.invVolInDimensions_part2[mipLevel].
    float compress;     ///< gvdb.densityCompressScaleFactor[mipLevel].
    float scaling;      ///< gScene.volumeDesc.densityScaleFactorByScaling.

    int resolution() { return res; }
#else
    int mipLevel;

    int resolution() { return gvdb.res[mipLevel * 3]; }
#endif
};

AtlasMip loadAtlasMip(int mipLevel)
{
    AtlasMip m;
#if VR_HOIST_ATLAS
    m.res = gvdb.res[mipLevel * 3];
    m.dimZ = gvdb.volInDimensions[mipLevel].z;
    m.invDim = gvdb.invVolInDimensions[mipLevel];
    m.invDim2 = gvdb.invVolInDimensions_part2[mipLevel];
    m.compress = gvdb.densityCompressScaleFactor[mipLevel];
    m.scaling = gScene.volumeDesc.densityScaleFactorByScaling;
#else
    m.mipLevel = mipLevel;
#endif
    return m;
}

float DensityInAtlas(float3 p_atlas, int mipLevel, bool useLinearSampler, AtlasMip m)
{
#if !VR_HOIST_ATLAS
    return DensityInAtlas(p_atlas, mipLevel, useLinearSampler);
#else
    float v;
    if (p_atlas.z > m.dimZ)
    {
        p_atlas.z -= m.dimZ;
        if (useLinearSampler) v = gvdb.volIn_part2[mipLevel].SampleLevel(gLinearSampler, p_atlas * m.invDim2, 0);
        else v = gvdb.volIn_part2[mipLevel].SampleLevel(gPointSampler, p_atlas * m.invDim2, 0);
    }
    else
    {
        if (useLinearSampler) v = gvdb.volIn[mipLevel].SampleLevel(gLinearSampler, p_atlas * m.invDim, 0);
        else v = gvdb.volIn[mipLevel].SampleLevel(gPointSampler, p_atlas * m.invDim, 0);
    }
    return v * m.compress * m.scaling;
#endif
}

void FetchEightVoxelsInAtlas(float3 p_atlas, int mipLevel, inout float4 densities[2], AtlasMip m)
{
#if !VR_HOIST_ATLAS
    FetchEightVoxelsInAtlas(p_atlas, mipLevel, densities);
#else
    float3 anchor = floor(p_atlas - 0.5) + 0.5f;
    [unroll]
    for (int i = 0; i < 8; i++)
    {
        densities[i/4][i%4] = DensityInAtlas(anchor + float3(i % 2, (i % 4) / 2, i / 4), mipLevel, false, m);
    }
#endif
}
