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

// ---------------------------------------------------------------------------------------------
// Volumetric ReSTIR GVDB volume subsystem — separate translation unit implementing the thin
// Scene volume hooks (Scene.h) + the GVDBVolumeManager (SceneGVDB.h). Ported from the Falcor 4.x
// "Denoising-VolumetricReSTIR" fork. The heavy GVDB `.vbx` loading depends on the prebuilt GVDB
// SDK and is gated behind FALCOR_HAS_GVDB; when it is off the loaders are no-ops so the core
// engine and the VolumetricReSTIR render pass reach compile-clean.
// ---------------------------------------------------------------------------------------------

#include "Scene/Scene.h"
#include "Scene/GVDB/SceneGVDB.h"
#include "Utils/Image/BCHelper.h"
#include "Core/API/Device.h"
#include "Core/API/RenderContext.h"
#include "Core/AssetResolver.h"
#include "Core/Program/ShaderVar.h"
#include "Core/Program/Program.h"
#include "Core/Program/ProgramReflection.h"
#include "GlobalState.h"
#include "Utils/Logger.h"
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <cfloat>
#include <algorithm>

// The GVDB header does `using namespace nvdb;` at global scope and is only needed by this
// translation unit, so it is included here (isolated) rather than in Scene.h.
#if defined(FALCOR_HAS_GVDB) && FALCOR_HAS_GVDB
#include <gvdb_volume_gvdb.h>
#endif

namespace Falcor
{
    // Volume-grid layout constants, mirrored from RenderPasses/VolumetricReSTIR/HostDeviceSharedConstants.slang.
    // Defined locally so the core Scene does not depend on a render-pass header.
    static const int kNumMaxMips = 8;
    static const int kPrevFrameDensityGridOffset = 2 * kNumMaxMips + 3;
    static const int kPrevFrameExtraGridOffset = 11;

    // Diagnostic: dump the GVDBInfo/VolumeDesc values a volume ends up with, so the offline bake can
    // be validated numerically against the live gvdb.dll path (which is the fork's own code). Set
    // FALCOR_GVDB_DUMP=1 to enable; the two paths should produce byte-identical output.
    static void dumpGVDBDiag(const char* tag, const GVDBInfo& gi, const VolumeDesc& vd, int numMips)
    {
        static const bool enabled = []{ const char* e = std::getenv("FALCOR_GVDB_DUMP"); return e && e[0] == '1'; }();
        if (!enabled) return;

        std::printf("[gvdbdiag] ==== %s ====\n", tag);
        std::printf("[gvdbdiag] desc maxDensity=%.9g invMaxDensity=%.9g tStep=%.9g sigma_t=%.9g\n",
            vd.maxDensity, vd.invMaxDensity, vd.tStep, vd.sigma_t);
        std::printf("[gvdbdiag] desc gridRes=%u,%u,%u densScale=%.9g densScaleByScaling=%.9g numMips=%d\n",
            vd.gridRes.x, vd.gridRes.y, vd.gridRes.z, vd.densityScaleFactor, vd.densityScaleFactorByScaling, vd.numMips);
        for (int m = 0; m < numMips && m < kNumMaxMips; m++)
        {
            std::printf("[gvdbdiag] mip%d top_lev=%d maxValue=%.9g invMaxValue=%.9g volInDim=%d,%d,%d\n",
                m, gi.top_lev[m], gi.maxValue[m], gi.invMaxValue[m],
                gi.volInDimensions[m].x, gi.volInDimensions[m].y, gi.volInDimensions[m].z);
            std::printf("[gvdbdiag] mip%d bmin=%.9g,%.9g,%.9g bmax=%.9g,%.9g,%.9g\n",
                m, gi.bmin[m].x, gi.bmin[m].y, gi.bmin[m].z, gi.bmax[m].x, gi.bmax[m].y, gi.bmax[m].z);
            for (int n = 0; n < GVDBInfo::MAX_LEVELS; n++)
            {
                const int i = n + GVDBInfo::MAX_LEVELS * m;
                std::printf("[gvdbdiag] mip%d lev%d dim=%d res=%d cnt=%d nodewid=%d childwid=%d "
                            "vdel=%.9g,%.9g,%.9g range=%d,%d,%d\n",
                    m, n, gi.dim[i], gi.res[i], gi.nodecnt[i], gi.nodewid[i], gi.childwid[i],
                    gi.vdel[i].x, gi.vdel[i].y, gi.vdel[i].z,
                    gi.noderange[i].x, gi.noderange[i].y, gi.noderange[i].z);
            }
        }
        std::fflush(stdout);
    }

    // Resolve a data-relative path against the active asset search directories (replaces the
    // Falcor 4.x findFileInDataDirectories). Returns true and the absolute path if found.
    static bool resolveDataFile(const std::string& path, std::string& outFull)
    {
        std::filesystem::path resolved = getActiveAssetResolver().resolvePath(path);
        if (!resolved.empty() && std::filesystem::exists(resolved))
        {
            outFull = resolved.string();
            return true;
        }
        return false;
    }

    // -----------------------------------------------------------------------------------------
    // GVDBInfo — bind the host-side grid metadata + buffers/textures into the `gvdb` param block.
    // -----------------------------------------------------------------------------------------
    void GVDBInfo::bindParameterBlock(const ref<ParameterBlock>& pBlock, int mipId)
    {
        ShaderVar block = pBlock->getRootVar();
        for (int lev = 0; lev <= top_lev[mipId]; lev++)
        {
            block["dim"][lev + mipId * MAX_LEVELS] = dim[lev + mipId * MAX_LEVELS];
            block["res"][lev + mipId * MAX_LEVELS] = res[lev + mipId * MAX_LEVELS];
            block["vdel"][lev + mipId * MAX_LEVELS] = vdel[lev + mipId * MAX_LEVELS];
            block["noderange"][lev + mipId * MAX_LEVELS] = noderange[lev + mipId * MAX_LEVELS];
            block["nodecnt"][lev + mipId * MAX_LEVELS] = nodecnt[lev + mipId * MAX_LEVELS];
            block["nodewid"][lev + mipId * MAX_LEVELS] = nodewid[lev + mipId * MAX_LEVELS];
            block["childwid"][lev + mipId * MAX_LEVELS] = childwid[lev + mipId * MAX_LEVELS];
            block["nodelist"][lev + mipId * MAX_LEVELS] = nodelist[lev + mipId * MAX_LEVELS];
            if (lev > 0)
                block["childlist"][lev + mipId * MAX_LEVELS] = childlist[lev + mipId * MAX_LEVELS];
        }
        block["top_lev"][mipId] = top_lev[mipId];
        if (mipId == 0)
        {
            block["max_iter"] = max_iter;
            block["epsilon"] = epsilon;
            block["update"] = update;
            block["clr_chan"] = clr_chan;
            block["superVoxelWorldSpaceDiagonalLength"] = superVoxelWorldSpaceDiagonalLength;
        }
        block["bmin"][mipId] = bmin[mipId];
        block["bmax"][mipId] = bmax[mipId];
        if (mipId < 2 * kNumMaxMips + 1)
        {
            block["volIn"][mipId] = volIn[mipId];
            block["volIn_part2"][mipId] = volIn_part2[mipId];
        }
        else if (mipId == 2 * kNumMaxMips + 1)
        {
            int texId = 0;
            block["velocityIn"][texId] = velocityIn[0];
            block["velocityIn_part2"][texId] = velocityIn_part2[0];
        }

        block["volInDimensions"][mipId] = volInDimensions[mipId];
        block["volInDimensions_part2"][mipId] = volInDimensions_part2[mipId];
        block["invVolInDimensions"][mipId] = float3(1.f) / float3(volInDimensions[mipId]);
        block["invVolInDimensions_part2"][mipId] = float3(1.f) / float3(volInDimensions_part2[mipId]);
        block["xform"][mipId] = xform[mipId];
        block["invxform"][mipId] = invxform[mipId];
        block["invxrot"][mipId] = invxrot[mipId];
        block["maxValue"][mipId] = maxValue[mipId];
        block["invMaxValue"][mipId] = invMaxValue[mipId];
        block["densityCompressScaleFactor"][mipId] = densityCompressScaleFactor[mipId];
    }

