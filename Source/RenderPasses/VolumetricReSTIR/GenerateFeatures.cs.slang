/***************************************************************************
 # Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
 # EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 # PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 # OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 **************************************************************************/

 /** Temporal accumulation render pass.

     There are entry points for each of the three supported accumulation modes.
     Note that for the compensated summation mode the shader _must_ be compiled
     for precise floating-point operations (no reordering).

     In all modes, the shader writes the current accumulated average to the
     output texture. The intermediate buffers are internal to the pass.
 */

#include "Utils/Math/MathConstants.slangh"
__exported import ReSTIRHelper;
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;
import Utils.Math.MathHelpers; // calcMotionVector()

cbuffer CB
{
    uint2   gResolution;
    bool    gUseReference;
    SamplingOptions gInitialSamplingOptions;
    // Guide-buffer outputs for temporal upscalers (DLSS). Both default off; when off the textures
    // are not even allocated, so this costs nothing.
    bool    gOutputDepth;
    bool    gOutputDeterministicMV;
    bool    gDepthAsNDC;            // false = linear view Z (GBufferRT.linearZ layout)
    // Depth/mvec follow the medium only where it supplies at least this share of the pixel's light;
    // 0 = wherever it is met at all. See mGuideMediumMinShare.
    float   gGuideMediumMinShare;
    // The previous frame's light statistics (GuideLightStats.cs.slang) are bound and usable, and the
    // mip that averages them over the neighbourhood.
    bool    gGuideLightStatsValid;
    float   gGuideLightStatsMip;
    // Volumetric guides for DLSS Ray Reconstruction. RR's albedo/normal/roughness guides describe a
    // surface; a participating medium has none, so instead we export how much of the pixel the
    // medium covers and a stand-in normal, and blend toward medium-like values downstream.
    // This now gates only whether the MARCH runs; each guide below has its own flag, because one
    // shared flag meant requesting a single guide silently produced a zeroed buffer.
    bool    gOutputVolumeGuides;
    bool    gOutputMediumAlpha;
    bool    gOutputMediumNormal;
    // Optical thickness tau = -log(transmittance), free from the march's accumulated exponent.
    bool    gOutputOpticalThickness;
    // Velocity of the medium at the scatter point, split into direction and magnitude the way Zhang et
    // al. list them as two separate features. Free: VelocityWorld is already sampled here for the
    // motion vector.
    bool    gOutputVolumeVelocity;
    // Density at the scatter point. Unlike optical thickness (an integral along the whole ray) this is
    // a LOCAL quantity, which is the reason to expect it to carry structure the integrals average away.
    bool    gOutputScatterDensity;
    // Confinement mask for the split's volume half. NOT the raw coverage: the volume denoiser blurs
    // the plume's radiance past its own silhouette (measured leak ratio raw 0.326 -> REBLUR 0.401,
    // with the core losing 15% of its energy), and multiplying by raw alpha would kill that halo but
    // also darken the core by ~10% -- trading one error for another. saturate(alpha/knee) is ~1
    // wherever the medium actually is and 0 outside, so it confines without dimming.
    bool    gOutputMediumCoverage;
    float   gCoverageKnee;
    // Primary-ray transmittance, for NRD's IN_DIFF_CONFIDENCE on the surface half. See the write site.
    bool    gOutputMediumTransmittance;
    // 0 = camera-facing stand-in, 1 = density gradient. A switch rather than a replacement: the
    // existing comment rejects the gradient as noisy in the plume core and prone to GVDB apron
    // artifacts, and that objection deserves a measurement rather than an assumption.
    uint    gVolumeNormalMode;
    // Expected scattering distance along the primary ray, for NRD's hit-distance guide. Separate
    // flag from gOutputVolumeGuides because the two denoisers want different subsets, but it is
    // written from the same block, so gOutputVolumeGuides gates whether that block runs at all.
    bool    gOutputScatterDistance;
}

