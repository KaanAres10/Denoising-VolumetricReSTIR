/***************************************************************************
 # Copyright (c) 2019, NVIDIA CORPORATION.  All rights reserved.
 #
 # NVIDIA CORPORATION and its licensors retain all intellectual property
 # and proprietary rights in and to this software, related documentation
 # and any modifications thereto.  Any use, reproduction, disclosure or
 # distribution of this software and related documentation without an express
 # license agreement from NVIDIA CORPORATION is strictly prohibited.
 **************************************************************************/

#include "Utils.h"

using namespace Falcor;

////////////////////////////////////////////////////////////////////
// Convert from std::vector<> to Falcor vectors.
//    -> Useful for converting from pybind11 list values to Falcor vectors

float2 _toVec2(std::vector<float> pyVec, float2 def)
{
    if (pyVec.size() >= 2)
    {
        return float2(pyVec[0], pyVec[1]);
    }
    return def;
}

float3 _toVec3(std::vector<float> pyVec, float3 def)
{
    if (pyVec.size() >= 3)
    {
        return float3(pyVec[0], pyVec[1], pyVec[2]);
    }
    return def;
}

float4 _toVec4(std::vector<float> pyVec, float4 def)
{
    if (pyVec.size() >= 4)
    {
        return float4(pyVec[0], pyVec[1], pyVec[2], pyVec[3]);
    }
    return def;
}

ref<Sampler> createLinearSampler(ref<Device> pDevice)
{
    Sampler::Desc desc;
    desc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point)
        .setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
    return pDevice->createSampler(desc);
}

ref<Sampler> createNearestSampler(ref<Device> pDevice)
{
    Sampler::Desc desc;
    desc.setFilterMode(TextureFilteringMode::Point, TextureFilteringMode::Point, TextureFilteringMode::Point)
        .setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
    return pDevice->createSampler(desc);
}

ref<Texture> createNeighborOffsetTexture(ref<Device> pDevice, int numSamples)
{
    int R = 250;
    std::unique_ptr<int8_t[]> offsets(new int8_t[numSamples * 2]);
    const float phi2 = 1.0f / 1.3247179572447f;
    int num = 0;
    float u = 0.5f;
    float v = 0.5f;
    while (num < numSamples * 2) {
        u += phi2;
        v += phi2 * phi2;
        if (u >= 1.0f) u -= 1.0f;
        if (v >= 1.0f) v -= 1.0f;

        float rSq = (u - 0.5f)*(u - 0.5f) + (v - 0.5f)*(v - 0.5f);
        if (rSq > 0.25f)
            continue;

        offsets[num++] = int8_t((u - 0.5f)*R);
        offsets[num++] = int8_t((v - 0.5f)*R);
    }

    return pDevice->createTexture1D(numSamples, ResourceFormat::RG8Int, 1, 1, offsets.get());
}

ref<ComputePass> createSimpleComputePass(ref<Device> pDevice, const std::string& file, const std::string& mainEntry,
    DefineList defs)
{
    // To avoid not being able to compile compute shaders importing Scene.slang, make sure to define a MATERIAL_COUNT parameter.
    //   NOTE:  This just avoids the compile error on shader load, this parameter *still* needs to be set to the correct value when
    //   the scene is loaded (by calling updateSceneDefines()).
    DefineList matlDefs = { { "MATERIAL_COUNT", "1" }, {"PARTICLE_SYSTEM_COUNT", "1"}, {"INDEXED_VERTICES", "1"} };
    matlDefs.add(defs);
    matlDefs.add("_MS_DISABLE_ALPHA_TEST");

    // Defer program compilation/var creation until setScene() has supplied the real scene defines
    // (Scene.slang requires SCENE_GEOMETRY_TYPES etc. which are only known once a scene is loaded).
    return ComputePass::create(pDevice, file, mainEntry, matlDefs, /*createVars*/ false);
}

ref<ComputePass> createSceneComputePass(ref<Device> pDevice, const std::string& file, const std::string& mainEntry,
    DefineList defs, const ref<Scene>& pScene)
{
    // Same as createSimpleComputePass, but links the scene's shader modules + material type
    // conformances into the program. Required by the surface-scene path (mUseSurfaceScene), which
    // uses gScene.materials.getMaterialInstance() — Slang needs the concrete IMaterial/IMaterialInstance
    // implementations (e.g. StandardMaterial) present in the linkage.
    DefineList matlDefs = { { "MATERIAL_COUNT", "1" }, { "PARTICLE_SYSTEM_COUNT", "1" }, { "INDEXED_VERTICES", "1" } };
    matlDefs.add(defs);
    matlDefs.add("_MS_DISABLE_ALPHA_TEST");

    ProgramDesc desc;
    desc.addShaderModules(pScene->getShaderModules());
    desc.addShaderLibrary(file).csEntry(mainEntry);
    desc.addTypeConformances(pScene->getTypeConformances());
    return ComputePass::create(pDevice, desc, matlDefs, /*createVars*/ false);
}
