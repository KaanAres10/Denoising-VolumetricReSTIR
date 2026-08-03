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

    // --- volumetric demodulation ---
    // NRD's input slots are fixed (viewZ, normal+roughness, motion, radiance+hitDist, confidence), so
    // there is nowhere to hand it a volumetric feature. Dividing the medium's own structure out of the
    // radiance before the filter, and letting ModulateIllumination put it back after, is the only way
    // to keep that structure out of the filter's reach.
    //
    // The divisor is a BLURRED density and the blur is not incidental. Measured on the plume as
    // scale-free gradient energy of the CONVERGED image inside the smoke (lower = flatter):
    //   raw scatterDensity  +117%  <- WORSE; per-pixel density is the value at a stochastically
    //                                 chosen scatter point, so its high frequencies are sampling
    //                                 noise and dividing by noise injects noise
    //   blur 5   -48%   blur 11  -56% (best)   blur 21  -49%   blur 81  -14%
    // A self-normalising local-contrast divisor (blur_small/blur_large) was also tried: -22% at best.
    // --- selection-rate normalisation (for the stochastic radiance split) ---
    // ReSTIR keeps ONE reservoir per pixel, so when the radiance is split into volume and surface
    // halves a pixel's entire contribution lands in one of them and the other is exactly zero. Those
    // zeros are structural, not physical, and NRD cannot tell the difference -- it averages them as
    // real black. Measured on the plume, by coverage band:
    //
    //     band            % frame   surface holes
    //     no medium        83.65%       0.0%
    //     thin             0.83%       57.5%
    //     partial          1.95%       92.2%   <- surface estimate comes out 0.078x too dark here
    //     dense           13.57%       98.9%
    //
    // and which pixels are zero is re-randomised every frame, which is the flicker.
    //
    // The fix is NOT more filtering. Both of NRD's spatial tools (diffusePrepassBlurRadius,
    // historyFixFrameNum) work by spreading information over ~30 pixels, so turning them up spreads
    // the structural zeros too and makes the darkening WORSE -- measured, by trying it.
    //
    // Instead divide by the local rate at which this half actually won the reservoir. gColor.a is
    // already the indicator: FinalShading writes the full alpha to whichever bucket fired and zero to
    // the other. E[color] = rate * trueColor, so color / rate is unbiased, and the two corrected
    // halves still sum to the original in expectation.
    //
    // This is a CORRECTION, not a demodulation: nothing multiplies it back downstream. The floor
    // matters -- deep inside the medium the surface rate falls to ~0.011, and dividing by that turns
    // residual noise into fireflies. Flooring leaves a little darkening exactly where the true
    // surface contribution is tiny anyway.
    bool  gNormalizeBySelection;
    int   gSelectionBlur;    // box half-width in pixels
    float gSelectionFloor;   // smallest rate we are willing to divide by

    bool  gDemodulateVolume;
    // False when nothing consumes gOutDemodDivisor. An unconnected output is not allocated, and
    // writing to the resulting null UAV is an access violation -- the failure the SH outputs hit.
    bool  gWriteDemodDivisor;
    int   gVolumeStructureBlur;   // box half-width in pixels
    float gVolumeStructureFloor;  // divisor floor, same role as gMinReflectance
}

// Inputs.
Texture2D<float4> gColor;            // final radiance from VolumetricReSTIR (material included)
Texture2D<float> gScatterDistance;   // expected scatter distance along the ray, -1 = no medium
Texture2D<float4> gGuideNormalW;     // world-space guide normal (GBufferRaster)
Texture2D<float4> gSpecRough;        // .a = perceptual roughness (GBufferRaster)
Texture2D<float4> gDiffuseAlbedo;    // demodulation divisor (DLSSDGuides, medium-blended)
Texture2D<float> gScatterDensity;    // medium density at the scatter point; 0 where no medium
Texture2D<float> gMediumAlpha;       // medium coverage (1 - transmittance), the blend weight

// Outputs.
// NOTE: NRDPass binds diffuseRadianceHitDist as a UAV and rewrites it in place, so nothing
// downstream may read this texture expecting the pre-denoise values.
RWTexture2D<float4> gOutNormalRoughness;
/// EXACTLY what the radiance was divided by, so ModulateIllumination can multiply back the same
/// value rather than two sites agreeing on a formula by hand.
RWTexture2D<float4> gOutDemodDivisor;

