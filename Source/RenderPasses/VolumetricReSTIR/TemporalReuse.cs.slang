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

cbuffer CB
{
    uint2   gResolution;
    int     gFrameCount;
    int     gNumTotalRounds;
    int     gRoundOffset;
    float   gTemporalHistoryThreshold;
    bool    gIsFirstFrame;
    uint    gMISMethod;
    float4x4 gPrevViewMat;
    float4x4 gPrevProjMat;
    int     gReprojectionMipLevel;
    uint    gReprojectionMode;
    bool    gOutputMotionVec;
    bool    gReprojectIndependent;  // see the reprojection point below
    bool    gReprojectByLightShare; // with gReprojectIndependent: see reprojectSurfaceProbability()
    bool    gGuideLightStatsValid;  // gGuideLightStats holds last frame's statistics
    float   gGuideLightStatsMip;
    float3  gPrevCameraU;
    float3  gPrevCameraV;
    float3  gPrevCameraW;
    float3  gPrevCameraPosW;
    // Jitter the PREVIOUS frame was rendered with. Required to reconstruct the previous frame's rays
    // exactly; zero when jitter is disabled, which reduces the math to the unjittered form.
    float2  gPrevJitter;
    SamplingOptions gSamplingOptions;
    EnvMapSampler           envMapSampler;      ///< Environment map sampler.
    EmissiveLightSampler           emissiveSampler;  
}

// VR_SPECIALIZE (SpecializeOptions.slangh): the sampling options compiled in as constants from the
// values the host also writes into CB.
#include "SpecializeOptions.slangh"
#if VR_SPECIALIZE
static const SamplingOptions kSamplingOptions = VR_SAMPLING_OPTIONS;
#define SAMPLING_OPTIONS specializeOptions(kSamplingOptions, gSamplingOptions)
#else
#define SAMPLING_OPTIONS gSamplingOptions
#endif

// Input data to accumulate and accumulated output.
RWStructuredBuffer<Reservoir> gCurReservoirs;
RWStructuredBuffer<Reservoir> gTemporalReservoirs;
RWStructuredBuffer<ExtraBounceReservoir> gCurExtraBounceReservoirs;
RWStructuredBuffer<ExtraBounceReservoir> gTemporalExtraBounceReservoirs;
StructuredBuffer<ReservoirFeatures> gReservoirFeatureBuffer;
StructuredBuffer<ReservoirFeatures> gTemporalReservoirFeatureBuffer;
RWTexture2D<float2> gMotionVec;
#ifdef SURFACE_SCENE
StructuredBuffer<VBufferItem> gVBuffer;
StructuredBuffer<VBufferItem> gTemporalVBuffer;
#endif
/// GuideLightStats.cs.slang's running average of (medium light, coverage, surface light, transmittance).
Texture2D<float4> gGuideLightStats;

/** How often gReprojectIndependent follows the SURFACE's motion rather than the medium's.

    By default the transmittance T -- the surface's share of the pixel's COVERAGE. At thin medium that
    follows the surface nearly always, so the medium's samples rarely find a matching history and its
    light is noisy in motion (it is not biased: any choice made without looking at this frame's sample
    keeps the Talbot weights summing to one). With gReprojectByLightShare it is the surface's share of
    the pixel's LIGHT, so the history follows whichever layer supplies the light. Estimated the way
    GenerateFeatures' mediumLightShare() does for the guides, from the same statistics: this pixel's
    coverage and T, times the neighbourhood's medium light per unit coverage and surface light per unit
    transmittance -- last frame's running average, so still independent of this frame's sample.
*/
float reprojectSurfaceProbability(int2 pixelPos, float T)
{
    if (gReprojectByLightShare && gGuideLightStatsValid)
    {
        const float2 uv = (float2(pixelPos) + 0.5f) / float2(gResolution);
        const float4 s = gGuideLightStats.SampleLevel(gLinearSampler, uv, gGuideLightStatsMip);
        if (s.y > 1e-4f && s.w > 1e-4f)
        {
            const float mediumLight = (1.f - saturate(T)) * (s.x / s.y);
            const float surfaceLight = saturate(T) * (s.z / s.w);
            if (mediumLight + surfaceLight > 0.f) return surfaceLight / (mediumLight + surfaceLight);
        }
    }
    return T;
}