    void GVDBInfo::bindPrevParameterBlock(const ref<ParameterBlock>& pBlock, int mipId)
    {
        ShaderVar block = pBlock->getRootVar();
        int storedMipId = mipId >= 2 * kNumMaxMips ? mipId + kPrevFrameExtraGridOffset : mipId + kPrevFrameDensityGridOffset;
        for (int lev = 0; lev <= top_lev[mipId]; lev++)
        {
            block["dim"][lev + storedMipId * MAX_LEVELS] = dim[lev + mipId * MAX_LEVELS];
            block["res"][lev + storedMipId * MAX_LEVELS] = res[lev + mipId * MAX_LEVELS];
            block["vdel"][lev + storedMipId * MAX_LEVELS] = vdel[lev + mipId * MAX_LEVELS];
            block["noderange"][lev + storedMipId * MAX_LEVELS] = noderange[lev + mipId * MAX_LEVELS];
            block["nodecnt"][lev + storedMipId * MAX_LEVELS] = nodecnt[lev + mipId * MAX_LEVELS];
            block["nodewid"][lev + storedMipId * MAX_LEVELS] = nodewid[lev + mipId * MAX_LEVELS];
            block["childwid"][lev + storedMipId * MAX_LEVELS] = childwid[lev + mipId * MAX_LEVELS];
            block["nodelist"][lev + storedMipId * MAX_LEVELS] = nodelist[lev + mipId * MAX_LEVELS];
            if (lev > 0)
                block["childlist"][lev + storedMipId * MAX_LEVELS] = childlist[lev + mipId * MAX_LEVELS];
        }
        block["top_lev"][storedMipId] = top_lev[mipId];
        block["bmin"][storedMipId] = bmin[mipId];
        block["bmax"][storedMipId] = bmax[mipId];

        if (mipId < 2 * kNumMaxMips + 1)
        {
            block["volIn"][storedMipId] = volIn[mipId];
            block["volIn_part2"][storedMipId] = volIn_part2[mipId];
        }
        else if (mipId == 2 * kNumMaxMips + 1)
        {
            int texId = 1;
            block["velocityIn"][texId] = velocityIn[0];
            block["velocityIn_part2"][texId] = velocityIn_part2[0];
        }

        block["volInDimensions"][storedMipId] = volInDimensions[mipId];
        block["volInDimensions_part2"][storedMipId] = volInDimensions_part2[mipId];
        block["invVolInDimensions"][storedMipId] = float3(1.f) / float3(volInDimensions[mipId]);
        block["invVolInDimensions_part2"][storedMipId] = float3(1.f) / float3(volInDimensions_part2[mipId]);
        block["xform"][storedMipId] = xform[mipId];
        block["invxform"][storedMipId] = invxform[mipId];
        block["invxrot"][storedMipId] = invxrot[mipId];
        block["maxValue"][storedMipId] = maxValue[mipId];
        block["invMaxValue"][storedMipId] = invMaxValue[mipId];
        block["densityCompressScaleFactor"][storedMipId] = densityCompressScaleFactor[mipId];
    }

    // -----------------------------------------------------------------------------------------
    // GVDBVolumeManager
    // -----------------------------------------------------------------------------------------
    void GVDBVolumeManager::setShaderData(const ShaderVar& var, int frameId)
    {
        var["gvdb"].setParameterBlock(mGVDBVolumes[frameId].paramBlock);

        if (mGVDBVolumes[frameId].hasEmissionGrid)
            var["gBlackBodyRadiationTex"] = mpBlackBodyRadiationTexture;

        mVDBLastAnimationFrameId = frameId;
    }

    int GVDBVolumeManager::getNumMips(int volumeId) const
    {
        return mGVDBVolumes[volumeId].numMips;
    }

    float4x4 GVDBVolumeManager::computeVolumeExternalModelToWorldMatrix() const
    {
        float4x4 m = math::matrixFromTranslation(mVolumeWorldTranslation);
        m = math::mul(m, math::matrixFromRotationX(math::radians(mVolumeWorldRotation.x)));
        m = math::mul(m, math::matrixFromRotationY(math::radians(mVolumeWorldRotation.y)));
        m = math::mul(m, math::matrixFromRotationZ(math::radians(mVolumeWorldRotation.z)));
        m = math::mul(m, math::matrixFromScaling(float3(mVolumeWorldScaling)));
        return m;
    }

    void GVDBVolumeManager::ensureBlackBodyLUT()
    {
        if (mpBlackBodyRadiationTexture) return;
        // 128 RGB rows, 50 K .. 6400 K, from PBRT (data/LUT). A missing file used to go unnoticed: the
        // reads failed silently and emission came out black or garbage.
        std::string lutPath;
        // data/ (repo root) is deployed next to the executable by copy_data_folder; the asset resolver
        // only searches media/, so look there too.
        const std::filesystem::path deployed = getRuntimeDirectory() / "data" / "LUT" / "BlackBodyRadiationRGB_50K-6400K.txt";
        if (std::filesystem::exists(deployed))
            lutPath = deployed.string();
        else if (!resolveDataFile("LUT/BlackBodyRadiationRGB_50K-6400K.txt", lutPath))
        {
            logError("GVDB: blackbody LUT 'LUT/BlackBodyRadiationRGB_50K-6400K.txt' not found; volume emission will be black.");
            return;
        }
        std::ifstream f(lutPath);
        mCPUBlackBodyRadiationTexture.clear();
        for (int i = 0; i < 128; i++)
        {
            float r = 0.f, gg = 0.f, b = 0.f;
            if (!(f >> r >> gg >> b))
            {
                logError("GVDB: blackbody LUT '{}' has fewer than 128 rows; volume emission will be wrong.", lutPath);
                break;
            }
            mCPUBlackBodyRadiationTexture.push_back(float4(r, gg, b, 0));
        }
        mCPUBlackBodyRadiationTexture.resize(128, float4(0.f));
        mpBlackBodyRadiationTexture = mpDevice->createTexture1D(128, ResourceFormat::RGBA32Float, 1, 1, mCPUBlackBodyRadiationTexture.data());
    }