#if SH_MODE
// NRD v4 spherical-harmonics mode. SH1 carries the DIRECTION incoming radiance arrives from, scaled
// by luminance -- not a surface normal, so gGuideNormalW is not a substitute for gLightDir.
Texture2D<float4> gLightDir;        // .xyz = world direction, .w = 1 when trustworthy
RWTexture2D<float4> gOutDiffuseSh0; // {radiance.rgb, hitDist}
RWTexture2D<float4> gOutDiffuseSh1; // {direction * luminance(radiance), 0}
#else
RWTexture2D<float4> gOutDiffuseRadianceHitDist;
#endif

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

    // Blended in by coverage, so a pixel the medium does not cover keeps exactly the old
    // albedo-only divisor and the surface path cannot regress.
    float structure = 1.f;
    if (gDemodulateVolume)
    {
        const int r = gVolumeStructureBlur;
        float sum = 0.f;
        float wsum = 0.f;
        for (int dy = -r; dy <= r; dy++)
        {
            for (int dx = -r; dx <= r; dx++)
            {
                const int2 q = clamp(int2(pixel) + int2(dx, dy), int2(0), int2(gResolution) - 1);
                // Coverage-weighted: an unweighted average would drag the divisor toward zero at the
                // plume's silhouette, exactly where a small divisor turns a dim pixel into a firefly.
                const float w = gMediumAlpha[q];
                sum += gScatterDensity[q] * w;
                wsum += w;
            }
        }
        const float blurred = wsum > 0.f ? sum / wsum : 0.f;
        structure = lerp(1.f, max(blurred, gVolumeStructureFloor), saturate(gMediumAlpha[pixel]));
    }

    // Local rate at which this half won the reservoir. A plain box mean of the indicator: unlike the
    // volumetric structure blur above this must NOT be coverage-weighted, because the quantity being
    // estimated IS the coverage-like selection probability itself.
    float selection = 1.f;
    if (gNormalizeBySelection)
    {
        const int rs = gSelectionBlur;
        float hits = 0.f;
        float total = 0.f;
        for (int sy = -rs; sy <= rs; sy++)
        {
            for (int sx = -rs; sx <= rs; sx++)
            {
                const int2 q = clamp(int2(pixel) + int2(sx, sy), int2(0), int2(gResolution) - 1);
                hits += gColor[q].a > 0.f ? 1.f : 0.f;
                total += 1.f;
            }
        }
        selection = max(hits / max(total, 1.f), gSelectionFloor);
    }

    const float3 divisor = albedo * structure * selection;
    const float3 demodulated = radiance / divisor;
    if (gWriteDemodDivisor) gOutDemodDivisor[pixel] = float4(divisor, 1.f);

    // --- hit distance ---
    // -1 means the ray passed through empty space. Feed a finite stand-in rather than the sentinel:
    // a negative hit distance is not a value NRD defines, and it would be clamped to 0 by the
    // front-end sanitise, which reads as "hit immediately" -- the opposite of what happened.
    // gUseScatterDistance=false substitutes the constant everywhere, which ablates the hit-distance
    // guide entirely: if the output is unchanged, the guide is not influencing the denoiser.
    const float scatterT = gScatterDistance[pixel];
    const float hitDist = (gUseScatterDistance && scatterT >= 0.f) ? scatterT : gMissHitDistance;

#if SH_MODE
    // Mirrors RELAX_FrontEnd_PackSh (external/nrd-4/Shaders/NRD.hlsli). Kept in step with it by hand
    // for the same reason encodeNormalRoughness is: pulling NRD.hlsli into this pass would drag in
    // its include path and the whole NRD_INTERNAL / encoding-macro setup for two lines of packing.
    //
    // NOTE the asymmetry: RELAX packs SH0 as plain RGB here, but its BACK end unpacks SH0 as YCoCg
    // (c0 + chroma) -- RELAX converts internally. The resolve must therefore go through
    // RELAX_BackEnd_UnpackSh and must NOT assume NRD's output is in this same space.
    const float3 lightDir = gLightDir[pixel].xyz;
    const bool dirValid = gLightDir[pixel].w > 0.5f;

    // Zero direction where the estimator could not supply one, rather than a guessed one: an SH1 of
    // zero means "no directional information for this pixel", which is exactly what is true.
    const float3 dir = dirValid ? lightDir : float3(0.f);
    const float lum = dot(demodulated, float3(0.2126f, 0.7152f, 0.0722f));

    gOutDiffuseSh0[pixel] = float4(demodulated, hitDist);
    gOutDiffuseSh1[pixel] = float4(dir * lum, 0.f);
#else
    gOutDiffuseRadianceHitDist[pixel] = float4(demodulated, hitDist);
#endif

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