// Thread-group size. 8x8, not 16x16: these kernels need 128-224 registers per thread, and with
// 256-thread groups the SM's 64K registers hold whole groups only -- at 192 registers that is one group,
// 8 warps. 64-thread groups pack to the register limit instead (10 warps at 192). Measured on the
// bistro raw estimator: 16x16 101.0 ms, 8x8 89.5, 8x4 92.4, 16x4 93.2, 32x2 108.0. Every thread's work
// depends only on its pixel (no groupshared memory, group ids or wave ops), so this changes
// occupancy, never results -- captures are byte-identical. VR_GROUP=WxH overrides it for an A/B.
#ifndef VR_GROUP_X
#define VR_GROUP_X 8
#endif
#ifndef VR_GROUP_Y
#define VR_GROUP_Y 8
#endif
[numthreads(VR_GROUP_X, VR_GROUP_Y, 1)]
void main(uint3 DTid : SV_DispatchThreadID)
{
    RWStructuredBufferArrayDataProvider curDataProvider;
    curDataProvider.data = gCurExtraBounceReservoirs;
    RWStructuredBufferArrayDataProvider tempDataProvider;
    tempDataProvider.data = gTemporalExtraBounceReservoirs;

    const int2 pixelPos = DTid.xy;

    if (any(DTid.xy >= gResolution)) return;
    printSetPixel(pixelPos);

    if (!gIsFirstFrame)
    {
        SampleGenerator sg = SampleGenerator(DTid.xy, gNumTotalRounds * gFrameCount + gRoundOffset); // prevent correlation with ray traicng shaders

        int selectedId = -1;

        int pixelId = getPixelID(pixelPos, gResolution);

        // temporal reprojection using motion vectors

        int numUsedReservoirs = 1;
        Reservoir taps[2];
        taps[0] = gCurReservoirs[pixelId];

        CameraRay cameraRay = computeRayPinholeScaled(gScene.camera, pixelPos, 1, 0.5f, gResolution);

        VolRay ray = { cameraRay.origin, cameraRay.dir, 0, kRayTMax };

        Reservoir output;
        if (gMISMethod == kMISTalbot) output = createNewReservoir();
        else output = taps[0];

    #if MAX_BOUNCES > 1
        int centerExtraBounceStartId = taps[0].extraBounceStartId;
    #endif
        // for background samples, find a random reprojection point

        float temporalOriginalDepth = 0.f;
        int2 reprojScreenPos = 0;

        ReservoirFeatures centerFeatures = gReservoirFeatureBuffer[pixelId];
        bool isBackgroundReservoir = centerFeatures.transmittance == 1.f && centerFeatures.noReflectiveSurface;

        bool useFallbackReservoir = true;

        if (gReprojectionMode != kReprojectionNone)
        {
            // The reprojection point picks the temporal neighbour. By default it is the canonical
            // sample's own depth whenever that sample scattered in the medium, so the neighbour depends
            // on the sample: the canonical sample's Talbot weight is computed against a neighbour chosen
            // FOR it, while the neighbour's samples are weighted against the neighbours chosen for all
            // the OTHER canonical samples, and the two weights stop summing to one. With a still camera
            // every choice lands on the same pixel and nothing changes. While the camera moves,
            // parallax sends medium and surface to different pixels, and where the medium is thin --
            // its samples a minority, most neighbours picked through the surface behind it -- it loses
            // light. gReprojectIndependent draws the point from the pixel alone, as the surface-sample
            // branch below already does: the surface with probability T, else a point by density.
            // Bistro, stop-and-go, lights frozen, vs a 256-frame truth, medium light while moving (thin /
            // silhouette): 0.60 / 0.80 -> 0.99 / 1.00; still camera unchanged; ~1.7-2x the noise at a
            // moving silhouette (its history now matches it less often); +0.06 ms at 960x540.
            float reprojDepth = (gReprojectIndependent && gReprojectionMode == kReprojectionLinear) ? kRayTMax : taps[0].depth;
            bool reprojectUsingVolumeSample = true;

            if (reprojDepth == kRayTMax && gReprojectionMode != kReprojectionNoBackground && !isBackgroundReservoir)
            {
            #ifdef SURFACE_SCENE
                VBufferItem vItem = gVBuffer[pixelId];
                SurfaceHitInfo hitInfo = { vItem.meshInstanceID, vItem.primitiveID, vItem.barycentrics, vItem.rayT };

                // if we have reflective surfaces, they also need temporal resampling to reduce noise.
                // so we randomly decide using surface or volume (velocity resampling) by total transmittance
                if (!centerFeatures.noReflectiveSurface)
                {
                    reprojDepth = hitInfo.rayT;
                    // are we almost surface or almost volume?
                    if (sampleNext1D(sg) < (gReprojectIndependent ? reprojectSurfaceProbability(pixelPos, centerFeatures.transmittance)
                                                                   : centerFeatures.transmittance))
                    {
                        reprojectUsingVolumeSample = false;
                    }
                }

                if (reprojectUsingVolumeSample)
            #endif
                {
                    // velocity resampling
                    reprojDepth = RejectionSampleRandomPointByDensity(ray, sg, kNumMaxMips + gReprojectionMipLevel); // always use conservative grid!
                }
            }

            float3 p = cameraRay.origin + cameraRay.dir * reprojDepth;

            // find last frame world position if having velocity grid
            if (gScene.volumeDesc.hasVelocity && gScene.volumeDesc.hasAnimation && reprojectUsingVolumeSample)
            {
                float3 v = VelocityWorld(p) *  gScene.volumeDesc.velocityScale;
                p = p - v;
            }

            float4 viewPos = mul(float4(p, 1.f), gPrevViewMat);
            float4 clipPos = mul(viewPos, gPrevProjMat);

            float2 scrPos = clipPos.xy / clipPos.w;
            int2 scrPosI; 

            if (reprojDepth == kRayTMax)
            {
                scrPos = pixelPos + 0.5f;
                scrPosI = pixelPos;
            }
            else
            {
                scrPos.x = 0.5 * scrPos.x + 0.5;
                scrPos.y = -0.5 * scrPos.y + 0.5;
                scrPos *= gResolution;
                scrPosI = int2(scrPos);
            }

            // Publish the reprojection before any early-out below: reprojScreenPos is initialized to
            // 0 at declaration, so the motion-vector write on the early-return path used to emit
            // (0 - pixelPos), a vector pointing at the top-left corner, for every background pixel.
            reprojScreenPos = scrPosI;

            {
                // Range-check before indexing: scrPosI comes from a projection and can land outside
                // the frame, and getPixelID() does no clamping.
                if (IsWithinRange(scrPosI, gResolution))
                {
                    ReservoirFeatures tapFeatures = gTemporalReservoirFeatureBuffer[getPixelID(scrPosI, gResolution)];

                    bool isTapBackgroundReservoir = tapFeatures.transmittance == 1.f && tapFeatures.noReflectiveSurface;
                    if (isBackgroundReservoir && !isTapBackgroundReservoir)
                    {
                        if (gOutputMotionVec) gMotionVec[pixelPos] = (reprojScreenPos - pixelPos) / float2(gResolution);
                        return;
                    }
                }
            }

            {
                scrPosI = int2(scrPos);
                reprojScreenPos = scrPosI;

                if (IsWithinRange(scrPosI, gResolution))
                {
                    numUsedReservoirs++;
                    taps[1] = gTemporalReservoirs[getPixelID(scrPosI, gResolution)];
                }
            }

            if (numUsedReservoirs > 1) useFallbackReservoir = false;
        }

        if (useFallbackReservoir)
        {
            numUsedReservoirs++;
            reprojScreenPos = pixelPos;
            taps[1] = gTemporalReservoirs[pixelId];
        }

        if (gOutputMotionVec) gMotionVec[pixelPos] = (reprojScreenPos - pixelPos) / float2(gResolution);

        float curM = taps[0].M;
        float MaxPrevM = gTemporalHistoryThreshold * curM;

        // convert depths to current frame depths
        if (numUsedReservoirs == 2)
        {
            temporalOriginalDepth = taps[1].depth;
            if (taps[1].depth != kRayTMax)
            {
                int2 tapPos = reprojScreenPos;
                float3 worldPos = computeWorldPositionWithRayTracingFrameScaled(gScene.camera, tapPos, 1,
                                        0.5f, gResolution, gPrevCameraPosW, gPrevCameraU, gPrevCameraV, gPrevCameraW, taps[1].depth, gPrevJitter);

                taps[1].depth = length(worldPos - ray.origin);
            }
        }

        float centerPrevFrameDepth = taps[0].depth;
        if (centerPrevFrameDepth != kRayTMax)
        {
            float3 worldPos = ray.at(centerPrevFrameDepth);
            centerPrevFrameDepth = length(worldPos - gPrevCameraPosW);
        }
        //

        bool hasSelection = output.runningSum > 0.f;

        int startSampleId = gMISMethod == kMISTalbot ? 0 : 1;
        if (startSampleId == 1) selectedId = 0;

        for (int i = startSampleId; i < numUsedReservoirs; i++)
        {
            // if not using initial RIS, use Talbot in temporal causes noise
            float talbotMISWeight = 1.f;

            float neighbor_py = 0.f;

            if (taps[i].p_y > 0.f)
            {
                int2 resampleRayPixelPos = pixelPos;

                VolRay resampleRay = ray;

                neighbor_py = taps[i].p_y;

                if (isnan(taps[i].runningSum) || isinf(taps[i].runningSum)) taps[i].runningSum = 0.f;

                // don't need to resample self for talbot
                if (i > 0)
                {
                    #ifdef SURFACE_SCENE
                    VBufferItem vItem = gVBuffer[getPixelID(resampleRayPixelPos, gResolution)];
                    #endif
                    // tap's runningSum and p_y are overwritten!
                    // for vertex reuse: p_partial is also overwritten!
                    bool isValid = resampleNeighbor(taps[i], resampleRay, sg, envMapSampler, emissiveSampler, VBUFFERITEM tempDataProvider, SAMPLING_OPTIONS);
                    if (!isValid) continue;
                }
            }
            else
            {
                taps[i].p_y = 0.f;
                taps[i].runningSum = 0.f;
            }

            if (gMISMethod == kMISTalbot && taps[i].runningSum > 0.f)
            {
                float p_sum = 0;
                float p_qi = 0;
                float k = 0;
            
                for (int j = 0; j < numUsedReservoirs; j++)
                {
                    int2 tapPos2 = int2(j == 0 ? pixelPos.x : reprojScreenPos.x, j == 0 ? pixelPos.y : reprojScreenPos.y);
                    float correctedM = min(MaxPrevM, taps[j].M);
            
                    k += correctedM;

                    if (j == 0)
                    {
                        p_qi = taps[i].p_y; // already resampled at center pixel!
                        p_sum += taps[i].p_y * correctedM;
                    }
                    else if (i == j)
                    {
                        p_qi = neighbor_py; // this is the original p_y!
                        p_sum += neighbor_py * correctedM;
                    }
                    else
                    {
                        int2 neighborRayPixelPos = tapPos2;

                        CameraRay neighborCameraRay;
                        if (j == 0) neighborCameraRay = computeRayPinholeScaled(gScene.camera, tapPos2, 1, 0.5, gResolution);
                        else neighborCameraRay = computeRayPinholeWithRayTracingFrameScaled(gScene.camera, tapPos2, 1, 0.5, gResolution, gPrevCameraPosW, gPrevCameraU, gPrevCameraV, gPrevCameraW, gPrevJitter);
            
                        float usedDepth = j == 0 ? taps[i].depth : (i == 0 ? centerPrevFrameDepth : temporalOriginalDepth);
            
                        VolRay neighborRay = { neighborCameraRay.origin, neighborCameraRay.dir, 0, usedDepth };
                        SingleExternalVisibilityProvider externalVis;
                        externalVis.Initialize();

                        #ifdef SURFACE_SCENE
                        VBufferItem vItem;
                        if (j == 0) vItem = gVBuffer[getPixelID(neighborRayPixelPos, gResolution)];
                        else vItem = gTemporalVBuffer[getPixelID(neighborRayPixelPos, gResolution)];
                        #endif

                        float backupDepth = taps[i].depth;
                        taps[i].depth = usedDepth;
                        float p_y;

                        if (i == 0) p_y = evaluatePHatReadOnly(taps[i], neighborRay, sg, envMapSampler, emissiveSampler,
                            VBUFFERITEM curDataProvider, SAMPLING_OPTIONS, j > 0, true, false);
                        else p_y = evaluatePHatReadOnly(taps[i], neighborRay, sg, envMapSampler, emissiveSampler,
                            VBUFFERITEM tempDataProvider, SAMPLING_OPTIONS, j > 0, true, false);

                        taps[i].depth = backupDepth;
                        if (isinf(p_y) || isnan(p_y)) p_y = 0.f;
                        p_sum += p_y * correctedM;
                    }
                }
            
                if (p_sum > 0)
                    talbotMISWeight = p_qi * k / p_sum;
            }

            taps[i].runningSum *= float(talbotMISWeight);

            bool isCurrentSelected = simpleResampleStepWithMaxM(taps[i], MaxPrevM, output, sg);
            hasSelection |= isCurrentSelected;
            if (isCurrentSelected)
            {
                selectedId = i;
            }
        }

    #if MAX_BOUNCES > 1
        if (hasSelection && selectedId > 0)
        {
            // copy the extra bounce reservoirs
            int maxIndirectBounces = decodeMaxIndirectBounces(output.sampledPixel);

            for (int bounceId = 0; bounceId < maxIndirectBounces; bounceId++)
            {
                gCurExtraBounceReservoirs[centerExtraBounceStartId + bounceId] = gTemporalExtraBounceReservoirs[output.extraBounceStartId + bounceId];
            }
        }
        output.extraBounceStartId = centerExtraBounceStartId;
    #endif

        gCurReservoirs[pixelId] = output;

    }
}
