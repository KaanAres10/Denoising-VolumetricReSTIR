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
__exported import ReSTIRHelper;
#include "HostDeviceSharedDefinitions.slangh"
import Utils.Debug.PixelDebug;
import Utils.Math.MathHelpers;
#include "Utils/Math/MathConstants.slangh"

cbuffer CB
{
    uint2   gResolution;
    int     gNumTotalRounds;
    int     gFrameCount;
    bool    gTemporalReuse;
    bool    gSpatialReuse;
    bool    gUseReference;
    int     gMaxBounces;
    bool    gVisualizeTotalTransmittance;
    bool    gNoReuse;
    // Emit gLightDir. Separate from the other guides: only NRD's SH mode needs it, and it costs an
    // extra light-sample reconstruction per pixel.
    bool    gOutputLightDir;
    // Split the radiance into the part that scattered in the medium and the part that came from a
    // surface or the background through it. Zhang et al.'s core mechanism: denoise each with the
    // features that suit it, instead of handing one composited image to surface-only guides.
    // Gated per output, not as a pair -- see the volume guides for why one shared flag is a trap.
    bool    gOutputVolumeColor;
    bool    gOutputSurfaceColor;
    // Directly-visible emitters, split off so they can bypass the denoiser entirely. NRD demodulates
    // radiance by diffuse albedo, and an emissive bulb has huge radiance with near-zero DIFFUSE
    // albedo -- so it takes the full 1/minReflectance amplification (100x at the 0.01 floor), the
    // a-trous filter smears that spike across its footprint, and re-modulation multiplies back each
    // pixel's OWN albedo, which cannot retrieve energy already leaked into its neighbours. Measured
    // on bistro: a ring 2 px around emitter cores comes out 14.7x brighter than raw, and the whole
    // frame gains 10% energy. ModulateIllumination.emission is an additive input that exists exactly
    // so emission can skip the filter.
    bool    gOutputEmissiveColor;
    bool    gOutputNonEmissiveColor;
    SamplingOptions gSamplingOptions;
    EnvMapSampler           envMapSampler; 
    EmissiveLightSampler    emissiveSampler; 
}
// Input data to accumulate and accumulated output.
StructuredBuffer<Reservoir> gCurReservoirs;
StructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
StructuredBuffer<ReservoirFeatures> gReservoirFeatureBuffer;
RWTexture2D<float4> gCurrentColors;
RWTexture2D<float4> gOutputFrame;
/// .xyz = world-space direction the reservoir's chosen light arrives FROM at the first scatter
/// vertex, .w = 1 when that direction is trustworthy and 0 when it is not. Consumed by NRD v4's SH
/// mode, which packs "direction * luminance(radiance)" -- note this is the direction incoming
/// RADIANCE comes from, so it is NOT interchangeable with mediumNormal.
RWTexture2D<float4> gLightDir;
/// The radiance split. gVolumeColor + gSurfaceColor == gOutputFrame exactly, by construction.
///
/// This is a STOCHASTIC decomposition, not a radiance decomposition. ReSTIR keeps ONE reservoir per
/// pixel, so a pixel's entire contribution lands in whichever bucket its selected sample belongs to --
/// each buffer is zero wherever the other one fired. The partition is not random, though: it is
/// governed by whether the primary ray scattered in the medium, whose expectation is exactly the
/// mediumAlpha guide. That is what makes demodulating by mediumAlpha before denoising necessary rather
/// than merely helpful -- filtering a buffer that is zero on a random half of its pixels biases the
/// result toward zero unless the coverage is divided out first.
RWTexture2D<float4> gVolumeColor;
RWTexture2D<float4> gSurfaceColor;
/// gEmissiveColor + gNonEmissiveColor == gOutputFrame exactly, by construction -- the same
/// complementary-pair shape as the volume/surface split, and verifiable the same way.
RWTexture2D<float4> gEmissiveColor;
RWTexture2D<float4> gNonEmissiveColor;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
#endif

import ComputeInitialSample;

