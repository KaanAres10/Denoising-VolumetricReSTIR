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

void applyEstimatorCompilerFlags(ProgramDesc& desc, bool volumeOnlyScene)
{
    // PRECISE floating point for every Volumetric ReSTIR program. Falcor 9.0 ships Slang 2025.13.2,
    // whose DEFAULT floating-point mode emits fast-math DXIL: every float op in the largest kernel is
    // flagged `fast` and none is `dx.precise`. Slang 2024.1.34 (Falcor 8.0) emitted the same kernel
    // with 4,869 `dx.precise` markers and 9 fast ops -- effectively precise. Same source, same DXC.
    //
    // The estimator runs ~20% slower under Slang 2025's default (bistro orbit, raw, 1080p, interleaved
    // runs: 123.6 ms on 8.0 -> 149.5 ms on 9.0; Spatial Reuse 63.6 -> 85). Isolated three ways: the 8.0
    // engine with 8.0's own shaders slows to 9.0's speed when only slang.dll is swapped for 9.0's (old
    // gfx.dll kept); the two compilers' DXIL is otherwise within 0.7% in instructions and identical in
    // allocas; and this flag brings 9.0 to 123.2 ms, level with 8.0. PRECISE on Slang 2025 reproduces
    // Slang 2024's default almost exactly: 4,899 vs 4,869 dx.precise, the same 2,914 fused mads.
    // The volume-only path does not show it (it is slightly FASTER under fast math), which is what made
    // it look like a material problem rather than a compiler one.
    //
    // VR_FP_MODE=fast|default restores the other modes for an A/B.
    //
    // VR_FP_MODE_VOLUME=default|fast applies to VOLUME-ONLY scenes only (the programs built by
    // createSimpleComputePass; surface scenes rebuild every pass with createSceneComputePass and stay
    // precise). OPT-IN, off by default: it changes pixel values at the rounding level, so captures
    // are no longer byte-identical to the locked ones. Measured on bistro volume-only: default
    // 20.4 ms against precise 21.8 (-7%). The 4.x fork compiled everything fast-math. VR_FP_MODE,
    // when set, wins over it.
    static const std::string allMode = [] { const char* v = std::getenv("VR_FP_MODE"); return std::string(v ? v : ""); }();
    static const std::string volumeMode = [] { const char* v = std::getenv("VR_FP_MODE_VOLUME"); return std::string(v ? v : ""); }();
    const std::string mode = !allMode.empty() ? allMode : (volumeOnlyScene && !volumeMode.empty()) ? volumeMode : "precise";
    SlangCompilerFlags flags = SlangCompilerFlags::None;
    if (mode == "fast")
        flags = SlangCompilerFlags::FloatingPointModeFast;
    else if (mode != "default")
        flags = SlangCompilerFlags::FloatingPointModePrecise;

    // VR_DUMP_DXIL=1 writes each estimator program's intermediates (HLSL, DXIL, DXIL assembly) to the
    // working directory, for inspecting what the compiler hands the driver. Programs found in gfx's
    // .shadercache are not recompiled and dump nothing.
    static const bool dumpDxil = std::getenv("VR_DUMP_DXIL") != nullptr;
    if (dumpDxil)
        flags |= SlangCompilerFlags::DumpIntermediates;
    desc.setCompilerFlags(flags);

    // VR_SLANG_ARGS: extra Slang command-line arguments, space-separated, for an A/B of compiler
    // options. DXC options go through Slang's -Xdxc: "-Xdxc -disable-lifetime-markers" for one token,
    // "-Xdxc... -opt-disable licm -X." for several.
    static const std::vector<std::string> extraArgs = [] {
        std::vector<std::string> out;
        if (const char* v = std::getenv("VR_SLANG_ARGS"))
        {
            std::string s(v), tok;
            for (char c : s + " ")
            {
                if (c == ' ') { if (!tok.empty()) out.push_back(tok); tok.clear(); }
                else tok += c;
            }
        }
        return out;
    }();
    if (!extraArgs.empty())
        desc.addCompilerArguments(extraArgs);

    // VR_SHADER_MODEL=6_5 (or 6_6, ...) compiles the estimator programs for that shader model.
    static const std::string shaderModel = [] { const char* v = std::getenv("VR_SHADER_MODEL"); return std::string(v ? v : ""); }();
    if (shaderModel == "6_5")
        desc.setShaderModel(ShaderModel::SM6_5);
    else if (shaderModel == "6_6")
        desc.setShaderModel(ShaderModel::SM6_6);
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
    ProgramDesc desc;
    desc.addShaderLibrary(file).csEntry(mainEntry);
    applyEstimatorCompilerFlags(desc, /*volumeOnlyScene*/ true);
    return ComputePass::create(pDevice, desc, matlDefs, /*createVars*/ false);
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
    applyEstimatorCompilerFlags(desc);
    return ComputePass::create(pDevice, desc, matlDefs, /*createVars*/ false);
}
