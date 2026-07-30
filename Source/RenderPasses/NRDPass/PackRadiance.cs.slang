/***************************************************************************
 # Copyright (c) 2015-23, NVIDIA CORPORATION. All rights reserved.
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
#define NRD_COMPILER_DXC
// v4 flattened the shader tree: NRD.hlsli sits beside the .cs.hlsl files rather than under
// Include/. NRD_V4 is supplied by NRDPass.cpp from FALCOR_HAS_NRD4.
#ifdef NRD_V4
#include "nrd/Shaders/NRD.hlsli"
#else
#include "nrd/Shaders/Include/NRD.hlsli"
#endif

import Utils.Color.ColorHelpers;

#ifndef NRD_METHOD
// NRD_METHOD must be defined in order to use this module.
#error "NRD_METHOD not defined!"
#endif

#define NRD_METHOD_RELAX_DIFFUSE_SPECULAR 0
#define NRD_METHOD_REBLUR_DIFFUSE_SPECULAR 1

cbuffer PerImageCB
{
#ifdef NRD_V4
    // v4's ReblurHitDistanceParameters is {A,B,C} -- the D term was removed along with the old
    // lerp(1,C,exp2(D*r^2)) normalization curve.
    float3 gHitDistParams;
#else
    float4 gHitDistParams;
#endif
    float gMaxIntensity;

    Texture2D<float> gViewZ;
    Texture2D<float4> gNormalRoughness;

    RWTexture2D<float4> gDiffuseRadianceHitDist;
    RWTexture2D<float4> gSpecularRadianceHitDist;
};

void clampRadiance(inout float3 diffuseRadiance, inout float3 specularRadiance)
{
    static const float kEpsilon = 1e-6f;

    float lDiff = luminance(diffuseRadiance);
    if (lDiff > kEpsilon)
    {
        diffuseRadiance *= min(gMaxIntensity / lDiff, 1.f);
    }

    float lSpec = luminance(specularRadiance);
    if (lSpec > kEpsilon)
    {
        specularRadiance *= min(gMaxIntensity / lSpec, 1.f);
    }
}

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId: SV_DispatchThreadID)
{
    int2 ipos = dispatchThreadId.xy;

    float4 diffuseRadianceHitDist = gDiffuseRadianceHitDist[ipos];
    float4 specularRadianceHitDist = gSpecularRadianceHitDist[ipos];

    clampRadiance(diffuseRadianceHitDist.rgb, specularRadianceHitDist.rgb);

#if NRD_METHOD == NRD_METHOD_RELAX_DIFFUSE_SPECULAR

    diffuseRadianceHitDist = RELAX_FrontEnd_PackRadianceAndHitDist(diffuseRadianceHitDist.rgb, diffuseRadianceHitDist.a, true);
    specularRadianceHitDist = RELAX_FrontEnd_PackRadianceAndHitDist(specularRadianceHitDist.rgb, specularRadianceHitDist.a, true);

#else // NRD_METHOD == NRD_METHOD_REBLUR_DIFFUSE_SPECULAR

    float viewZ = gViewZ[ipos];
    float linearRoughness = gNormalRoughness[ipos].z;

    diffuseRadianceHitDist.a = REBLUR_FrontEnd_GetNormHitDist(diffuseRadianceHitDist.a, viewZ, gHitDistParams, linearRoughness);
    specularRadianceHitDist.a = REBLUR_FrontEnd_GetNormHitDist(specularRadianceHitDist.a, viewZ, gHitDistParams, linearRoughness);
#ifdef NRD_V4
    diffuseRadianceHitDist = REBLUR_FrontEnd_PackRadianceAndNormHitDist(diffuseRadianceHitDist.rgb, diffuseRadianceHitDist.a, true);
    specularRadianceHitDist = REBLUR_FrontEnd_PackRadianceAndNormHitDist(specularRadianceHitDist.rgb, specularRadianceHitDist.a, true);
#else
    REBLUR_FrontEnd_PackRadianceAndHitDist(diffuseRadianceHitDist.rgb, diffuseRadianceHitDist.a);
    REBLUR_FrontEnd_PackRadianceAndHitDist(specularRadianceHitDist.rgb, specularRadianceHitDist.a);
#endif

#endif

    gDiffuseRadianceHitDist[ipos] = diffuseRadianceHitDist;
    gSpecularRadianceHitDist[ipos] = specularRadianceHitDist;
}
