/***************************************************************************
 # Converts Falcor G-buffer channels into the four guide buffers DLSS Ray Reconstruction expects.
 #
 # Two mismatches make this necessary rather than wiring GBufferRaster straight into DLSSDPass:
 #
 #   1. GBufferRaster's specRough.rgb is F0 (specular reflectance at normal incidence), but RR wants
 #      a pre-integrated directional-hemispherical specular albedo. Same conversion the PathTracer
 #      applies for NRD (NRDHelpers.slang), via approxSpecularIntegralGGX.
 #   2. RR in Roughness_Mode_Unpacked wants roughness in its own texture; GBufferRaster packs it
 #      into specRough.a.
 #
 # Stage 2 adds volumetric blending here (lerp toward the medium's scattering albedo by its opacity),
 # which is why this is a separate pass -- DLSSDPass then needs no change at all.
 **************************************************************************/
import Utils.Color.ColorHelpers;
import Rendering.Materials.IsotropicGGX;

cbuffer CB
{
    uint2 gResolution;
    // Floor on reflectance, matching kNRDMinReflectance: a zero guide makes the denoiser divide
    // through by nothing and produces fireflies on black materials.
    float gMinReflectance;

    // --- Volumetric blending (Stage 2) ---
    // RR's guides describe a surface. A participating medium has no surface, so where the medium
    // covers the pixel we blend the guides toward what an isotropic scatterer looks like. The
    // blend weight is the medium's own coverage, 1 - transmittance, supplied per pixel.
    bool gBlendMedium;
    // Single-scatter albedo sigma_s/sigma_t. Uniform rather than a texture because only DENSITY
    // varies spatially in this renderer -- sigma_s and sigma_t are per-volume constants
    // (cf. VolumePathTracingFunctions.slang, ComputeInitialSample.slang).
    float3 gMediumScatterAlbedo;

    // --- Per-guide ablation controls ---
    // Which guides the medium blend is applied to. Individually switchable because the four guides
    // are not equally important and their contributions are not separable by looking at the result:
    // turning one off and re-measuring is the only way to attribute the gain.
    bool gBlendDiffuse;
    bool gBlendSpecular;
    bool gBlendRoughness;
    bool gBlendNormal;
    // Scales the medium coverage. 0 reproduces the surface-only path bit-exactly (lerp(x, y, 0) == x),
    // which is the cheap control for "is the volumetric path doing anything at all".
    float gAlphaScale;
    // Blend target for roughness. 1 = fully rough, i.e. isotropic scattering.
    float gMediumRoughness;

    // Replace a guide with a constant, to measure what RR does WITHOUT that guide. Not the same as
    // disconnecting it -- RR requires all four, and an unbound input would fault -- so the neutral
    // value stands in: mid-grey diffuse, zero specular, fully rough, camera-facing normal.
    bool gNeutralDiffuse;
    bool gNeutralSpecular;
    bool gNeutralRoughness;
    bool gNeutralNormal;
};

// Inputs (from GBufferRaster).
Texture2D<float4> gDiffuseOpacity;   // rgb = diffuse reflection albedo
Texture2D<float4> gSpecRough;        // rgb = F0, a = perceptual roughness
Texture2D<float4> gGuideNormalW;     // rgb = world-space guide normal
Texture2D<float4> gViewW;            // rgb = world-space view vector

// Volumetric guides (from VolumetricReSTIR). Optional: only read when gBlendMedium is set.
Texture2D<float> gMediumAlpha;       // 1 - transmittance through the medium
Texture2D<float4> gMediumNormal;     // stand-in medium orientation (world space)

// Outputs (to DLSSDPass).
RWTexture2D<float4> gOutDiffuseAlbedo;
RWTexture2D<float4> gOutSpecularAlbedo;
RWTexture2D<float4> gOutNormals;
RWTexture2D<float> gOutRoughness;

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId: SV_DispatchThreadID)
{
    const uint2 pixel = dispatchThreadId.xy;
    if (any(pixel >= gResolution))
        return;

    const float3 diffuseAlbedo = gDiffuseOpacity[pixel].rgb;
    const float4 specRough = gSpecRough[pixel];
    const float3 f0 = specRough.rgb;
    const float roughness = specRough.a;
    const float3 normalW = gGuideNormalW[pixel].rgb;
    const float3 viewW = gViewW[pixel].rgb;

    // Pre-integrate the specular lobe, exactly as the PathTracer does for NRD.
    const float NdotV = saturate(dot(normalW, viewW));
    const float ggxAlpha = roughness * roughness;
    float3 specularAlbedo = approxSpecularIntegralGGX(f0, ggxAlpha, NdotV);

    float3 outDiffuse = diffuseAlbedo;
    float3 outSpecular = specularAlbedo;
    float3 outNormal = normalW;
    float outRoughness = roughness;

    if (gBlendMedium)
    {
        // alpha = 0 leaves every guide byte-identical to the surface-only path, which is what makes
        // this safe to enable: a scene with no medium in front of a pixel is unaffected.
        const float alpha = saturate(gMediumAlpha[pixel] * gAlphaScale);

        // Diffuse: toward the medium's single-scatter albedo. The highest-value guide -- it tells
        // RR the medium is a flat, untextured, non-metallic scatterer, so it stops trying to
        // preserve surface detail that is not there.
        if (gBlendDiffuse)
            outDiffuse = lerp(diffuseAlbedo, gMediumScatterAlbedo, alpha);
        // Specular: toward zero. A participating medium has no specular lobe.
        if (gBlendSpecular)
            outSpecular = lerp(specularAlbedo, float3(0.f), alpha);
        // Roughness: toward fully rough. Isotropic scattering has no glossy direction, and this is
        // what stops RR sharpening smoke into streaks.
        if (gBlendRoughness)
            outRoughness = lerp(roughness, gMediumRoughness, alpha);
        // Normal: toward the medium's camera-facing stand-in. Normalize after the lerp, since
        // interpolating two unit vectors does not preserve length.
        if (gBlendNormal)
            outNormal = normalize(lerp(normalW, gMediumNormal[pixel].rgb, alpha));
    }

    // Ablation: substitute a neutral constant so RR still receives a well-formed guide while the
    // information it carries is removed.
    if (gNeutralDiffuse)
        outDiffuse = float3(0.5f);
    if (gNeutralSpecular)
        outSpecular = float3(0.f);
    if (gNeutralRoughness)
        outRoughness = 1.f;
    if (gNeutralNormal)
        outNormal = viewW; // camera-facing: no orientation information

    gOutDiffuseAlbedo[pixel] = float4(max(gMinReflectance, outDiffuse), 1.f);
    gOutSpecularAlbedo[pixel] = float4(max(gMinReflectance, outSpecular), 1.f);
    gOutNormals[pixel] = float4(outNormal, 0.f);
    gOutRoughness[pixel] = outRoughness;
}
