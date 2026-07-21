/***************************************************************************
 # Copyright (c) 2019, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
 # EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED.
 **************************************************************************/
#pragma once

// GVDB volume subsystem for the Volumetric ReSTIR port. This header defines the host-side
// GVDB grid representation and manager, ported from the Falcor 4.x fork's Scene.{h,cpp}.
// It intentionally references ONLY Falcor types (ref<Buffer>/ref<Texture>/ref<ParameterBlock>,
// float3/int3/float4x4, AABB) — the GVDB SDK header is included only in SceneGVDB.cpp.

#include "Core/Macros.h"
#include "Core/Object.h"
#include "Core/API/Buffer.h"
#include "Core/API/Texture.h"
#include "Core/API/ParameterBlock.h"
#include "Core/Program/ShaderVar.h"
#include "Scene/SceneTypes.slang"
#include "Utils/Math/AABB.h"
#include "Utils/Math/Vector.h"
#include "Utils/Math/Matrix.h"
#include <vector>

namespace Falcor
{
    class Device;

    /** Host-side representation of the (multi-mip) GVDB sparse voxel grids for one volume, and the
        book-keeping to bind them to the `gvdb` shader parameter block. Ported verbatim (types only
        adapted to Falcor 8.0 ref<>) from Scene::GVDBInfo in the Falcor 4.x fork.
    */
    struct GVDBInfo
    {
        static const int MAX_LEVELS = 3;
        static const int MAX_MIPS = 30;   // 2*kNumMaxMips reserved for temperature/emission, +1 velocity, +2 supervoxels, +3..+10 prev-frame mips, +11 prev temperature, +12 prev velocity
        static const int MAX_CHANNELS = 1;

        int      dim[MAX_LEVELS * MAX_MIPS];        // Log base 2 of lateral resolution of each node per level
        int      res[MAX_LEVELS * MAX_MIPS];        // Lateral resolution of each node per level
        float3   vdel[MAX_LEVELS * MAX_MIPS];       // How many voxels on a side a child of each level covers
        int3     noderange[MAX_LEVELS * MAX_MIPS];  // How many voxels on a side a node of each level covers
        int      nodecnt[MAX_LEVELS * MAX_MIPS];    // Total number of allocated nodes per level
        int      nodewid[MAX_LEVELS * MAX_MIPS];    // Size of a node at each level in bytes
        int      childwid[MAX_LEVELS * MAX_MIPS];   // Size of the child list per node at each level in bytes
        ref<Buffer> nodelist[MAX_LEVELS * MAX_MIPS];
        ref<Buffer> childlist[MAX_LEVELS * MAX_MIPS];
        int      top_lev[MAX_MIPS];                 // Top level (tree spans from voxels to level 0 to level top_lev)
        int      max_iter = 0;
        float    epsilon = 0.f;
        bool     update = false;
        uint32_t clr_chan = 0;
        float3   bmin[MAX_MIPS];                     // Inclusive minimum of AABB in voxels
        float3   bmax[MAX_MIPS];                     // Inclusive maximum of AABB in voxels
        ref<Texture> volIn[MAX_CHANNELS * MAX_MIPS]; // Read+interp atlas per channel
        ref<Texture> volIn_part2[MAX_CHANNELS * MAX_MIPS]; // For depth slices exceeding 2048
        ref<Texture> velocityIn[2];
        ref<Texture> velocityIn_part2[2];
        float    superVoxelWorldSpaceDiagonalLength = 0.f;
        int3     volInDimensions[MAX_CHANNELS * MAX_MIPS];
        int3     volInDimensions_part2[MAX_CHANNELS * MAX_MIPS];
        float3   invVolInDimensions[MAX_CHANNELS * MAX_MIPS];
        float3   invVolInDimensions_part2[MAX_CHANNELS * MAX_MIPS];
        float4x4 xform[MAX_MIPS];
        float4x4 invxform[MAX_MIPS];
        float4x4 invxrot[MAX_MIPS];
        float    maxValue[MAX_MIPS];
        float    invMaxValue[MAX_MIPS];
        float    densityCompressScaleFactor[MAX_MIPS];

