/***************************************************************************
 # Volumetric ReSTIR port — standalone GVDB bake tool.
 #
 # Parses GVDB .vbx volume files with the prebuilt gvdb.dll (run this from a directory where
 # gvdb.dll can find its own OpenVDB/TBB, e.g. the fork's Bin\x64\Release), and serializes
 # everything Falcor needs into a .bin (see GVDBBakeFormat.h). Falcor then reads the .bin and
 # never touches gvdb.dll — avoiding the OpenVDB ABI conflict inside the Falcor process.
 #
 # Extraction logic is a faithful copy of Scene::addGVDBVolume's GVDB path (SceneGVDB.cpp),
 # with GPU resource creation replaced by blob writes.
 #
 # Build (from Denoising-VolumetricReSTIR/Bin/x64/Release, so gvdb.lib/deps resolve):
 #   cl /std:c++17 /EHsc /I "<repo>/Denoising-VolumetricReSTIR/Source/Externals/gvdb/include"
 #      /I "<repo>/Source/Falcor" GVDBBake.cpp
 #      "<repo>/Denoising-VolumetricReSTIR/Source/Externals/gvdb/lib/gvdb.lib"
 #
 # Usage: GVDBBake <vbxFolder> <numMips> <hasVelocity 0|1> <hasEmission 0|1> <out.bin>
 **************************************************************************/

#include <gvdb_volume_gvdb.h>       // brings `using namespace nvdb;`
#include "Scene/GVDB/GVDBBakeFormat.h"

#include <filesystem>
#include <string>
#include <vector>
#include <cstdio>
#include <cstring>
#include <cfloat>
#include <algorithm>

using namespace gvdbbake;
namespace fs = std::filesystem;

static const int kNumMaxMips = 8; // matches HostDeviceSharedConstants.slang

// CUDA-style vector types used by the GVDB node layout (gvdb does not define these globally).
struct int3 { int32_t x, y, z; };
struct uint2 { uint32_t x, y; };
struct float3 { float x, y, z; };

struct NewVDBNode { int32_t mPackedPosValue[3]; uint32_t mChildList; float mDensityBounds[4]; };
struct OldVDBNode
{
    uint32_t mPackedLevFlagPriority;
    int3 mPos; int3 mValue; float3 mVRange;
    uint2 mParent; uint2 mChildList; uint2 mMask;
};

struct SlotBlobs
{
    std::vector<uint8_t> node[MAX_LEVELS];
    std::vector<uint8_t> child[MAX_LEVELS];
    bool hasAtlas = false;
    int32_t w = 0, h = 0, d = 0, p1 = 0, p2 = 0;
    int32_t isVelocity = 0;
    std::vector<float> atlas; // w*h*d * (isVelocity?3:1)
};

static bool exists(const std::string& p) { return fs::exists(p); }

