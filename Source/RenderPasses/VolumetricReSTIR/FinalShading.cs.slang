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

    if (gOutputLightDir)
    {
        // Reconstruct the direction the reservoir's light lies in, mirroring the branch in
        // evaluate_L_in_volume(). Written AFTER the shading loop and with its own SampleGenerator:
        // getAnalyticalLightSample() draws from the stream it is handed, so reusing `sg` here would
        // shift every subsequent random number and silently change the rendered image.
        float3 wi = 0.f;
        float valid = 0.f;

        Reservoir res = gCurReservoirs[pixelId];

        // Volume self-emission overloads Reservoir::lightID: encodeEmissivePosition() stores
        // asint(pos.z) in it, so the value is a float bit pattern rather than a light index and the
        // branch below cannot tell the two apart. The disambiguating flag (isCurrentVertexEmissive)
        // exists only inside the path evaluation. Rather than guess, declare the direction invalid
        // for emissive media and let the consumer decide -- a wrong direction would still produce a
        // plausible-looking image, which is the failure mode worth avoiding.
        const bool lightIDIsAmbiguous = gScene.volumeDesc.hasEmission;

        if (res.runningSum > 0.f && !gUseReference && !lightIDIsAmbiguous)
        {
            const float3 org = gScene.camera.getPosition();
            const float3 dir = normalize(computeNonNormalizedRayDirPinholeScaled(gScene.camera, DTid.xy, 1, 0.5f, gResolution));
            const float3 p = org + dir * res.depth; // first scatter vertex

            if (res.lightID < 0)
            {
                wi = gScene.envMap.uvToWorld(res.lightUV, false);
                valid = 1.f;
            }
            else if (res.lightID < (int)gScene.getLightCount())
            {
                SampleGenerator sgDir = SampleGenerator(pixelPos, gFrameCount);
                SceneLightSample ls = getAnalyticalLightSample(res.lightID, p, sgDir);
                wi = ls.rayDir;
                valid = 1.f;
            }
            // NOTE: no emissive-triangle branch. evaluate_L_in_volume() reaches
            // sampleTriangleOffset() only for reservoirs it knows hold a triangle sample; doing the
            // same here from lightID alone indexed the light collection out of bounds and took the
            // device down (DXGI_ERROR_DEVICE_REMOVED) on plume, which has no emissive triangles at
            // all. Emissive-lit scenes therefore report valid = 0 rather than a guessed direction.
            // Lifting this needs the triangle count to bound-check against, or the emissive flag
            // that only exists inside the path evaluation.

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