        void bindParameterBlock(const ref<ParameterBlock>& block, int mipId);
        void bindPrevParameterBlock(const ref<ParameterBlock>& block, int mipId);
    };

    struct GVDBParamBlocks
    {
        ref<ParameterBlock> paramBlock;
        int  numMips = 1;
        bool hasEmissionGrid = false;   // the last grid is emission grid
        bool hasVelocityGrid = false;
    };

    struct VDBBuffers
    {
        int  numMips = 1;
        bool hasEmissionGrid = false;   // the last grid is emission grid
        std::vector<ref<Buffer>> kNodeLevel0s;
        std::vector<ref<Buffer>> kNodeLevel1s;
        std::vector<ref<Buffer>> kNodeLevel2s;
        std::vector<ref<Buffer>> kRootData_roots;
        std::vector<ref<Buffer>> kRootData_tiles;
        std::vector<ref<Buffer>> kGridDatas;
    };

    /** Owns all host-side GVDB volume state for a Scene. Held by Scene via a shared_ptr so the
        heavy state + the GVDB SDK dependency stay out of Scene.h ("thin Scene hooks").
    */
    class GVDBVolumeManager
    {
    public:
        GVDBVolumeManager(ref<Device> pDevice) : mpDevice(pDevice) {}

        /** Bind the (possibly animated) volume's `gvdb` parameter block + emission LUT to a shader var. */
        void setShaderData(const ShaderVar& var, int frameId);

        int getNumMips(int volumeId) const;
        bool empty() const { return mGVDBVolumes.empty(); }
        AABB getVolumeBB(int volumeId) const { return mVDBVolumeBBs[volumeId]; }

        // .vbx loaders (implemented in SceneGVDB.cpp under FALCOR_HAS_GVDB). Return volume index.
        uint32_t addVolume(VolumeDesc& volumeDesc, AABB& sceneVolumeBB, const ref<ParameterBlock>& sceneBlock, int curFrameId,
            float3 sigma_a, float3 sigma_s, float g, const std::string& vbxFile, int numMips, float densityScale, bool hasVelocityGrid,
            bool hasEmissionGrid, float LeScale, float temperatureCutOff, float temperatureScale, float3 worldTranslation,
            float3 worldRotation, float worldScaling);

        int mVDBLastAnimationFrameId = 0;
        int mVDBAnimationFrames = 0;

        std::vector<GVDBParamBlocks> mGVDBVolumes;
        std::vector<GVDBInfo> mGVDBInfos;
        std::vector<VDBBuffers> mVDBVolumes;
        std::vector<VolumeDesc> mVolumeDescArray;   // for animated volume sequence
        std::vector<AABB> mVDBVolumeBBs;

        std::vector<float4> mCPUBlackBodyRadiationTexture;
        ref<Texture> mpBlackBodyRadiationTexture;

        float3 mVolumeWorldTranslation = float3(0, 0, 0);
        float3 mVolumeWorldRotation = float3(0, 0, 0);
        float  mVolumeWorldScaling = 1.f;

    private:
        float4x4 computeVolumeExternalModelToWorldMatrix() const;

        // Loads a pre-baked GVDB volume (.bin produced by the GVDBBake tool) and uploads to GPU.
        // This is the path used at runtime (no gvdb.dll in the Falcor process).
        uint32_t addVolumeFromBaked(VolumeDesc& volumeDesc, AABB& sceneVolumeBB, const ref<ParameterBlock>& sceneBlock,
            const std::string& bakedPath, float3 sigma_a, float3 sigma_s, float g, float densityScale, float LeScale,
            float temperatureCutOff, float temperatureScale, float3 worldTranslation, float3 worldRotation, float worldScaling, int curFrameId);

        ref<Device> mpDevice;
    };
}