    uint32_t GVDBVolumeManager::addVolume(VolumeDesc& volumeDesc, AABB& sceneVolumeBB, const ref<ParameterBlock>& sceneBlock, int curFrameId,
        float3 sigma_a, float3 sigma_s, float g, const std::string& vbxFile, int numMips, float densityScale, bool hasVelocityGrid,
        bool hasEmissionGrid, float LeScale, float temperatureCutOff, float temperatureScale, float3 worldTranslation,
        float3 worldRotation, float worldScaling)
    {
        // Load .vbx in-process through gvdb.dll, exactly as the Falcor 4.x fork did
        // (its Scene::addGVDBVolume -> gvdb.LoadVBX). No prebake stage; the fork had none.
        //
        // This used to prefer a "<vbxFile>.bin" produced by the GVDBBake tool, on the stated grounds
        // that gvdb.dll could not be loaded in the Falcor process because its OpenVDB is
        // ABI-incompatible with Falcor's. That does not hold for the gvdb.dll we actually link:
        // there are two different builds in this tree, and they are not interchangeable.
        //
        //   legacy/GVDBConverter/gvdb.dll          1,670,144 B  imports openvdb, tbb, blosc, Half, ...
        //   build/.../bin/Release/gvdb.dll         1,481,728 B  imports only OpenGL, CUDA, CRT
        //
        // Falcor.dll has a load-time import of the second one (`dumpbin /dependents` lists both
        // gvdb.dll and openvdb.dll), so GVDB is already resident in this process and always has been.
        // Reading .vbx never needed OpenVDB -- only LoadVDB() does, and that stays in the separate
        // gImportVDB process, exactly as in the fork.
#if defined(FALCOR_HAS_GVDB) && FALCOR_HAS_GVDB
        // Ported from the Falcor 4.x fork Scene::addGVDBVolume, including its BC4 density atlas
        // (ATLAS_COMPRESSION == 2, via BCHelper).
        const auto kBufFlags = ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess;

        if (curFrameId <= 0) // non-animated uses curFrameId == -1
        {
            mVolumeWorldTranslation = worldTranslation;
            mVolumeWorldScaling = worldScaling;
            mVolumeWorldRotation = worldRotation;
        }

        ref<Program> pProgram = Program::createCompute(mpDevice, "Scene/GVDBParameterBlock.slang", "main");
        ref<const ParameterBlockReflection> pReflection = pProgram->getReflector()->getParameterBlock("gVDBInfo");
        FALCOR_ASSERT(pReflection);

        GVDBParamBlocks gvdbParamBlocks;

        std::string filenameWithoutPath = vbxFile;
        const size_t last_slash_idx = filenameWithoutPath.find_last_of("\\/");
        if (std::string::npos != last_slash_idx) filenameWithoutPath.erase(0, last_slash_idx + 1);

        int mipId = 0;
        ref<ParameterBlock> gvdbBlock = ParameterBlock::create(mpDevice, pReflection);
        // Value-initialized: only levels below top_lev are filled in, so without this the unused
        // levels ship uninitialized stack garbage to the GPU. Harmless in practice (nodecnt==0 and
        // top_lev gate the traversal, so those entries are never read) but it made the live path's
        // vdel/noderange differ from the baked path's, which memsets its whole blob -- and that
        // difference is exactly what FALCOR_GVDB_DUMP exists to rule out. Not memset: GVDBInfo holds
        // ref<Buffer>/ref<Texture> members, so {} is the only safe way to zero the POD arrays.
        GVDBInfo gvdbInfo{};

        FALCOR_ASSERT(numMips <= kNumMaxMips);

        gvdbParamBlocks.numMips = numMips;
        gvdbParamBlocks.hasEmissionGrid = false;

        std::string temperatureFilename = vbxFile + "/" + filenameWithoutPath + "_temperature.vbx";
        std::string temperaturefullpath;
        if (!resolveDataFile(temperatureFilename, temperaturefullpath)) hasEmissionGrid = false;

        for (mipId = 0; mipId < numMips; mipId++)
        {
            std::string filename = vbxFile;
            int numTypes = mipId >= 2 * kNumMaxMips ? 1 : 2;

            for (int typeId = 0; typeId < numTypes; typeId++)
            {
                if (numMips > 1 && mipId < 2 * kNumMaxMips)
                    filename = vbxFile + "/" + filenameWithoutPath + "_mip" + std::to_string(mipId) + (typeId == 0 ? "" : "c") + ".vbx";
                else if (mipId == 2 * kNumMaxMips)
                    filename = vbxFile + "/" + filenameWithoutPath + "_temperature.vbx";
                else if (mipId == 2 * kNumMaxMips + 1)
                    filename = vbxFile + "/" + filenameWithoutPath + "_velocity_x.vbx";
                else if (mipId == 2 * kNumMaxMips + 2)
                    FALCOR_THROW("GVDB: Supervoxel already disabled!");

                std::string fullpath;
                if (!resolveDataFile(filename, fullpath))
                {
                    if (mipId == 2 * kNumMaxMips) { gvdbParamBlocks.hasEmissionGrid = false; continue; }
                    else if (mipId == 2 * kNumMaxMips + 1) { gvdbParamBlocks.hasVelocityGrid = false; break; }
                    else
                    {
                        bool shouldSkip = false;
                        if (typeId == 1)
                        {
                            logWarning("GVDB: No conservative grid detected for '{}'", filename);
                            numTypes = 1;
                            if (mipId == numMips - 1) shouldSkip = true;
                        }
                        else { gvdbParamBlocks.numMips = mipId; shouldSkip = true; }

                        if (shouldSkip)
                        {
                            if (hasEmissionGrid) { numMips = 2 * kNumMaxMips + 1; mipId = 2 * kNumMaxMips - 1; }
                            else if (hasVelocityGrid) { numMips = 2 * kNumMaxMips + 2; mipId = 2 * kNumMaxMips; }
                        }
                        continue;
                    }
                }

                if (mipId == 0) logInfo("GVDB loading '{}'", filename);

                if (mipId == 2 * kNumMaxMips)
                {
                    gvdbParamBlocks.hasEmissionGrid = true;
                    ensureBlackBodyLUT();
                }

                if (mipId == 2 * kNumMaxMips + 1) gvdbParamBlocks.hasVelocityGrid = true;

                VolumeGVDB gvdb;
                gvdb.Initialize(true);
                gvdb.LoadVBX(fullpath, true);

                int slotId = mipId;
                if (typeId == 1) slotId += kNumMaxMips;

                int levs = gvdb.mPool->getNumLevels();

                struct NewVDBNode { int3 mPackedPosValue; uint32_t mChildList; float4 mDensityBounds; };
                std::vector<std::vector<NewVDBNode>> newNodePool;

                for (int n = 0; n <= levs - 1; n++)
                {
                    gvdbInfo.nodecnt[n + GVDBInfo::MAX_LEVELS * slotId] = static_cast<int>(gvdb.mPool->getPoolTotalCnt(0, n));
                    if (gvdbInfo.nodecnt[n + GVDBInfo::MAX_LEVELS * slotId] == 0) continue;
                    gvdbInfo.dim[n + GVDBInfo::MAX_LEVELS * slotId] = gvdb.getLD(n);
                    gvdbInfo.res[n + GVDBInfo::MAX_LEVELS * slotId] = gvdb.getRes(n);
                    nvdb::Vector3DI range = gvdb.getRange(n);
                    nvdb::Vector3DI res3DI = gvdb.getRes3DI(n);
                    gvdbInfo.vdel[n + GVDBInfo::MAX_LEVELS * slotId] = float3((float)range.x, (float)range.y, (float)range.z);
                    gvdbInfo.vdel[n + GVDBInfo::MAX_LEVELS * slotId] /= float3((float)res3DI.x, (float)res3DI.y, (float)res3DI.z);
                    gvdbInfo.noderange[n + GVDBInfo::MAX_LEVELS * slotId] = int3(range.x, range.y, range.z);
                    gvdbInfo.nodewid[n + GVDBInfo::MAX_LEVELS * slotId] = static_cast<int>(gvdb.mPool->getPoolWidth(0, n));
                    gvdbInfo.childwid[n + GVDBInfo::MAX_LEVELS * slotId] = static_cast<int>(gvdb.mPool->getPoolWidth(1, n));
                    FALCOR_ASSERT(gvdb.mPool->getPoolWidth(0, n) % 64 == 0);

                    struct OldVDBNode
                    {
                        uint32_t mPackedLevFlagPriority;
                        int3 mPos; int3 mValue; float3 mVRange;
                        uint2 mParent; uint2 mChildList; uint2 mMask;
                    };

                    FALCOR_ASSERT(gvdbInfo.nodewid[n + GVDBInfo::MAX_LEVELS * slotId] == 64);
                    int oldPoolWidth = 64;
                    int newPoolWidth = 32;
                    int numElements = gvdb.mPool->getPoolTotalCnt(0, n);
                    char* nodePoolPtr = gvdb.mPool->getPoolCPU(0, n);

                    if (slotId == 0) volumeDesc.maxDensity = gvdb.mGridValMax;

                    newNodePool.push_back(std::vector<NewVDBNode>(numElements));

                    std::string nodeCacheFilename = std::filesystem::path(fullpath).parent_path().string() + "/" +
                        std::filesystem::path(fullpath).stem().string() + "_level" + std::to_string(n) + "nodes.bin";

                    if (std::filesystem::exists(nodeCacheFilename))
                    {
                        FILE* f = fopen(nodeCacheFilename.c_str(), "rb");
                        fread(newNodePool.back().data(), newPoolWidth, gvdb.mPool->getPoolTotalCnt(0, n), f);
                        fclose(f);
                    }
                    else
                    {
                        for (int i = 0; i < numElements; i++)
                        {
                            OldVDBNode oldnode; NewVDBNode newnode;
                            memcpy(&oldnode, nodePoolPtr + oldPoolWidth * i, oldPoolWidth);

                            newnode.mPackedPosValue.x = (oldnode.mPos.x & 0xFFFF) | (oldnode.mPos.y << 16);
                            newnode.mPackedPosValue.y = (oldnode.mPos.z & 0xFFFF) | (oldnode.mValue.x << 16);
                            newnode.mPackedPosValue.z = (oldnode.mValue.y & 0xFFFF) | (oldnode.mValue.z << 16);

                            uint2 listid = oldnode.mChildList;
                            if (listid.x == 0xFFFFFFFF)
                            {
                                newnode.mChildList = 0xFFFFFFFF;
                                int3 vMin = oldnode.mPos;
                                float sum = 0, sum2 = 0;
                                float minDensity = FLT_MAX, maxDensity = 0.f;
                                for (int ii = -1; ii <= 8; ii++)
                                    for (int jj = -1; jj <= 8; jj++)
                                        for (int kk = -1; kk <= 8; kk++)
                                        {
                                            float density = 0.f; int tcX, tcY, tcZ;
                                            if (vMin.x + ii < gvdb.mEffectiveVoxMin.x || vMin.x + ii > gvdb.mEffectiveVoxMax.x - 1 ||
                                                vMin.y + jj < gvdb.mEffectiveVoxMin.y || vMin.y + jj > gvdb.mEffectiveVoxMax.y - 1 ||
                                                vMin.z + kk < gvdb.mEffectiveVoxMin.z || vMin.z + kk > gvdb.mEffectiveVoxMax.z - 1)
                                                density = 0.f;
                                            else
                                                density = gvdb.getValueWithTexCoordFromRoot(nvdb::Vector3DF(vMin.x + ii + 0.5f, vMin.y + jj + 0.5f, vMin.z + kk + 0.5f), gvdb.mPool->getAtlasCPU(0), tcX, tcY, tcZ);
                                            minDensity = std::min(minDensity, density);
                                            maxDensity = std::max(maxDensity, density);
                                            sum += density; sum2 += density * density;
                                        }
                                float avgDensity = sum / 512.f;
                                newnode.mDensityBounds = float4(minDensity, maxDensity, avgDensity, 0.f);
                            }
                            else
                            {
                                int cndx = ((listid.y & 0xFFFF) << 16) | ((listid.x >> 16) & 0xFFFF);
                                newnode.mChildList = cndx;
                            }
                            newNodePool.back()[i] = newnode;
                        }
                        FILE* nodeCacheFile = fopen(nodeCacheFilename.c_str(), "wb");
                        if (nodeCacheFile) { fwrite(newNodePool.back().data(), newPoolWidth, gvdb.mPool->getPoolTotalCnt(0, n), nodeCacheFile); fclose(nodeCacheFile); }
                    }

                    gvdbInfo.nodewid[n + GVDBInfo::MAX_LEVELS * slotId] = newPoolWidth;
                    gvdbInfo.nodelist[n + GVDBInfo::MAX_LEVELS * slotId] = mpDevice->createStructuredBuffer(newPoolWidth,
                        gvdb.mPool->getPoolTotalCnt(0, n), kBufFlags, MemoryType::DeviceLocal, newNodePool.back().data(), false);
                    gvdbInfo.nodelist[n + GVDBInfo::MAX_LEVELS * slotId]->setName("nodelist" + std::to_string(n));

                    if (n > 0)
                    {
                        int numChildElements = gvdb.mPool->getPoolSize(1, n) / 8;
                        char* childPoolPtr = gvdb.mPool->getPoolCPU(1, n);
                        std::vector<uint32_t> newChildPool(numChildElements);
                        for (int i = 0; i < numChildElements; i++)
                        {
                            uint2 oldElement; memcpy(&oldElement.x, childPoolPtr + 8 * i, 8);
                            newChildPool[i] = ((oldElement.y & 0xFFFF) << 16) | ((oldElement.x >> 16) & 0xFFFF);
                        }
                        gvdbInfo.childwid[n + GVDBInfo::MAX_LEVELS * slotId] /= 2;
                        gvdbInfo.childlist[n + GVDBInfo::MAX_LEVELS * slotId] = mpDevice->createBuffer(gvdb.mPool->getPoolSize(1, n) / 2,
                            kBufFlags, MemoryType::DeviceLocal, newChildPool.data());
                        gvdbInfo.childlist[n + GVDBInfo::MAX_LEVELS * slotId]->setName("childList" + std::to_string(n));
                    }
                    if (gvdbInfo.nodecnt[n + GVDBInfo::MAX_LEVELS * slotId] == 1) gvdbInfo.top_lev[slotId] = n;
                }

                gvdbInfo.densityCompressScaleFactor[slotId] = 1.f;

                nvdb::Matrix4F xform = gvdb.mVDBXform;
                nvdb::Matrix4F invXform = gvdb.mVDBXformInv;
                nvdb::Matrix4F invRot = invXform;
                invRot(3, 0) = 0; invRot(3, 1) = 0; invRot(3, 2) = 0;
                memcpy((void*)&gvdbInfo.xform[slotId], &xform, sizeof(float) * 16);
                memcpy((void*)&gvdbInfo.invxform[slotId], &invXform, sizeof(float) * 16);
                memcpy((void*)&gvdbInfo.invxrot[slotId], &invRot, sizeof(float) * 16);

                if (slotId == 0)
                {
                    gvdbInfo.epsilon = gvdb.getEpsilon();
                    gvdbInfo.max_iter = gvdb.getMaxIter();
                    gvdbInfo.superVoxelWorldSpaceDiagonalLength = 8.f * sqrt(
                        dot(gvdbInfo.xform[slotId][0].xyz(), gvdbInfo.xform[slotId][0].xyz()) +
                        dot(gvdbInfo.xform[slotId][1].xyz(), gvdbInfo.xform[slotId][1].xyz()) +
                        dot(gvdbInfo.xform[slotId][2].xyz(), gvdbInfo.xform[slotId][2].xyz()));
                }
                if (gvdb.mIsCustomVersion)
                {
                    gvdbInfo.bmin[slotId] = float3((float)gvdb.mEffectiveVoxMin.x, (float)gvdb.mEffectiveVoxMin.y, (float)gvdb.mEffectiveVoxMin.z);
                    gvdbInfo.bmax[slotId] = float3((float)gvdb.mEffectiveVoxMax.x, (float)gvdb.mEffectiveVoxMax.y, (float)gvdb.mEffectiveVoxMax.z);
                    gvdbInfo.maxValue[slotId] = gvdb.mGridValMax;
                    gvdbInfo.invMaxValue[slotId] = 1.f / gvdbInfo.maxValue[slotId];
                }
                else
                {
                    gvdbInfo.bmin[slotId] = float3((float)gvdb.mObjMin.x, (float)gvdb.mObjMin.y, (float)gvdb.mObjMin.z);
                    gvdbInfo.bmax[slotId] = float3((float)gvdb.mObjMax.x, (float)gvdb.mObjMax.y, (float)gvdb.mObjMax.z);
                }

                gvdbInfo.clr_chan = 0xFFFFFFFF;

                if (gvdb.mPool->getNumAtlas() == 0)
                {
                    logError("GVDB: No atlas created for '{}'", filename);
                }
                else
                {
                    std::vector<float3> velocities; // supervoxel abuse
                    if (mipId == 2 * kNumMaxMips + 1)
                    {
                        std::string fullpath_y, fullpath_z;
                        resolveDataFile(vbxFile + "/" + filenameWithoutPath + "_velocity_y.vbx", fullpath_y);
                        resolveDataFile(vbxFile + "/" + filenameWithoutPath + "_velocity_z.vbx", fullpath_z);
                        VolumeGVDB gvdb_y; gvdb_y.Initialize(true); gvdb_y.LoadVBX(fullpath_y, true);
                        VolumeGVDB gvdb_z; gvdb_z.Initialize(true); gvdb_z.LoadVBX(fullpath_z, true);
                        float* vx = gvdb.mPool->getAtlasCPU(0);
                        float* vy = gvdb_y.mPool->getAtlasCPU(0);
                        float* vz = gvdb_z.mPool->getAtlasCPU(0);
                        int numTexels = gvdb.mPool->getAtlasRes(0).x * gvdb.mPool->getAtlasRes(0).y * gvdb.mPool->getAtlasRes(0).z;
                        velocities.resize(numTexels);
                        for (int i = 0; i < numTexels; i++) velocities[i] = float3(vx[i], vy[i], vz[i]);
                    }

                    FALCOR_ASSERT(gvdb.mPool->getAtlasRes(0).z <= 4096);

                    int brickRes = gvdb.mPool->getAtlasBrickres(0);
                    int atlasDepth = gvdb.mPool->getAtlasRes(0).z;
                    int atlasWidth = gvdb.mPool->getAtlasRes(0).x;
                    int atlasHeight = gvdb.mPool->getAtlasRes(0).y;
                    int part1Depth = atlasDepth > 2048 ? 2048 / brickRes * brickRes : atlasDepth;
                    int part2Depth = atlasDepth - part1Depth;

                    int numAtlasElements = atlasHeight * atlasWidth * atlasDepth;
                    std::vector<float> clampedDensity(numAtlasElements);
                    for (int i = 0; i < numAtlasElements; i++)
                        clampedDensity[i] = gvdb.mPool->getAtlasCPU(0)[i] / gvdb.mGridValMax < 1e-9 ? 0 : gvdb.mPool->getAtlasCPU(0)[i];

                    // Density atlas compression, restored from the 4.x fork (ATLAS_COMPRESSION == 1).
                    //
                    // The port allocated every atlas as R32Float -- 4 bytes per voxel against the fork's 1 -- so
                    // every density fetch moved 4x the bytes. The volume march is the inner loop of Generate
                    // Samples, Temporal Reuse, Spatial Reuse and Final Shading alike, which is why the port
                    // measured ~15 ms/frame slower on bistro with the cost spread across passes, not in one.
                    //
                    // The shader already expects this: getValueAtlasCoord() multiplies by
                    // gvdb.densityCompressScaleFactor[mip], which the port had pinned to 1.0.
                    // ATLAS_COMPRESSION == 2 in the 4.x fork: BC4, 4 bits/voxel against R8Unorm's 8 and
                    // R32Float's 32. Transparent to the shaders -- BC4 is hardware-decompressed with
                    // hardware trilinear filtering, and getValueAtlasCoord already multiplies by
                    // densityCompressScaleFactor.
                    //
                    // The conservative family passes isConservative=true, which rounds toward the endpoint
                    // that does not underestimate, so a conservative grid compressed this way still bounds
                    // the true density from above -- which is what the ratio/residual trackers rely on.
                    //
                    // BC4 works on 4x4 blocks, so the texture is allocated at dimensions rounded up to a
                    // multiple of 4 and volInDimensions records the PADDED size: the shader divides atlas
                    // coordinates by it to get UVs, and the texture really is that wide.
                    const bool useTextureCompression = (mipId > 0 && mipId < (int)kNumMaxMips) || (mipId == 0 && typeId == 1);
                    const int atlasWidthPadded = (atlasWidth + 3) / 4 * 4;
                    const int atlasHeightPadded = (atlasHeight + 3) / 4 * 4;
                    std::vector<uint8_t> compressedDensity, compressedDensityPart2;
                    if (useTextureCompression && gvdb.mGridValMax > 0.f)
                    {
                        gvdbInfo.densityCompressScaleFactor[slotId] = gvdb.mGridValMax;
                        BCHelper::CompressImage(clampedDensity.data(), int3(atlasWidth, atlasHeight, part1Depth),
                                                gvdb.mGridValMax, typeId == 1, compressedDensity);
                        if (atlasDepth > 2048 && part2Depth > 0)
                        {
                            BCHelper::CompressImage(clampedDensity.data() + (size_t)atlasWidth * atlasHeight * part1Depth,
                                                    int3(atlasWidth, atlasHeight, part2Depth),
                                                    gvdb.mGridValMax, typeId == 1, compressedDensityPart2);
                        }
                    }
                    const bool atlasCompressed = !compressedDensity.empty();
                    // D3D12 caps a Texture3D at 2048 per axis and this loader only ever splits the
                    // atlas in two, so the addressable depth is 2 * 2048. Past that, texture creation
                    // fails with a bare E_INVALIDARG that reads like a driver fault. Say what it is.
                    if (part2Depth > 2048)
                    {
                        logWarning("GVDB slot {}: atlas is {}x{}x{}, and the two-part split gives "
                                   "part1={} + part2={} -- part2 exceeds the 2048 Texture3D limit, so "
                                   "this volume cannot be uploaded. The atlas is only {} bricks wide; "
                                   "re-importing with more bricks per axis (gImportVDB's "
                                   "SetChannelDefault) trades depth for width and brings it back "
                                   "under the cap.",
                                   slotId, atlasWidth, atlasHeight, atlasDepth, part1Depth, part2Depth,
                                   atlasWidth / 10);
                    }
                    if (mipId < 2 * kNumMaxMips + 1)
                    {
                        gvdbInfo.volIn[slotId] = atlasCompressed
                            ? mpDevice->createTexture3D(atlasWidthPadded, atlasHeightPadded, part1Depth, ResourceFormat::BC4Unorm, 1, compressedDensity.data(), ResourceBindFlags::ShaderResource)
                            : mpDevice->createTexture3D(atlasWidth, atlasHeight, part1Depth, ResourceFormat::R32Float, 1, clampedDensity.data(), ResourceBindFlags::ShaderResource);
                        gvdbInfo.volIn[slotId]->setName("volIn");
                    }
                    else if (mipId == 2 * kNumMaxMips + 1)
                    {
                        gvdbInfo.velocityIn[0] = mpDevice->createTexture3D(atlasWidth, atlasHeight, part1Depth, ResourceFormat::RGB32Float, 1, velocities.data(), ResourceBindFlags::ShaderResource);
                    }

                    gvdbInfo.volInDimensions[slotId] = atlasCompressed
                        ? int3(atlasWidthPadded, atlasHeightPadded, part1Depth)
                        : int3(atlasWidth, atlasHeight, part1Depth);

                    if (atlasDepth > 2048)
                    {
                        if (mipId != 2 * kNumMaxMips + 1)
                        {
                            gvdbInfo.volIn_part2[slotId] = atlasCompressed
                                ? mpDevice->createTexture3D(atlasWidthPadded, atlasHeightPadded, part2Depth, ResourceFormat::BC4Unorm, 1, compressedDensityPart2.data(), ResourceBindFlags::ShaderResource)
                                : mpDevice->createTexture3D(atlasWidth, atlasHeight, part2Depth, ResourceFormat::R32Float, 1, clampedDensity.data() + atlasWidth * atlasHeight * part1Depth, ResourceBindFlags::ShaderResource);
                            gvdbInfo.volIn_part2[slotId]->setName("volIn_part2");
                        }
                        else
                        {
                            gvdbInfo.velocityIn_part2[0] = mpDevice->createTexture3D(atlasWidth, atlasHeight, part2Depth, ResourceFormat::RGB32Float, 1, velocities.data() + atlasWidth * atlasHeight * part1Depth, ResourceBindFlags::ShaderResource);
                        }
                        gvdbInfo.volInDimensions_part2[slotId] = atlasCompressed
                            ? int3(atlasWidthPadded, atlasHeightPadded, part2Depth)
                            : int3(atlasWidth, atlasHeight, part2Depth);
                    }
                }

                gvdbInfo.bindParameterBlock(gvdbBlock, slotId);

                if (mipId == 0)
                {
                    volumeDesc.PhaseFunctionConstantG = g;
                    volumeDesc.sigma_s = sigma_s;
                    volumeDesc.sigma_a = sigma_a;
                    volumeDesc.sigma_t = sigma_s.x + sigma_a.x;
                    volumeDesc.tStep = (length(gvdbInfo.xform[0][0].xyz()) + length(gvdbInfo.xform[0][1].xyz()) + length(gvdbInfo.xform[0][2].xyz())) / 3.f;
                    volumeDesc.densityScaleFactor = densityScale;
                    volumeDesc.densityScaleFactorByScaling = densityScale / mVolumeWorldScaling;
                    volumeDesc.invMaxDensity = gvdbInfo.invMaxValue[0];
                    volumeDesc.gridRes = uint3((uint32_t)round(gvdbInfo.bmax[0].x - gvdbInfo.bmin[0].x), (uint32_t)round(gvdbInfo.bmax[0].y - gvdbInfo.bmin[0].y), (uint32_t)round(gvdbInfo.bmax[0].z - gvdbInfo.bmin[0].z));
                    volumeDesc.hasEmission = false;
                    volumeDesc.LeScale = LeScale;
                    volumeDesc.temperatureCutOff = temperatureCutOff;
                    volumeDesc.temperatureScale = temperatureScale;
                }

                if (typeId == numTypes - 1 && mipId == numMips - 1)
                {
                    if (hasEmissionGrid && mipId < 2 * kNumMaxMips) { mipId = 2 * kNumMaxMips - 1; numMips = 2 * kNumMaxMips + 1; }
                    else if (hasVelocityGrid && mipId < 2 * kNumMaxMips + 1) { mipId = 2 * kNumMaxMips; numMips = 2 * kNumMaxMips + 2; }
                }
            }
        }

        if (curFrameId >= 1)
        {
            for (int i = 0; i < gvdbParamBlocks.numMips; i++) mGVDBInfos[curFrameId - 1].bindPrevParameterBlock(gvdbBlock, i);
            if (gvdbParamBlocks.hasEmissionGrid) mGVDBInfos[curFrameId - 1].bindPrevParameterBlock(gvdbBlock, 2 * kNumMaxMips);
            if (gvdbParamBlocks.hasVelocityGrid) mGVDBInfos[curFrameId - 1].bindPrevParameterBlock(gvdbBlock, 2 * kNumMaxMips + 1);
        }

        volumeDesc.numMips = gvdbParamBlocks.numMips;
        volumeDesc.velocityScale = 1;
        volumeDesc.hasEmission = gvdbParamBlocks.hasEmissionGrid;
        volumeDesc.hasVelocity = gvdbParamBlocks.hasVelocityGrid;
        volumeDesc.hasAnimation = curFrameId >= 0;
        volumeDesc.usePrevGridForReproj = false;
        mVolumeDescArray.push_back(volumeDesc);

        ShaderVar sceneVar = sceneBlock->getRootVar();
        sceneVar["volumeDesc"].setBlob(volumeDesc);

        float4x4 externalModelToWorldMatrix = computeVolumeExternalModelToWorldMatrix();
        if (curFrameId <= 0)
        {
            sceneVar["volumeWorldTranslation"] = mVolumeWorldTranslation;
            sceneVar["volumeWorldScaling"] = mVolumeWorldScaling;
            float4x4 externalWorldToModelMatrix = inverse(externalModelToWorldMatrix);
            // The GVDB xform/invxform matrices are stored in GVDB's (column-major) layout, which the
            // verbatim shaders consume with a row-vector `mul(v, M)`. Falcor-native matrices built here
            // are the transpose of that layout, so transpose before binding to stay consistent with
            // gvdb.xform in the shader (identity is transpose-invariant, so static volumes are unaffected).
            sceneVar["volumeExternalWorldToModelMatrix"] = transpose(externalWorldToModelMatrix);
            sceneVar["volumeExternalModelToWorldMatrix"] = transpose(externalModelToWorldMatrix);
            // Emissive lights scale by gScene.emissiveIntensityMultiplier; the shader default (1.f)
            // does not apply to cbuffer-backed data, so set it explicitly or emissive lighting is 0.
            sceneVar["emissiveIntensityMultiplier"] = 1.f;
        }

        // gvdbInfo.xform is in GVDB's layout (transpose of a Falcor-native float4x4); use its transpose
        // so this host-side transform stays consistent with the Falcor-native external matrix.
        float4x4 m0 = math::mul(externalModelToWorldMatrix, transpose(gvdbInfo.xform[0]));
        float3 worldMin = math::mul(m0, float4(gvdbInfo.bmin[0], 1.f)).xyz();
        float3 worldMax = math::mul(m0, float4(gvdbInfo.bmax[0], 1.f)).xyz();
        mVDBVolumeBBs.push_back(AABB(worldMin, worldMax));
        sceneVolumeBB = AABB(worldMin, worldMax);

        gvdbParamBlocks.paramBlock = gvdbBlock;
        mGVDBInfos.push_back(gvdbInfo);
        mGVDBVolumes.push_back(gvdbParamBlocks);

        dumpGVDBDiag("LIVE (gvdb.dll)", gvdbInfo, volumeDesc, gvdbParamBlocks.numMips);

        mpDevice->getRenderContext()->submit(true);

        return (uint32_t)mGVDBVolumes.size() - 1;
        logWarning("GVDBVolumeManager::addVolume: GVDB support not compiled in (FALCOR_HAS_GVDB=0); cannot read '{}'.", vbxFile);
        return 0;
        return 0;
#endif
    }

