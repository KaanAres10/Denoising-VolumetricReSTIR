/***************************************************************************
 # Copyright (c) 2020, NVIDIA CORPORATION. All rights reserved.
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
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY
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

/** Path tracing pass.

    This file contains the entry points for all ray tracing programs.
    We import the path tracer utility functions defined in PathTracer.slang.

    The host sets the compile-time constants in StaticParams.slang.
    It also sets the following defines for optional I/O buffers:

    is_valid_<name> is 1 if buffer with this name is bound, 0 otherwise.
*/
import PathTracer;
import Utils.Timing.GpuTimer;
import RenderPasses.Shared.PathTracer.LoadShadingData;

ParameterBlock<PathTracerData> gData;

// Outputs (optional)
RWTexture2D<float4> gOutputColor;
RWTexture2D<float>  gOutputViewZ;
RWTexture2D<float4> gOutputAlbedo;
RWTexture2D<uint> gOutputTime;

// Static configuration based on which buffers are bound.
#define isValid(name) (is_valid_##name != 0)


/** ********************* Ray index 0: Scatter ray ************************ */

[shader("miss")]
void scatterMiss(inout ScatterRayData rayData : SV_RayPayload)
{
}

[shader("anyhit")]
void scatterAnyHit(
    uniform HitShaderParams hitParams,
    inout ScatterRayData rayData : SV_RayPayload, BuiltInTriangleIntersectionAttributes attribs : SV_IntersectionAttributes)
{
#if USE_ALPHA_TEST
    // Alpha test for non-opaque geometry.
    VertexData v = getVertexData(hitParams, PrimitiveIndex(), attribs);
    const uint materialID = gScene.getMaterialID(hitParams.getGlobalHitID());
    if (alphaTest(v, gScene.materials[materialID], gScene.materialResources[materialID], 0.f)) IgnoreHit();
#endif
}

[shader("closesthit")]
void scatterClosestHit(
    uniform HitShaderParams hitParams,
    inout ScatterRayData rayData : SV_RayPayload, BuiltInTriangleIntersectionAttributes attribs : SV_IntersectionAttributes)
{
    // Store hit information. Note we don't access the materials here.
    HitInfo hit;
    hit.meshInstanceID = hitParams.getGlobalHitID();
    hit.primitiveIndex = PrimitiveIndex();
    hit.barycentrics = attribs.barycentrics;
    rayData.packedHitInfo = hit.encode();
}

/************************** Ray index 1: Shadow ray ************************ */

[shader("miss")]
void shadowMiss(inout ShadowRayData rayData : SV_RayPayload)
{
    // The miss shader is executed if the ray misses all geometry. Mark as visible.
    rayData.visible = true;
}

[shader("anyhit")]
void shadowAnyHit(
    uniform HitShaderParams hitParams,
    inout ShadowRayData rayData : SV_RayPayload, BuiltInTriangleIntersectionAttributes attribs : SV_IntersectionAttributes)
{
#if USE_ALPHA_TEST
    // Alpha test for non-opaque geometry.
    VertexData v = getVertexData(hitParams, PrimitiveIndex(), attribs);
    const uint materialID = gScene.getMaterialID(hitParams.getGlobalHitID());
    if (alphaTest(v, gScene.materials[materialID], gScene.materialResources[materialID], 0.f)) IgnoreHit();
#endif
}

/** ******************************** RayGen ******************************** */

/** This is the entry point for the path tracer.

    We generate N paths (= #spp) per pixel, which are traced into the scene.
    The path tracer is written as a for-loop over path segments, where each
    iteration traces a shadow ray for direct illumination and a scatter ray.

    The hit shader for the scatter ray currently generates ray parameters for
    the shadow ray to evaluate direct illumination and generates ray parameters
    for the next scatter ray, which are both returned the raygen shader to be
    traced. This is more efficient than tracing from the hit shader. The max
    recusion depth = 1.
*/
[shader("raygeneration")]
void rayGen()
{
    uint2 launchIndex = DispatchRaysIndex().xy;
    uint2 launchDim = DispatchRaysDimensions().xy;

    logSetPixel(launchIndex);
    printSetPixel(launchIndex);

    GpuTimer timer;
    if (isValid(gOutputTime)) timer.start();

    float3 outColor = float3(0, 0, 0);
    float3 outAlbedo = float3(0, 0, 0);
    float outAlpha = 0.f; // This is Hit Distance for NRD
    float viewZ = 0.f;    // This is Linear View Z for NRD

    HitInfo hit;
    ShadingData sd;
    
    // --- LOAD G-BUFFER DATA ---
    if (loadShadingData(launchIndex, launchDim, gScene.camera, sd, hit))
    {
        // 1. Calculate Geometry for NRD
        // sd.posW = World Position of the primary hit
        // gScene.camera.data.posW = Camera World Position
        // gScene.camera.data.cameraW = Camera Forward Vector
        
        float3 toPixel = sd.posW - gScene.camera.data.posW;
        
        // A. Hit Distance (Euclidean)
        outAlpha = length(toPixel); 
        
        // B. Linear View Z (Projected onto forward axis)
        viewZ = dot(toPixel, gScene.camera.data.cameraW);

        // ... (Keep existing Ray Origin / Sample Loop code) ...
        const float3 rayOrigin = sd.computeNewRayOrigin();

        [loop]
        for (uint sampleIdx = 0; sampleIdx < kSamplesPerPixel; sampleIdx++)
        {
            // ... (Keep loop body exactly as is) ...
            // ... tracePath(...) call is here ...
            
            // Note: Keep the accumulation logic unchanged
            PathData path = {}; // ... setup path ...
            // ... trace ...
            
            outColor += gData.params.clampSamples && path.L > gData.params.clampThreshold ? gData.params.clampThreshold : path.L;
        }

        const float invSpp = 1.f / kSamplesPerPixel;
        outColor *= invSpp;
        outAlbedo = sd.diffuse + sd.specular;
    }
    else
    {
        // --- BACKGROUND HIT ---
        outColor = evalBackground(-sd.V);
        outAlbedo = outColor.rgb;
        
        // NRD requires specific "Sky" distance values to avoid denoising the sky
        outAlpha = 100000.0f; // Huge HitT
        viewZ = 100000.0f;    // Huge ViewZ
    }

    // DEBUG
    assert(!any(isnan(outColor)));

    // --- WRITE OUTPUTS ---
    
    // 1. Write Color + HitDistance (Alpha)
    if (isValid(gOutputColor)) gOutputColor[launchIndex] = float4(outColor, outAlpha);
    
    // 2. Write ViewZ (New)
    if (isValid(gOutputViewZ)) gOutputViewZ[launchIndex] = viewZ;
    
    // 3. Write Albedo (Existing)
    if (isValid(gOutputAlbedo)) gOutputAlbedo[launchIndex] = float4(outAlbedo, 1);

    // 4. Write Time (Existing)
    if (isValid(gOutputTime)) gOutputTime[launchIndex] = timer.getElapsed();
}