// VR_SPECIALIZE (SpecializeOptions.slangh): the sampling options and the pass's static switches (field
// bit 25) compiled in as constants from the values the host also writes into CB.
#include "SpecializeOptions.slangh"
#if VR_SPECIALIZE
static const SamplingOptions kInitialSamplingOptions = VR_INITIAL_OPTIONS;
#define INITIAL_OPTIONS specializeOptions(kInitialSamplingOptions, gInitialSamplingOptions)
#define GF_UseReference (VR_SPECIALIZES(25) ? VR_GF_UseReference : gUseReference)
#define GF_OutputDepth (VR_SPECIALIZES(25) ? VR_GF_OutputDepth : gOutputDepth)
#define GF_OutputDeterministicMV (VR_SPECIALIZES(25) ? VR_GF_OutputDeterministicMV : gOutputDeterministicMV)
#define GF_DepthAsNDC (VR_SPECIALIZES(25) ? VR_GF_DepthAsNDC : gDepthAsNDC)
#define GF_OutputVolumeGuides (VR_SPECIALIZES(25) ? VR_GF_OutputVolumeGuides : gOutputVolumeGuides)
#define GF_OutputMediumAlpha (VR_SPECIALIZES(25) ? VR_GF_OutputMediumAlpha : gOutputMediumAlpha)
#define GF_OutputMediumNormal (VR_SPECIALIZES(25) ? VR_GF_OutputMediumNormal : gOutputMediumNormal)
#define GF_OutputOpticalThickness (VR_SPECIALIZES(25) ? VR_GF_OutputOpticalThickness : gOutputOpticalThickness)
#define GF_OutputVolumeVelocity (VR_SPECIALIZES(25) ? VR_GF_OutputVolumeVelocity : gOutputVolumeVelocity)
#define GF_OutputScatterDensity (VR_SPECIALIZES(25) ? VR_GF_OutputScatterDensity : gOutputScatterDensity)
#define GF_OutputMediumCoverage (VR_SPECIALIZES(25) ? VR_GF_OutputMediumCoverage : gOutputMediumCoverage)
#define GF_OutputMediumTransmittance (VR_SPECIALIZES(25) ? VR_GF_OutputMediumTransmittance : gOutputMediumTransmittance)
#define GF_VolumeNormalMode (VR_SPECIALIZES(25) ? VR_GF_VolumeNormalMode : gVolumeNormalMode)
#define GF_OutputScatterDistance (VR_SPECIALIZES(25) ? VR_GF_OutputScatterDistance : gOutputScatterDistance)
#else
#define INITIAL_OPTIONS gInitialSamplingOptions
#define GF_UseReference gUseReference
#define GF_OutputDepth gOutputDepth
#define GF_OutputDeterministicMV gOutputDeterministicMV
#define GF_DepthAsNDC gDepthAsNDC
#define GF_OutputVolumeGuides gOutputVolumeGuides
#define GF_OutputMediumAlpha gOutputMediumAlpha
#define GF_OutputMediumNormal gOutputMediumNormal
#define GF_OutputOpticalThickness gOutputOpticalThickness
#define GF_OutputVolumeVelocity gOutputVolumeVelocity
#define GF_OutputScatterDensity gOutputScatterDensity
#define GF_OutputMediumCoverage gOutputMediumCoverage
#define GF_OutputMediumTransmittance gOutputMediumTransmittance
#define GF_VolumeNormalMode gVolumeNormalMode
#define GF_OutputScatterDistance gOutputScatterDistance
#endif

// Input data to accumulate and accumulated output.
RWStructuredBuffer<ReservoirFeatures> gReservoirFeatureBuffer;
#ifdef SURFACE_SCENE
RWStructuredBuffer<VBufferItem> gVBuffer;
#endif

// Guide buffers. gMotionVec here is the DETERMINISTIC writer; the legacy stochastic writer lives in
// TemporalReuse.cs.slang and the host guarantees only one of them is ever active.
RWTexture2D<float2> gLinearZ;
RWTexture2D<float2> gMotionVec;
// Volumetric guides: medium coverage (1 - transmittance) and a stand-in "normal" for the medium.
RWTexture2D<float> gMediumAlpha;
RWTexture2D<float4> gMediumNormal;
// Optical thickness along the primary ray. Saturates near 4.6 (the march's transmittance early-out).
RWTexture2D<float> gOpticalThickness;
// xyz = velocity vector in world units per frame, w = its magnitude (redundant, but free, and .w does
// not survive an EXR capture -- see the write site).
RWTexture2D<float4> gVolumeVelocity;
// Density at the scatter point; 0 where the ray met no medium.
RWTexture2D<float> gScatterDensity;
/// rgb all carry the mask: ModulateIllumination reads a reflectance as .rgb, and a single-channel
/// R16Float bound there would read (a,0,0) and tint the medium red.
RWTexture2D<float4> gMediumCoverage;
/// rgb all carry the value for the same reason as gMediumCoverage: NRD samples confidence as a
/// single channel, but the texture is easier to inspect and to reuse when it is not (c,0,0).
RWTexture2D<float4> gMediumTransmittance;
// Raw expected scatter distance along the ray (world units), -1 where the ray met no medium.
RWTexture2D<float> gScatterDistance;
// Running average of (medium light, coverage, surface light, transmittance), with mips -- the
// previous frame's, from GuideLightStats.cs.slang. Read only for the depth/mvec layer choice.
Texture2D<float4> gGuideLightStats;

