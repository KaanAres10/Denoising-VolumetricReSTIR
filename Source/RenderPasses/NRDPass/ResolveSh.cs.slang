/***************************************************************************
 # Resolves NRD v4's spherical-harmonics output back into radiance.
 #
 # RELAX_DIFFUSE_SH emits a PAIR of coefficient textures, not an image. Without this step the graph
 # carries {c0, chroma, normHitDist} and {c1, sharpness} straight into ModulateIllumination, which
 # would multiply albedo into a set of SH coefficients -- producing something that looks like a
 # picture and is not one.
 #
 # Lives in NRDPass rather than NRDAdapter because it needs NRD.hlsli, and NRDPass is already set up
 # to compile against it (include path, NRD_INTERNAL, and the encoding macros). Hand-rolling the
 # YCoCg conversion elsewhere is exactly the duplication that produced the RGB10A2 guide bug.
 **************************************************************************/
#include "nrd/Shaders/NRD.hlsli"

import Utils.Color.ColorHelpers;

// Resolve semantics. Both exist because NRD's own resolve assumes a SURFACE, and this renderer's
// media do not have one -- see the note on gResolveMode below.
#define SH_RESOLVE_DC 0
#define SH_RESOLVE_COSINE 1

#ifndef SH_RESOLVE_MODE
#error "SH_RESOLVE_MODE not defined!"
#endif

cbuffer PerImageCB
{
    uint2 gResolution;

    // TRUE when SH0 still holds what the front end packed (linear RGB) rather than what NRD emits
    // (YCoCg). RELAX converts internally, so its OUTPUT is YCoCg while its INPUT is RGB -- the two
    // ends of the same API are in different colour spaces. The bypass path (denoiser disabled) feeds
    // the front-end pair straight in, so it must do that conversion itself or it would read R as
    // luma and GB as chroma, which silently produces a wrong-coloured image rather than an error.
    bool gSh0IsLinearRgb;

    Texture2D<float4> gInSh0;            // OUT_DIFF_SH0 from NRD (or IN_DIFF_SH0 when bypassed)
    Texture2D<float4> gInSh1;            // OUT_DIFF_SH1 from NRD
    Texture2D<float4> gNormalRoughness;  // only read by the cosine resolve

    RWTexture2D<float4> gOutRadianceHitDist;
};

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId: SV_DispatchThreadID)
{
    const uint2 pixel = dispatchThreadId.xy;
    if (any(pixel >= gResolution))
        return;

    float4 sh0 = gInSh0[pixel];
    const float4 sh1 = gInSh1[pixel];

    if (gSh0IsLinearRgb)
        sh0 = float4(_NRD_LinearToYCoCg(sh0.rgb), sh0.w);

    // MUST go through the back-end unpack: it defines the {c0, chroma, normHitDist} layout NRD
    // actually writes.
    NRD_SG sg = RELAX_BackEnd_UnpackSh(sh0, sh1.xyz);

    float3 radiance;

#if SH_RESOLVE_MODE == SH_RESOLVE_COSINE
    // NVIDIA's intended resolve: Y = c0/PI + dot(c1, N) * 3/PI, i.e. a Lambertian cosine lobe about
    // the surface normal. NOTE this bakes in a 1/PI -- it converts an irradiance-like quantity into
    // outgoing radiance off a diffuse SURFACE, so it is not energy-preserving for a medium. Kept so
    // the assumption can be measured rather than argued about.
    const float3 N = NRD_FrontEnd_UnpackNormalAndRoughness(gNormalRoughness[pixel]).xyz;
    radiance = NRD_SH_ResolveDiffuse(sg, N);
#else
    // DC term only. This renderer's media use an ISOTROPIC phase function (g = 0), so outgoing
    // radiance is the uniform average over the sphere: the dot(c1, N) lobe has no physical
    // counterpart, and there is no surface normal to evaluate it against in the first place.
    //
    // Deliberately NOT NRD_SH_ResolveDiffuse with c1 = 0: that would still apply its k0 = 1/PI
    // surface factor and return radiance/PI. Taking Y = c0 keeps the DC term as the radiance it
    // was packed from, so pack -> resolve is an identity. The YCoCg -> linear conversion is still
    // NRD's rather than a reimplementation.
    radiance = _NRD_YCoCgToLinear_Corrected(sg.c0, sg.c0, sg.chroma);
#endif

    if (any(isnan(radiance)) || any(isinf(radiance)))
        radiance = float3(0.f);

    // .a carries the normalized hit distance through, matching what the radiance path emits so
    // everything downstream sees the same layout in either mode.
    gOutRadianceHitDist[pixel] = float4(radiance, sg.normHitDist);
}
