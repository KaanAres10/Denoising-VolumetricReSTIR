/***************************************************************************
 # Converts this renderer's volumetric output into the guide buffers NRD's RELAX denoiser expects.
 #
 # NRD is built for surface path tracing. Three mismatches make this pass necessary:
 #
 #   1. NRD wants radiance with the material response DIVIDED OUT ("radiance should not include any
 #      BRDFs"), denoised, then multiplied back afterwards. VolumetricReSTIR emits final radiance
 #      with the material already in it, so we demodulate here and let ModulateIllumination
 #      re-modulate after the denoiser.
 #   2. NRD wants normal + roughness packed octahedrally into RGB10A2. Only GBufferRT produces that
 #      channel, and this renderer's DLSS graphs use GBufferRaster -- so we pack it ourselves, using
 #      Falcor's ndir_to_oct_unorm, which is bit-compatible with NRD's _NRD_EncodeUnitVector.
 #   3. NRD wants a hit distance to size its filter kernel. A participating medium has no surface
 #      hit, so we supply the expected scattering distance instead.
 #
 # Deliberately does NOT call RELAX_FrontEnd_PackRadianceAndHitDist: NRDPass runs its own packing
 # internally (PackRadiance.cs.slang), and for RELAX that function is a pure NaN/Inf sanitise anyway.
 # Packing here would apply it twice.
 **************************************************************************/
import Utils.Math.MathHelpers;

cbuffer CB
{
    uint2 gResolution;
    // Floor on the demodulation divisor. Mirrors kNRDMinReflectance: dividing by a near-black albedo
    // turns a dark pixel into a firefly that the denoiser then smears across its filter footprint.
    float gMinReflectance;
    // Substituted where the primary ray never met the medium (scatterDistance < 0). NRD treats
    // anything past its denoisingRange (10000 units) as background, so this stays well inside it.
    float gMissHitDistance;
    // Ablation switch for the hit-distance guide; see the use site.
    bool gUseScatterDistance;
    // Ablation switch for the normal guide: false feeds the miss sentinel everywhere,
    // i.e. a constant orientation carrying no geometric information.
    bool gUseNormalGuide;
}

// Inputs.
Texture2D<float4> gColor;            // final radiance from VolumetricReSTIR (material included)
Texture2D<float> gScatterDistance;   // expected scatter distance along the ray, -1 = no medium
Texture2D<float4> gGuideNormalW;     // world-space guide normal (GBufferRaster)
Texture2D<float4> gSpecRough;        // .a = perceptual roughness (GBufferRaster)
Texture2D<float4> gDiffuseAlbedo;    // demodulation divisor (DLSSDGuides, medium-blended)

// Outputs.
// NOTE: NRDPass binds diffuseRadianceHitDist as a UAV and rewrites it in place, so nothing
// downstream may read this texture expecting the pre-denoise values.
RWTexture2D<float4> gOutDiffuseRadianceHitDist;
RWTexture2D<float4> gOutNormalRoughness;

/** Packs the normal+roughness guide in the layout the linked NRD expects.

    The two SDKs disagree completely on what RGB10A2 means, and neither validates it -- a mismatch
    just makes every edge-stopping weight garbage, so the denoiser blurs across depth and normal
    discontinuities and the image comes out uniformly smeared. That is what it looked like before
    this branch existed.

    v3.1 (NRD_USE_OCT_NORMAL_ENCODING=1, NRD_USE_MATERIAL_ID=0):
        .xy = unsigned octahedral normal, .z = linear roughness, .w unused.

    v4 (NRD_NORMAL_ENCODING=2 = R10G10B10A2_UNORM, NRD_ROUGHNESS_ENCODING=1 = LINEAR):
        an L1-normalized "diamond" pair in .xy, roughness in .z with n.z's SIGN folded into the
        sign of the roughness, and materialID/3 in .w. Mirrors _NRD_EncodeNormalRoughness101010
        in external/nrd-4/Shaders/NRD.hlsli -- keep the two in sync.
*/
float4 encodeNormalRoughness(float3 n, float roughness)
{
#if NRD_V4
    n /= abs(n.x) + abs(n.y) + abs(n.z);

    float3 r;
    r.y = n.y * 0.5f + 0.5f;
    r.x = n.x * 0.5f + r.y;
    r.y -= n.x * 0.5f;

    // Roughness must stay non-zero or it cannot carry n.z's sign bit.
    roughness = max(roughness, 1.5f / 512.f);
    const float s = n.z < 0.f ? -roughness : roughness;
    r.z = s * 0.5f + 0.5f;

    // materialID = 0; NRD compares max(m, minMaterial) and minMaterialFor* default to 4, so a
    // constant 0 disables material-based rejection rather than misclassifying anything.
    return float4(r, 0.f);
#else
    return float4(ndir_to_oct_unorm(n), roughness, 0.f);
#endif
}

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId: SV_DispatchThreadID)
{
    const uint2 pixel = dispatchThreadId.xy;
    if (any(pixel >= gResolution))
        return;

    // --- radiance: demodulate ---
    const float3 radiance = gColor[pixel].rgb;
    const float3 albedo = max(gDiffuseAlbedo[pixel].rgb, gMinReflectance);
    const float3 demodulated = radiance / albedo;

    // --- hit distance ---
    // -1 means the ray passed through empty space. Feed a finite stand-in rather than the sentinel:
    // a negative hit distance is not a value NRD defines, and it would be clamped to 0 by the
    // front-end sanitise, which reads as "hit immediately" -- the opposite of what happened.
    // gUseScatterDistance=false substitutes the constant everywhere, which ablates the hit-distance
    // guide entirely: if the output is unchanged, the guide is not influencing the denoiser.
    const float scatterT = gScatterDistance[pixel];
    const float hitDist = (gUseScatterDistance && scatterT >= 0.f) ? scatterT : gMissHitDistance;

    gOutDiffuseRadianceHitDist[pixel] = float4(demodulated, hitDist);

    // --- normal + roughness ---
    // Layout must match the SDK NRDPass is compiled against; see encodeNormalRoughness above.
    float3 normalW = gGuideNormalW[pixel].rgb;
    const float lenSq = dot(normalW, normalW);
    // A zero normal encodes to a degenerate direction and NRD's reprojection rejects the pixel
    // outright. GBufferRaster leaves the background normal at zero, so substitute the same constant
    // GBufferRT writes on a miss.
    normalW = (gUseNormalGuide && lenSq > 1e-8f) ? normalW * rsqrt(lenSq)
                                                 : float3(0.2215f, 0.2215f, 0.2215f);

    const float roughness = gSpecRough[pixel].a;
    gOutNormalRoughness[pixel] = encodeNormalRoughness(normalW, roughness);
}