/** Share of this pixel's light that comes from the medium, for choosing which layer depth/mvec
    describe. `coverage` and `transmittance` are this pixel's own (exact, from the march); the two
    layers' brightness comes from the neighbourhood statistics as medium light per unit coverage and
    surface light per unit transmittance. Without statistics both layers count as equally bright, so
    the share is simply the coverage.
*/
float mediumLightShare(int2 pixelPos, float coverage, float transmittance)
{
    if (gGuideLightStatsValid)
    {
        const float2 uv = (float2(pixelPos) + 0.5f) / float2(gResolution);
        const float4 s = gGuideLightStats.SampleLevel(gLinearSampler, uv, gGuideLightStatsMip);
        if (s.y > 1e-4f && s.w > 1e-4f)
        {
            const float mediumLight = coverage * (s.x / s.y);
            const float surfaceLight = transmittance * (s.z / s.w);
            if (mediumLight + surfaceLight > 0.f) return mediumLight / (mediumLight + surfaceLight);
        }
    }
    return coverage;
}

[numthreads(16, 16, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{

    const int2 pixelPos = DTid.xy;
    //printSetPixel(pixelPos );

    int2 resolution = gResolution;
    if (any(DTid.xy >= resolution)) return;

    // sg is not important, since we are not using it anyway
    SampleGenerator sg;

    int pixelId = getPixelID(pixelPos, resolution);

    CameraRay cameraRay = computeRayPinholeScaled(gScene.camera, pixelPos, 1, 0.5f, gResolution);

    VolRay ray = { cameraRay.origin, cameraRay.dir, 0, kRayTMax };

    float3 surfaceNormal = 0.f;

#ifdef SURFACE_SCENE
    SurfaceHitInfo hitInfo = FindSurfaceHit(ray.origin, ray.dir, 0, kRayTMax);
    if (hitInfo.isValidHit())
    {
        SurfaceShadingData shadingInfo = computeSurfaceShadingInfo(hitInfo, -ray.dir);
        surfaceNormal = shadingInfo.N;
        if (any(shadingInfo.emissive > 0.f)) surfaceNormal = 0.f;
    }

    ray.tMax = hitInfo.rayT;
    VBufferItem vbufferItem = { hitInfo.meshInstanceID, hitInfo.primitiveIndex, hitInfo.barycentrics, hitInfo.rayT };
#endif

#ifdef SURFACE_SCENE
    gVBuffer[pixelId] = vbufferItem;
#endif

    // The march is also what produces the guide buffers, so it must run when either is requested
    // even in reference mode. The feature-buffer store stays gated, as before.
    // Volume guides must be in this list: a DLSS-D graph takes depth and motion vectors from a
    // GBuffer, so gOutputDepth and gOutputDeterministicMV are both false there, and omitting the
    // volume flag silently skipped the whole block.
    const bool needGuides = GF_OutputDepth || GF_OutputDeterministicMV || GF_OutputVolumeGuides;
    if (!GF_UseReference || needGuides)
    {
        float accuTransmittance;
        float expectedT;
        ReservoirFeatureRayMarchingGeneric(ray, sg, 0, true, INITIAL_OPTIONS.visibilityTStepScale, accuTransmittance, expectedT);

        if (!GF_UseReference)
        {
            ReservoirFeatures features = { int(all(surfaceNormal == 0.f)), accuTransmittance };
            gReservoirFeatureBuffer[pixelId] = features;
        }

        if (needGuides)
        {
            // NRD's hit-distance guide. Written from the RAW expectedT, before the fallbacks below,
            // so the -1 "this ray never met the medium" sentinel survives -- NRD's consumer needs to
            // tell that apart from "medium at the far plane", which the linearZ fallback conflates.
            if (GF_OutputScatterDistance)
            {
                gScatterDistance[pixelPos] = expectedT;
            }

            // Pick the representative depth: the expected scattering distance inside the medium,
            // else the opaque surface hit, else the far plane. All are distances along the ray.
            float t = expectedT;
            // ...but the medium only where it supplies enough of the pixel's light to be what the pixel
            // shows (see mGuideMediumMinShare). Measured mid-orbit on bistro: 28k pixels of the plume's
            // outer fringe -- 11k of them below 0.1% coverage -- carried the smoke's motion, 6.9 px per
            // frame away from the ground's they actually show, which is exactly the veil RR laid over
            // that ground. Skipped entirely at 0, so the outputs stay bit-identical to the old rule.
            if (t >= 0.f && gGuideMediumMinShare > 0.f &&
                mediumLightShare(pixelPos, 1.f - accuTransmittance, accuTransmittance) < gGuideMediumMinShare)
                t = -1.f;
#ifdef SURFACE_SCENE
            if (t < 0.f && hitInfo.isValidHit()) t = hitInfo.rayT;
#endif
            const float3 fwd = normalize(gScene.camera.data.cameraW);
            const float cosTheta = dot(fwd, cameraRay.dir); // == 1 / invCos in VolumeBase.slang
            if (t < 0.f) t = gScene.camera.data.farZ / max(1e-6f, cosTheta);

            const float3 p = cameraRay.origin + cameraRay.dir * t;

            if (GF_OutputDepth)
            {
                if (GF_DepthAsNDC)
                {
                    float4 clip = mul(gScene.camera.data.viewProjMatNoJitter, float4(p, 1.f));
                    gLinearZ[pixelPos] = float2(clip.z / clip.w, 0.f);
                }
                else
                {
                    // Linear view Z, matching GBufferRT's "linearZ" (RG32Float, .y = slope, unused).
                    gLinearZ[pixelPos] = float2(t * cosTheta, 0.f);
                }
            }

            if (GF_OutputDeterministicMV)
            {
                // Advect the point backwards through the velocity grid so the plume's own motion is
                // represented, not just the camera's (mirrors TemporalReuse.cs.slang).
                float3 pPrev = p;
                if (gScene.volumeDesc.hasVelocity && gScene.volumeDesc.hasAnimation)
                    pPrev -= VelocityWorld(p) * gScene.volumeDesc.velocityScale;

                // Falcor 8 convention is mul(M, v) -- NOT the mul(v, M) used by TemporalReuse.
                float4 prevPosH = mul(gScene.camera.data.prevViewProjMatNoJitter, float4(pPrev, 1.f));
                // calcMotionVector returns current->previous in normalized [0,1] screen space with a
                // top-left origin, i.e. exactly DLSSPass' motionVectorScale='Relative'. The jitter
                // term cancels the current frame's subpixel offset (cf. GBufferRT.slang).
                gMotionVec[pixelPos] = calcMotionVector(float2(pixelPos) + 0.5f, prevPosH, float2(gResolution))
                    + float2(gScene.camera.data.jitterX, -gScene.camera.data.jitterY);
            }

            // Gated INDIVIDUALLY. These used to share one flag that the host only set when BOTH
            // textures were allocated, so asking for just one silently produced a zeroed buffer --
            // no warning, and it looks like the renderer computing zero rather than never writing.
            if (GF_OutputMediumAlpha)
            {
                // Medium coverage. accuTransmittance is the total transmittance along the primary
                // ray, so 1 - it is the fraction of this pixel the medium accounts for -- exactly
                // the weight for blending surface guides toward medium-like ones. Preferred over
                // the tracking adapter's weightSum, which saturates because the march terminates
                // early once transmittance drops below 0.01.
                gMediumAlpha[pixelPos] = saturate(1.f - accuTransmittance);
            }

            // Did this ray actually meet the medium? `t` above falls back to the surface hit and then
            // to the far plane, so `p` is a valid point either way -- but the volume-local guides below
            // are only meaningful where there was something to scatter off.
            const bool hasMedium = expectedT >= 0.f;

            if (GF_OutputMediumNormal)
            {
                if (GF_VolumeNormalMode == 1 && hasMedium)
                {
                    // Density gradient: the medium's own structure, pointing from dense to thin. This
                    // is the only candidate normal that carries volume information at all.
                    float3 grad = DensityGradientWorldSpace(p, 0);
                    float len = length(grad);
                    // Fall back to the camera-facing stand-in where the field is locally flat. Without
                    // this the plume core -- smooth by construction -- would get a normalize() of
                    // near-zero, i.e. direction noise amplified to full scale, which is precisely the
                    // failure the original comment predicted.
                    gMediumNormal[pixelPos] = len > 1e-6f ? float4(-grad / len, 0.f)
                                                          : float4(-cameraRay.dir, 0.f);
                }
                else
                {
                    // Stand-in normal for the medium: face the camera. An isotropic scatterer has no
                    // meaningful surface orientation, and -rayDir combined with roughness=1 downstream
                    // reads to RR as "diffuse blob facing the viewer". Costs nothing and cannot fail.
                    //
                    // NOTE this carries NO volume information -- it is a pure function of pixel
                    // coordinate. Anything edge-stopping on it (NRD's RELAX does) sees a perfectly
                    // smooth field across the medium.
                    gMediumNormal[pixelPos] = float4(-cameraRay.dir, 0.f);
                }
            }

            if (GF_OutputVolumeVelocity)
            {
                // Direction and magnitude kept apart on purpose: they are two features in Zhang et
                // al.'s pool, and magnitude alone is what predicts where reprojection should be
                // distrusted. Free -- the same sample already feeds the motion vector above.
                float3 v = 0.f;
                if (hasMedium && gScene.volumeDesc.hasVelocity && gScene.volumeDesc.hasAnimation)
                    v = VelocityWorld(p) * gScene.volumeDesc.velocityScale;
                // MEASURED ZERO on every baked asset, with all three flags above true. The cause is
                // not here: GVDBBake hardcodes `isVelocity = 0` and exports only channel 0 of the
                // atlas, while still setting hdr.hasVelocity = 1 whenever the *_velocity_*.vbx files
                // merely exist -- and the baked loader then uploads that slot as a scalar R32Float
                // into volIn[17], discarding the isVel flag it just read, so `velocityIn` (what
                // getVelocityAtPoint samples) is never populated. See SceneGVDB.cpp:737-753 against
                // the non-baked path at :544. Until the bake tool and that loader are fixed and the
                // sequence re-baked, this guide is identically zero and so are the velocity-advected
                // motion vectors -- which is exactly why VR_NRD_VOLMV measured 1.86e-05, i.e. nothing.
                // xyz holds the RAW vector, not a normalized direction, so both features survive a
                // capture: Falcor writes RGBA16Float to a 3-channel EXR and drops .w, which silently
                // took the magnitude with it when the direction lived in xyz. Consumers reading the
                // texture directly still get the magnitude from .w without recomputing it.
                gVolumeVelocity[pixelPos] = float4(v, length(v));
            }

            if (GF_OutputMediumCoverage)
            {
                const float cov = saturate((1.f - accuTransmittance) / max(gCoverageKnee, 1e-4f));
                gMediumCoverage[pixelPos] = float4(cov, cov, cov, 1.f);
            }

            // Transmittance, straight, as NRD's history confidence for the SURFACE half.
            //
            // The surface half's radiance is T * L_surface. T belongs to the medium BETWEEN camera
            // and surface, so it does not follow the surface's motion vector -- and a denoiser
            // reprojecting along that vector will happily carry a wall's radiance into a pixel the
            // plume has since moved in front of. Every guide it could test says the reprojection is
            // valid, because viewZ, normal and plane distance all describe the wall, and smoke does
            // not change the G-buffer. Measured on bistro's orbit, dense band (alpha > 0.75): the
            // undenoised surface half is 7.2e-4 there, RELAX gives 8.3e-4, REBLUR gives 146.5e-4 --
            // twenty times the energy that exists, which is the entire "see-through smoke".
            //
            // Confidence is 1 where there is no medium (nothing to invalidate) and falls to 0 as the
            // medium goes opaque, which is exactly where a stale reprojection does the most damage
            // and where losing the accumulation costs least, since the term is multiplied by T
            // anyway. Written for EVERY pixel, medium or not: a confidence texture that is zero
            // outside the plume would reset history across the whole frame.
            if (GF_OutputMediumTransmittance)
            {
                const float tr = saturate(accuTransmittance);
                gMediumTransmittance[pixelPos] = float4(tr, tr, tr, 1.f);
            }

            if (GF_OutputScatterDensity)
            {
                gScatterDensity[pixelPos] = hasMedium ? max(0.f, DensityWorldSpace(p, 0)) : 0.f;
            }

            // Optical thickness tau = -log(Tr), the exponent the march already accumulated. Free:
            // accuTransmittance is exp(-tau). Saturates near 4.6 because the march early-outs once
            // transmittance drops below 0.01, so treat it as "thickness up to opaque", not a
            // physical integral to infinity.
            if (GF_OutputOpticalThickness)
            {
                gOpticalThickness[pixelPos] = -log(max(accuTransmittance, 1e-6f));
            }
        }
    }
}