[numthreads(16, 16, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    StructuredBufferArrayDataProvider dataProvider;
    dataProvider.data = gCurExtraBounceReservoirs;

    uint2 pixelPos = DTid.xy;
    //printSetPixel(pixelPos);

    if (any(DTid.xy >= gResolution)) return;

    uint pixelId = pixelPos.y * gResolution.x + pixelPos.x;

    float3 outputColor = 0;

    SampleGenerator sg = SampleGenerator(pixelPos, gNumTotalRounds * gFrameCount + gNumTotalRounds - 1);

    if (gUseReference) // output raw
    {
        outputColor = gCurrentColors[pixelPos].rgb;
    }
    else if (gVisualizeTotalTransmittance)
    {
        outputColor = pow(gReservoirFeatureBuffer[pixelId].transmittance, 2.2f);
    }
    else
    {
        float3 rayOrigin = gScene.camera.getPosition();
        float3 rayDir = normalize(gScene.camera.computeNonNormalizedRayDirPinhole(DTid.xy, gResolution));
        VolRay ray = { rayOrigin, rayDir, 0, kRayTMax };

        Reservoir curReservoir = gCurReservoirs[pixelId];

        if (curReservoir.runningSum > 0.f)
        {
            //// background
            float3 rayOrigin = gScene.camera.getPosition();
            float3 rayDir = normalize(computeNonNormalizedRayDirPinholeScaled(gScene.camera, DTid.xy, 1, 0.5f, gResolution));

            VolRay ray = { rayOrigin, rayDir, 0, curReservoir.depth };

            float3 curOutputColor;

            #ifdef SURFACE_SCENE
            VBufferItem vItem = gVBuffer[pixelId];
            #endif

            curOutputColor = evaluate_F(curReservoir, VBUFFERITEM dataProvider, envMapSampler, emissiveSampler, ray, sg, gSamplingOptions, gNoReuse);

            float W = curReservoir.p_y == 0.0 ? 1.f : curReservoir.runningSum / (curReservoir.p_y * curReservoir.M);

            //print(curOutputColor);
            //print(curReservoir.runningSum);
            //print(curReservoir.p_y);
            //print(curReservoir.M);
            //print(W);

            curOutputColor *= W;

            outputColor += curOutputColor;
        }
    }

    float4 curColor = float4(outputColor, 1);

    pixelPos = DTid.xy;

    if (any(isnan(curColor) || isinf(curColor))) curColor = 0.f;

    gOutputFrame[pixelPos] = curColor;

    if (gOutputVolumeColor || gOutputSurfaceColor)
    {
        // `depth == kRayTMax` is the same test evaluate_F itself uses to decide whether the sample
        // scattered in the medium, so this classification costs nothing and cannot drift from the
        // shading: no second evaluation, no duplicated branch inside evaluate_F.
        //
        // Reference mode has no reservoir -- gCurrentColors is a brute-force path trace -- so there is
        // nothing to classify. Everything goes to the surface bucket rather than being silently
        // dropped, which keeps the sum equal to the output in every mode.
        // Zero in ALL four channels for the bucket that did not fire, alpha included, so that
        // volume + surface == output exactly rather than only in rgb. A round-trip check that has to
        // special-case a channel is a check that will eventually be relaxed and stop catching things.
        const bool scatteredInMedium = !gUseReference && gCurReservoirs[pixelId].depth != kRayTMax;
        if (gOutputVolumeColor) gVolumeColor[pixelPos] = scatteredInMedium ? curColor : float4(0.f);
        if (gOutputSurfaceColor) gSurfaceColor[pixelPos] = scatteredInMedium ? float4(0.f) : curColor;
    }

    if (gOutputEmissiveColor || gOutputNonEmissiveColor)
    {
        // Same test the lightDir path already uses to recognise a self-emission reservoir.
        // kSelfEmissionLightID is -3, i.e. NEGATIVE, so it must be compared explicitly rather than
        // folded into a "< 0" check meant for the env map.
        const bool isEmissive = !gUseReference && gCurReservoirs[pixelId].lightID == kSelfEmissionLightID;
        if (gOutputEmissiveColor) gEmissiveColor[pixelPos] = isEmissive ? curColor : float4(0.f);
        if (gOutputNonEmissiveColor) gNonEmissiveColor[pixelPos] = isEmissive ? float4(0.f) : curColor;
    }

    if (gOutputLightDir)
    {
        // Reconstruct the direction the reservoir's light lies in, mirroring the branch in
        // evaluate_L_in_volume(). Written AFTER the shading loop and with its own SampleGenerator:
        // getAnalyticalLightSample() draws from the stream it is handed, so reusing `sg` here would
        // shift every subsequent random number and silently change the rendered image.
        float3 wi = 0.f;
        float valid = 0.f;

        Reservoir res = gCurReservoirs[pixelId];

        // Volume self-emission overloads Reservoir::lightID -- encodeEmissivePosition() stores
        // asint(pos.z) there, a float bit pattern rather than a light index. The disambiguator is in
        // a DIFFERENT field: encodeEmissivePosition is always paired with encodePathTag(..., 1)
        // (ComputeInitialSample.slang), and that tag lives in bits 16-19 of sampledPixel. So the two
        // encodings can be told apart exactly, and emissive media do not have to be rejected
        // wholesale.
        const bool emissivePath = decodePathTag(res.sampledPixel) == 1;
        // kSelfEmissionLightID is -3, i.e. NEGATIVE -- a bounce-0 self-emission reservoir is neither
        // rewritten nor tagged, so without this it would fall into the "< 0" env-map branch below and
        // return a direction decoded from lightUV that means nothing.
        const bool selfEmission = res.lightID == kSelfEmissionLightID;

        if (res.runningSum > 0.f && !gUseReference && !emissivePath && !selfEmission)
        {
            const float3 org = gScene.camera.getPosition();
            const float3 dir = normalize(computeNonNormalizedRayDirPinholeScaled(gScene.camera, DTid.xy, 1, 0.5f, gResolution));
            const float3 p = org + dir * res.depth; // first scatter vertex
            const int lightCount = (int)gScene.getLightCount();

            if (res.lightID < 0)
            {
                wi = gScene.envMap.uvToWorld(res.lightUV, false);
                valid = 1.f;
            }
            else if (res.lightID < lightCount)
            {
                SampleGenerator sgDir = SampleGenerator(pixelPos, gFrameCount);
                SceneLightSample ls = getAnalyticalLightSample(res.lightID, p, sgDir);
                wi = ls.rayDir;
                valid = 1.f;
            }
            else
            {
                // Emissive triangle. This branch previously took the DEVICE DOWN
                // (DXGI_ERROR_DEVICE_REMOVED) on plume, and the reason matters: the triangle buffer
                // behind sampleTriangleOffset is [root]-tagged, so it bypasses descriptor bounds
                // checking, AND it is not bound at all when the scene has no emissive triangles.
                // Any index is then a raw page fault -- not merely an out-of-range read.
                //
                // getTriangleCount() is safe to call regardless: it is a uniform in the scene
                // constant block, not a buffer load, and defaults to 0 when no light collection
                // exists. It is also the right bound -- the reservoir stores a RAW triangle index
                // (VolumeUtils.slang: triangleIndex + getLightCount()), which getActiveTriangleCount()
                // would not bound correctly.
                const uint triIdx = (uint)(res.lightID - lightCount);
                if (gSamplingOptions.useEmissiveLights && triIdx < gScene.lightCollection.getTriangleCount())
                {
                    TriangleLightSample ls;
                    if (sampleTriangleOffset(p, triIdx, res.lightUV, ls))
                    {
                        wi = ls.dir;
                        valid = 1.f;
                    }
                }
            }

            const float lenSq = dot(wi, wi);
            if (!(lenSq > 1e-12f) || any(isnan(wi)) || any(isinf(wi)))
            {
                wi = 0.f;
                valid = 0.f;
            }
            else
            {
                wi *= rsqrt(lenSq);
            }
        }

        gLightDir[pixelPos] = float4(wi, valid);
    }
}