int main(int argc, char** argv)
{
    if (argc < 6) { printf("Usage: GVDBBake <vbxFolder> <numMips> <hasVelocity 0|1> <hasEmission 0|1> <out.bin>\n"); return 1; }
    std::string vbxFile = argv[1];
    int numMips = atoi(argv[2]);
    bool hasVelocityGrid = atoi(argv[3]) != 0;
    bool hasEmissionGrid = atoi(argv[4]) != 0;
    std::string outPath = argv[5];

    std::string filenameWithoutPath = vbxFile;
    size_t last_slash_idx = filenameWithoutPath.find_last_of("\\/");
    if (std::string::npos != last_slash_idx) filenameWithoutPath.erase(0, last_slash_idx + 1);

    BakedInfo info; memset(&info, 0, sizeof(info));
    BakedHeader hdr{}; hdr.magic = kMagic; hdr.version = kVersion; hdr.hasEmission = 0; hdr.hasVelocity = 0; hdr.volumeMaxDensity = 0.f;
    int outNumMips = numMips;
    SlotBlobs slots[MAX_SLOTS];

    std::string temperatureFilename = vbxFile + "/" + filenameWithoutPath + "_temperature.vbx";
    if (!exists(temperatureFilename)) hasEmissionGrid = false;

    for (int mipId = 0; mipId < numMips; mipId++)
    {
        int numTypes = mipId >= 2 * kNumMaxMips ? 1 : 2;
        for (int typeId = 0; typeId < numTypes; typeId++)
        {
            std::string filename = vbxFile;
            if (numMips > 1 && mipId < 2 * kNumMaxMips)
                filename = vbxFile + "/" + filenameWithoutPath + "_mip" + std::to_string(mipId) + (typeId == 0 ? "" : "c") + ".vbx";
            else if (mipId == 2 * kNumMaxMips)
                filename = vbxFile + "/" + filenameWithoutPath + "_temperature.vbx";
            else if (mipId == 2 * kNumMaxMips + 1)
                filename = vbxFile + "/" + filenameWithoutPath + "_velocity_x.vbx";

            if (!exists(filename))
            {
                if (mipId == 2 * kNumMaxMips) { hdr.hasEmission = 0; continue; }
                else if (mipId == 2 * kNumMaxMips + 1) { hdr.hasVelocity = 0; break; }
                else
                {
                    bool shouldSkip = false;
                    if (typeId == 1) { printf("Warning: no conservative grid for '%s'\n", filename.c_str()); numTypes = 1; if (mipId == numMips - 1) shouldSkip = true; }
                    else { outNumMips = mipId; shouldSkip = true; }
                    if (shouldSkip)
                    {
                        if (hasEmissionGrid) { numMips = 2 * kNumMaxMips + 1; mipId = 2 * kNumMaxMips - 1; }
                        else if (hasVelocityGrid) { numMips = 2 * kNumMaxMips + 2; mipId = 2 * kNumMaxMips; }
                    }
                    continue;
                }
            }
            std::string fullpath = fs::absolute(filename).string();
            if (mipId == 0) printf("Baking '%s'\n", filename.c_str());
            if (mipId == 2 * kNumMaxMips) hdr.hasEmission = 1;
            if (mipId == 2 * kNumMaxMips + 1) hdr.hasVelocity = 1;

            VolumeGVDB gvdb; gvdb.Initialize(true); gvdb.LoadVBX(fullpath, true);
            int slotId = mipId; if (typeId == 1) slotId += kNumMaxMips;
            int levs = gvdb.mPool->getNumLevels();

            for (int n = 0; n <= levs - 1; n++)
            {
                int cnt = (int)gvdb.mPool->getPoolTotalCnt(0, n);
                info.nodecnt[n + MAX_LEVELS * slotId] = cnt;
                if (cnt == 0) continue;
                info.dim[n + MAX_LEVELS * slotId] = gvdb.getLD(n);
                info.res[n + MAX_LEVELS * slotId] = gvdb.getRes(n);
                Vector3DI range = gvdb.getRange(n);
                Vector3DI res3DI = gvdb.getRes3DI(n);
                info.vdel[n + MAX_LEVELS * slotId][0] = (float)range.x / res3DI.x;
                info.vdel[n + MAX_LEVELS * slotId][1] = (float)range.y / res3DI.y;
                info.vdel[n + MAX_LEVELS * slotId][2] = (float)range.z / res3DI.z;
                info.noderange[n + MAX_LEVELS * slotId][0] = range.x;
                info.noderange[n + MAX_LEVELS * slotId][1] = range.y;
                info.noderange[n + MAX_LEVELS * slotId][2] = range.z;
                info.nodewid[n + MAX_LEVELS * slotId] = (int)gvdb.mPool->getPoolWidth(0, n);
                info.childwid[n + MAX_LEVELS * slotId] = (int)gvdb.mPool->getPoolWidth(1, n);

                int oldPoolWidth = 64, newPoolWidth = 32;
                int numElements = cnt;
                char* nodePoolPtr = gvdb.mPool->getPoolCPU(0, n);
                if (slotId == 0) hdr.volumeMaxDensity = gvdb.mGridValMax;

                std::vector<NewVDBNode> nodePool(numElements);
                for (int i = 0; i < numElements; i++)
                {
                    OldVDBNode oldnode; NewVDBNode newnode; memset(&newnode, 0, sizeof(newnode));
                    memcpy(&oldnode, nodePoolPtr + oldPoolWidth * i, oldPoolWidth);
                    newnode.mPackedPosValue[0] = (oldnode.mPos.x & 0xFFFF) | (oldnode.mPos.y << 16);
                    newnode.mPackedPosValue[1] = (oldnode.mPos.z & 0xFFFF) | (oldnode.mValue.x << 16);
                    newnode.mPackedPosValue[2] = (oldnode.mValue.y & 0xFFFF) | (oldnode.mValue.z << 16);
                    uint2 listid = oldnode.mChildList;
                    if (listid.x == 0xFFFFFFFF)
                    {
                        newnode.mChildList = 0xFFFFFFFF;
                        int3 vMin = oldnode.mPos;
                        float sum = 0, minD = FLT_MAX, maxD = 0.f;
                        for (int ii = -1; ii <= 8; ii++) for (int jj = -1; jj <= 8; jj++) for (int kk = -1; kk <= 8; kk++)
                        {
                            float density = 0.f; int tcX, tcY, tcZ;
                            if (vMin.x + ii < gvdb.mEffectiveVoxMin.x || vMin.x + ii > gvdb.mEffectiveVoxMax.x - 1 ||
                                vMin.y + jj < gvdb.mEffectiveVoxMin.y || vMin.y + jj > gvdb.mEffectiveVoxMax.y - 1 ||
                                vMin.z + kk < gvdb.mEffectiveVoxMin.z || vMin.z + kk > gvdb.mEffectiveVoxMax.z - 1)
                                density = 0.f;
                            else
                                density = gvdb.getValueWithTexCoordFromRoot(Vector3DF(vMin.x + ii + 0.5f, vMin.y + jj + 0.5f, vMin.z + kk + 0.5f), gvdb.mPool->getAtlasCPU(0), tcX, tcY, tcZ);
                            minD = std::min(minD, density); maxD = std::max(maxD, density); sum += density;
                        }
                        newnode.mDensityBounds[0] = minD; newnode.mDensityBounds[1] = maxD; newnode.mDensityBounds[2] = sum / 512.f; newnode.mDensityBounds[3] = 0.f;
                    }
                    else
                    {
                        newnode.mChildList = ((listid.y & 0xFFFF) << 16) | ((listid.x >> 16) & 0xFFFF);
                    }
                    nodePool[i] = newnode;
                }
                info.nodewid[n + MAX_LEVELS * slotId] = newPoolWidth;
                slots[slotId].node[n].assign((uint8_t*)nodePool.data(), (uint8_t*)nodePool.data() + (size_t)newPoolWidth * numElements);

                if (n > 0)
                {
                    int numChild = (int)gvdb.mPool->getPoolSize(1, n) / 8;
                    char* childPoolPtr = gvdb.mPool->getPoolCPU(1, n);
                    std::vector<uint32_t> newChild(numChild);
                    for (int i = 0; i < numChild; i++)
                    {
                        uint2 oldE; memcpy(&oldE.x, childPoolPtr + 8 * i, 8);
                        newChild[i] = ((oldE.y & 0xFFFF) << 16) | ((oldE.x >> 16) & 0xFFFF);
                    }
                    info.childwid[n + MAX_LEVELS * slotId] /= 2;
                    slots[slotId].child[n].assign((uint8_t*)newChild.data(), (uint8_t*)newChild.data() + (size_t)gvdb.mPool->getPoolSize(1, n) / 2);
                }
                if (cnt == 1) info.top_lev[slotId] = n;
            }

            info.densityCompressScaleFactor[slotId] = 1.f;
            Matrix4F xform = gvdb.mVDBXform, invXform = gvdb.mVDBXformInv, invRot = invXform;
            invRot(3, 0) = 0; invRot(3, 1) = 0; invRot(3, 2) = 0;
            memcpy(info.xform[slotId], &xform, sizeof(float) * 16);
            memcpy(info.invxform[slotId], &invXform, sizeof(float) * 16);
            memcpy(info.invxrot[slotId], &invRot, sizeof(float) * 16);

            if (slotId == 0)
            {
                info.epsilon = gvdb.getEpsilon(); info.max_iter = gvdb.getMaxIter();
                info.superVoxelWorldSpaceDiagonalLength = 8.f * sqrtf(
                    info.xform[0][0] * info.xform[0][0] + info.xform[0][1] * info.xform[0][1] + info.xform[0][2] * info.xform[0][2] +
                    info.xform[0][4] * info.xform[0][4] + info.xform[0][5] * info.xform[0][5] + info.xform[0][6] * info.xform[0][6] +
                    info.xform[0][8] * info.xform[0][8] + info.xform[0][9] * info.xform[0][9] + info.xform[0][10] * info.xform[0][10]);
            }
            if (gvdb.mIsCustomVersion)
            {
                info.bmin[slotId][0] = (float)gvdb.mEffectiveVoxMin.x; info.bmin[slotId][1] = (float)gvdb.mEffectiveVoxMin.y; info.bmin[slotId][2] = (float)gvdb.mEffectiveVoxMin.z;
                info.bmax[slotId][0] = (float)gvdb.mEffectiveVoxMax.x; info.bmax[slotId][1] = (float)gvdb.mEffectiveVoxMax.y; info.bmax[slotId][2] = (float)gvdb.mEffectiveVoxMax.z;
                info.maxValue[slotId] = gvdb.mGridValMax; info.invMaxValue[slotId] = 1.f / info.maxValue[slotId];
            }
            else
            {
                info.bmin[slotId][0] = (float)gvdb.mObjMin.x; info.bmin[slotId][1] = (float)gvdb.mObjMin.y; info.bmin[slotId][2] = (float)gvdb.mObjMin.z;
                info.bmax[slotId][0] = (float)gvdb.mObjMax.x; info.bmax[slotId][1] = (float)gvdb.mObjMax.y; info.bmax[slotId][2] = (float)gvdb.mObjMax.z;
            }
            info.clr_chan = 0xFFFFFFFF;

            if (gvdb.mPool->getNumAtlas() > 0)
            {
                int atlasW = gvdb.mPool->getAtlasRes(0).x, atlasH = gvdb.mPool->getAtlasRes(0).y, atlasDepth = gvdb.mPool->getAtlasRes(0).z;
                int brickRes = gvdb.mPool->getAtlasBrickres(0);
                int part1Depth = atlasDepth > 2048 ? 2048 / brickRes * brickRes : atlasDepth;
                int part2Depth = atlasDepth - part1Depth;
                int numAtlas = atlasW * atlasH * atlasDepth;
                std::vector<float> clamped(numAtlas);
                float* atlasCPU = gvdb.mPool->getAtlasCPU(0);
                for (int i = 0; i < numAtlas; i++) clamped[i] = atlasCPU[i] / gvdb.mGridValMax < 1e-9f ? 0.f : atlasCPU[i];
                slots[slotId].hasAtlas = true;
                slots[slotId].w = atlasW; slots[slotId].h = atlasH; slots[slotId].d = atlasDepth; slots[slotId].p1 = part1Depth; slots[slotId].p2 = part2Depth;
                slots[slotId].isVelocity = 0;
                slots[slotId].atlas = std::move(clamped);
                info.volInDimensions[slotId][0] = atlasW; info.volInDimensions[slotId][1] = atlasH; info.volInDimensions[slotId][2] = part1Depth;
                if (atlasDepth > 2048) { info.volInDimensions_part2[slotId][0] = atlasW; info.volInDimensions_part2[slotId][1] = atlasH; info.volInDimensions_part2[slotId][2] = part2Depth; }
            }

            if (typeId == numTypes - 1 && mipId == numMips - 1)
            {
                if (hasEmissionGrid && mipId < 2 * kNumMaxMips) { mipId = 2 * kNumMaxMips - 1; numMips = 2 * kNumMaxMips + 1; }
                else if (hasVelocityGrid && mipId < 2 * kNumMaxMips + 1) { mipId = 2 * kNumMaxMips; numMips = 2 * kNumMaxMips + 2; }
            }
        }
    }

    hdr.numMips = outNumMips;

    FILE* f = fopen(outPath.c_str(), "wb");
    if (!f) { printf("Failed to open output '%s'\n", outPath.c_str()); return 1; }
    writeVal(f, hdr);
    writePOD(f, &info, sizeof(info));
    for (int s = 0; s < MAX_SLOTS; s++)
    {
        for (int n = 0; n < MAX_LEVELS; n++)
        {
            writeBlob(f, slots[s].node[n].data(), slots[s].node[n].size());
            writeBlob(f, slots[s].child[n].data(), slots[s].child[n].size());
        }
        int32_t hasAtlas = slots[s].hasAtlas ? 1 : 0; writeVal(f, hasAtlas);
        if (hasAtlas)
        {
            writeVal(f, slots[s].w); writeVal(f, slots[s].h); writeVal(f, slots[s].d); writeVal(f, slots[s].p1); writeVal(f, slots[s].p2); writeVal(f, slots[s].isVelocity);
            uint64_t bytes = slots[s].atlas.size() * sizeof(float); writeVal(f, bytes); if (bytes) fwrite(slots[s].atlas.data(), 1, (size_t)bytes, f);
        }
    }
    fclose(f);
    printf("Baked '%s' -> '%s' (numMips=%d, maxDensity=%f)\n", vbxFile.c_str(), outPath.c_str(), hdr.numMips, hdr.volumeMaxDensity);
    return 0;
}