    // -----------------------------------------------------------------------------------------
    // Scene thin hooks — delegate to the GVDBVolumeManager.
    // -----------------------------------------------------------------------------------------
    int Scene::getVolumeNumMips(int volumeId)
    {
        if (!mpGVDB || mpGVDB->empty()) return 1;
        if (volumeId == -1) volumeId = mVDBAnimationFrameId;
        return mpGVDB->getNumMips(volumeId);
    }

    float3 Scene::getSceneVolumeCenter() const
    {
        return mSceneVolumeBB.valid() ? mSceneVolumeBB.center() : float3(0.f);
    }

    void Scene::updateVolumeDesc()
    {
        mpSceneBlock->getRootVar()["volumeDesc"].setBlob(mVolumeDesc);
    }

    void Scene::setVolumeShaderData(const ShaderVar& var, int volumeId)
    {
        if (!mpGVDB || mpGVDB->empty()) return;
        if (volumeId == -1) volumeId = mVDBAnimationFrameId;
        mpGVDB->setShaderData(var, volumeId);
    }

    void Scene::advanceVolumeAnimation()
    {
        // No-op unless an animated GVDB sequence is loaded. Ported from the fork's Scene::update
        // volume block: advance the frame, swap in the per-frame VolumeDesc, but PRESERVE the
        // UI/pass-adjustable fields (density scale, phase g, LeScale, etc.).
        if (!mpGVDB || mpGVDB->mVolumeDescArray.empty()) return;
        const int numFrames = mpGVDB->mVDBAnimationFrames;

        if (mUseAnimatedVolume && !mPauseVDBAnimation && numFrames > 0)
        {
            // Fields the user/pass can tweak at runtime — keep them across the frame swap.
            const float densityScale = mVolumeDesc.densityScaleFactor;
            const float tStep = mVolumeDesc.tStep;
            const float LeScale = mVolumeDesc.LeScale;
            const float temperatureCutOff = mVolumeDesc.temperatureCutOff;
            const float temperatureScale = mVolumeDesc.temperatureScale;
            const float velocityScale = mVolumeDesc.velocityScale;
            const bool usePrevGridForReproj = mVolumeDesc.usePrevGridForReproj;
            const float3 sigma_s = mVolumeDesc.sigma_s;
            const float3 sigma_a = mVolumeDesc.sigma_a;
            const float g = mVolumeDesc.PhaseFunctionConstantG;

            mpGVDB->mVDBLastAnimationFrameId = mVDBAnimationFrameId;
            mVDBAnimationFrameId = (mVDBAnimationFrameId + 1) % numFrames;

            mVolumeDesc = mpGVDB->mVolumeDescArray[mVDBAnimationFrameId];
            mVolumeDesc.densityScaleFactor = densityScale;
            mVolumeDesc.tStep = tStep;
            mVolumeDesc.lastFrameHasEmission = mpGVDB->mVolumeDescArray[mpGVDB->mVDBLastAnimationFrameId].hasEmission;
            mVolumeDesc.LeScale = LeScale;
            mVolumeDesc.temperatureCutOff = temperatureCutOff;
            mVolumeDesc.temperatureScale = temperatureScale;
            mVolumeDesc.velocityScale = velocityScale;
            mVolumeDesc.sigma_s = sigma_s;
            mVolumeDesc.sigma_a = sigma_a;
            mVolumeDesc.PhaseFunctionConstantG = g;
            mVolumeDesc.densityScaleFactorByScaling = densityScale / mpGVDB->mVolumeWorldScaling;
            mVolumeDesc.hasAnimation = true;
            mVolumeDesc.usePrevGridForReproj = usePrevGridForReproj;
            mpSceneBlock->getRootVar()["volumeDesc"].setBlob(mVolumeDesc);
        }
        else
        {
            // Paused / single frame selected: keep the current frame but refresh derived fields.
            mVolumeDesc.hasAnimation = false;
            mVolumeDesc.lastFrameHasEmission = mpGVDB->mVolumeDescArray[mpGVDB->mVDBLastAnimationFrameId].hasEmission;
            mVolumeDesc.densityScaleFactorByScaling = mVolumeDesc.densityScaleFactor / mpGVDB->mVolumeWorldScaling;
            mpSceneBlock->getRootVar()["volumeDesc"].setBlob(mVolumeDesc);
        }
    }

