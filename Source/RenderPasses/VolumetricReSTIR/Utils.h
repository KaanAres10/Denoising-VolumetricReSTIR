/***************************************************************************
 # Copyright (c) 2019, NVIDIA CORPORATION.  All rights reserved.
 #
 # NVIDIA CORPORATION and its licensors retain all intellectual property
 # and proprietary rights in and to this software, related documentation
 # and any modifications thereto.  Any use, reproduction, disclosure or
 # distribution of this software and related documentation without an express
 # license agreement from NVIDIA CORPORATION is strictly prohibited.
 **************************************************************************/

// A bunch of syntactic sugar and utilities Chris likes and has accumulated.
// Ported from Falcor 4.x to Falcor 8.0 (ref<T> + device factories).

#pragma once
#include "Falcor.h"
#include "Core/Pass/ComputePass.h"

using namespace Falcor;

//////////////////////////////////////////////////////////////////////////////////////////////////////////////
//   Small conversion helpers (kept for parity with the original module).
//////////////////////////////////////////////////////////////////////////////////////////////////////////////

/** Converts a std::vector<float> (e.g. from a Python list) to the appropriate Falcor vector type.
    If there's an error (e.g., the vector isn't long enough for the specified type), the default is returned.
*/
float2 _toVec2(std::vector<float> pyVec, float2 def = float2(0, 0));
float3 _toVec3(std::vector<float> pyVec, float3 def = float3(0, 0, 0));
float4 _toVec4(std::vector<float> pyVec, float4 def = float4(0, 0, 0, 0));

/** Helpers to create a new / unique linear or nearest neighbor sampler
*/
Falcor::ref<Falcor::Sampler> createLinearSampler(Falcor::ref<Falcor::Device> pDevice);
Falcor::ref<Falcor::Sampler> createNearestSampler(Falcor::ref<Falcor::Device> pDevice);

/** We create a texture with a specified number of entries.  Each entry is a low-discrepenency
    ("random") sample/offset within 1 unit around the origin (0,0).  The texture is RG8Int,
    rather than RG32Float (or other format) for compactness.  This is created WITHOUT mipmapping.
    \param[in] numSamples How many entries this neighbor offset texture should have
*/
Falcor::ref<Falcor::Texture> createNeighborOffsetTexture(Falcor::ref<Falcor::Device> pDevice, int numSamples = 8192);

/** Helper to create a simplistic/basic Falcor compute pass with minimal code.
*/
Falcor::ref<Falcor::ComputePass> createSimpleComputePass(Falcor::ref<Falcor::Device> pDevice, const std::string& file, const std::string& mainEntry, Falcor::DefineList defs = {});
Falcor::ref<Falcor::ComputePass> createSceneComputePass(Falcor::ref<Falcor::Device> pDevice, const std::string& file, const std::string& mainEntry, Falcor::DefineList defs, const Falcor::ref<Falcor::Scene>& pScene);

/** Maps the specified GPU buffer, reads back the data into the var[] array, reading
    a number of elements specified.  Note:  If this buffer was *not* created as a structure or
    typed buffer, this will likely fail.
*/
template <typename T>
void readbackBufferData(Falcor::ref<Falcor::Buffer> buf, T* var, uint32_t numElems)
{
    if (numElems > 0)
    {
        const T* bufPtr = reinterpret_cast<const T*>(buf->map());
        std::memcpy(var, bufPtr, sizeof(T) * numElems);
        buf->unmap();
    }
}
