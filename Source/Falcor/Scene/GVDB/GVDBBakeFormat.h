/***************************************************************************
 # Volumetric ReSTIR port — offline GVDB bake format.
 #
 # This header defines the on-disk format produced by the standalone GVDBBake tool
 # (Source/Tools/GVDBBake) and consumed by Scene::loadBakedGVDBVolume (SceneGVDB.cpp).
 #
 # Rationale: the prebuilt gvdb.dll hard-links an OpenVDB build that is ABI-incompatible
 # with the OpenVDB shipped by Falcor 8.0, so gvdb.dll cannot be loaded inside the Falcor
 # process. Instead, the GVDBBake tool runs gvdb.dll in isolation (its own OpenVDB, no
 # conflict) to parse each .vbx and serialize everything Falcor needs (repacked sparse node
 # pools, child lists, the dense density atlas, and the per-mip GVDBInfo metadata) into a
 # plain binary. Falcor then just reads the binary and uploads it to the GPU — no gvdb.dll
 # in the Falcor process at all.
 #
 # POD only, no Falcor or GVDB dependencies, so both the tool and Falcor can include it.
 **************************************************************************/
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <string>

namespace gvdbbake
{
    static const int MAX_LEVELS = 3;
    static const int MAX_MIPS = 30;          // matches GVDBInfo::MAX_MIPS
    static const int NLM = MAX_LEVELS * MAX_MIPS; // 90
    static const int MAX_SLOTS = 19;         // grid mips 0-7, conservative 8-15, temperature 16, velocity 17, supervoxel 18
    static const uint32_t kMagic = 0x42445647; // "GVDB"
    static const uint32_t kVersion = 1;

#pragma pack(push, 1)
    // Scalar metadata mirroring the scalar (non-resource) fields of Falcor's GVDBInfo, using
    // plain types so the tool (no Falcor) can produce it. Falcor copies these into GVDBInfo.
    struct BakedInfo
    {
        int32_t  dim[NLM];
        int32_t  res[NLM];
        float    vdel[NLM][3];
        int32_t  noderange[NLM][3];
        int32_t  nodecnt[NLM];
        int32_t  nodewid[NLM];
        int32_t  childwid[NLM];
        int32_t  top_lev[MAX_MIPS];
        int32_t  max_iter;
        float    epsilon;
        uint32_t clr_chan;
        float    bmin[MAX_MIPS][3];
        float    bmax[MAX_MIPS][3];
        float    superVoxelWorldSpaceDiagonalLength;
        int32_t  volInDimensions[MAX_MIPS][3];
        int32_t  volInDimensions_part2[MAX_MIPS][3];
        float    xform[MAX_MIPS][16];
        float    invxform[MAX_MIPS][16];
        float    invxrot[MAX_MIPS][16];
        float    maxValue[MAX_MIPS];
        float    invMaxValue[MAX_MIPS];
        float    densityCompressScaleFactor[MAX_MIPS];
    };

    struct BakedHeader
    {
        uint32_t magic;
        uint32_t version;
        int32_t  numMips;          // gvdbParamBlocks.numMips
        int32_t  hasEmission;
        int32_t  hasVelocity;
        float    volumeMaxDensity; // mVolumeDesc.maxDensity (gvdb.mGridValMax of slot 0)
    };
#pragma pack(pop)

    // ---- Per-slot payload (written sequentially for slot = 0 .. MAX_SLOTS-1) ----
    // For each slot:
    //   for level in [0, MAX_LEVELS): uint64 nodeBytes; <nodeBytes bytes>; uint64 childBytes; <childBytes bytes>;
    //   int32 hasAtlas;
    //   if hasAtlas: int32 atlasW, atlasH, atlasDepth, part1Depth, part2Depth; int32 isVelocity;
    //                <atlasW*atlasH*atlasDepth * (isVelocity?3:1) floats>

    // Small binary write/read helpers.
    inline void writePOD(FILE* f, const void* p, size_t n) { fwrite(p, 1, n, f); }
    inline bool readPOD(FILE* f, void* p, size_t n) { return fread(p, 1, n, f) == n; }
    template<typename T> inline void writeVal(FILE* f, const T& v) { fwrite(&v, sizeof(T), 1, f); }
    template<typename T> inline bool readVal(FILE* f, T& v) { return fread(&v, sizeof(T), 1, f) == 1; }
    inline void writeBlob(FILE* f, const void* data, uint64_t bytes) { writeVal(f, bytes); if (bytes) fwrite(data, 1, (size_t)bytes, f); }
    inline bool readBlob(FILE* f, std::vector<uint8_t>& out) { uint64_t bytes = 0; if (!readVal(f, bytes)) return false; out.resize((size_t)bytes); return bytes ? readPOD(f, out.data(), (size_t)bytes) : true; }
}