    void Scene::setRaytracingAcceleraitonStructure(RenderContext* pContext, const ShaderVar& var)
    {
        // Only used by "surface scenes" (mUseSurfaceScene). Volume-only scenes (e.g. the plume)
        // never call this. Wired up alongside the surface-scene path in a later phase.
        (void)pContext;
        (void)var;
    }

    bool Scene::renderVolumeUI(Gui::Widgets& widget)
    {
        bool dirty = false;
        if (auto g = widget.group("Volume"))
        {
            dirty |= g.var("Density Scale", mVolumeDesc.densityScaleFactor, 0.f, 1000.f);
            dirty |= g.var("Phase g", mVolumeDesc.PhaseFunctionConstantG, -1.f, 1.f);
            if (dirty) updateVolumeDesc();
        }
        return dirty;
    }

    uint32_t Scene::addGVDBVolume(int curFrameId, float3 sigma_a, float3 sigma_s, float g, std::string vbxFile, int numMips,
        float DensityScale, bool hasVelocityGrid, bool hasEmissionGrid, float LeScale, float temperatureCutOff, float temperatureScale,
        float3 worldTranslation, float3 worldRotation, float worldScaling)
    {
        if (!mpGVDB) mpGVDB = std::make_shared<GVDBVolumeManager>(mpDevice);
        return mpGVDB->addVolume(mVolumeDesc, mSceneVolumeBB, mpSceneBlock, curFrameId, sigma_a, sigma_s, g, vbxFile, numMips, DensityScale,
            hasVelocityGrid, hasEmissionGrid, LeScale, temperatureCutOff, temperatureScale, worldTranslation, worldRotation, worldScaling);
    }

    uint32_t Scene::addGVDBVolumeSequence(float3 sigma_a, float3 sigma_s, float g, std::string dataFilePrefix, int numberFixedLength,
        int startFrame, int numFrames, int numMips, float DensityScale, bool hasVelocityGrid, bool hasEmissionGrid, float LeScale,
        float temperatureCutOff, float temperatureScale, float3 worldTranslation, float3 worldRotation, float worldScaling)
    {
        if (!mpGVDB) mpGVDB = std::make_shared<GVDBVolumeManager>(mpDevice);

        mUseAnimatedVolume = true;
        mpGVDB->mVDBAnimationFrames = numFrames;
        mVDBAnimationFrameId = numFrames - 1;

        for (int i = 0; i < numFrames; i++)
        {
            std::string frameName = std::to_string(startFrame + i);
            int numChars = (int)frameName.length();
            for (int j = numChars; j < numberFixedLength; j++) frameName = "0" + frameName;
            addGVDBVolume(i, sigma_a, sigma_s, g, dataFilePrefix + frameName, numMips, DensityScale, hasVelocityGrid, hasEmissionGrid,
                LeScale, temperatureCutOff, temperatureScale, worldTranslation, worldRotation, worldScaling);
        }

        // The "previous frame" of the first frame is the last frame (wrap-around for temporal reprojection).
        if (!mpGVDB->mGVDBVolumes.empty())
        {
            const int last = numFrames - 1;
            const int kNumMaxMipsLocal = 8;
            for (int i = 0; i < mpGVDB->mGVDBVolumes[0].numMips; i++)
                mpGVDB->mGVDBInfos[last].bindPrevParameterBlock(mpGVDB->mGVDBVolumes[0].paramBlock, i);
            if (mpGVDB->mGVDBVolumes[0].hasEmissionGrid) mpGVDB->mGVDBInfos[last].bindPrevParameterBlock(mpGVDB->mGVDBVolumes[0].paramBlock, 2 * kNumMaxMipsLocal);
            if (mpGVDB->mGVDBVolumes[0].hasVelocityGrid) mpGVDB->mGVDBInfos[last].bindPrevParameterBlock(mpGVDB->mGVDBVolumes[0].paramBlock, 2 * kNumMaxMipsLocal + 1);
        }

        return numFrames;
    }
}
