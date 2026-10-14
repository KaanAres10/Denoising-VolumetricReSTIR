/***************************************************************************
 # Volumetric ReSTIR port -- a dense density array -> a sparse .vdb, for authored volumes.
 #
 # Scripts/make_volumes.py builds a density field in numpy (stage haze, ground mist, smoke puffs) and
 # writes it as raw float32 in C order, shape nx x ny x nz (x slowest, z fastest). This writes it as an
 # OpenVDB FloatGrid named "density" (a fog volume, background 0) with every voxel above the cutoff
 # active, which gImportVDB then converts to the .vbx mips the renderer loads -- the same route the
 # EmberGen frames took through VDBPrep. With a temperature array (same shape) it is written beside the
 # density as a FloatGrid named "temperature", which gImportVDB turns into <name>_temperature.vbx: the
 # grid an emissive volume (hasEmission) glows by.
 #
 # Runs as its own process from Falcor's runtime directory, for the reason VDBPrep.cpp's header gives
 # (it must load Falcor's openvdb.dll, not the GVDB-era one beside gImportVDB.exe).
 #
 # Build (from the repo root, inside a vcvars64 shell). IMATH_HALF_NO_LOOKUP_TABLE: the runtime directory has
 # no Imath-3_1.dll, and without it writing the grid pulls in Imath's half-to-float table.
 #   cl /std:c++17 /EHsc /MD /DIMATH_HALF_NO_LOOKUP_TABLE /I external\packman\deps\include
 #      Source\Tools\VolFromRaw\VolFromRaw.cpp
 #      /link /LIBPATH:external\packman\deps\lib
 #      /OUT:build\windows-vs2022\bin\Release\VolFromRaw.exe openvdb.lib
 #
 # Usage: VolFromRaw <in.raw> <nx> <ny> <nz> <voxelSize> <out.vdb> [cutoff=1e-4] [temperature.raw]
 **************************************************************************/
#include <openvdb/openvdb.h>

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

// A short read means the shape given does not match the file: refuse rather than write a volume whose rows are shifted.
static bool readRaw(const char* path, size_t count, std::vector<float>& data)
{
    data.resize(count);
    FILE* f = fopen(path, "rb");
    if (!f) { printf("ERROR: cannot open %s\n", path); return false; }
    const size_t got = fread(data.data(), sizeof(float), count, f);
    fclose(f);
    if (got != count) { printf("ERROR: %s holds %zu floats, the shape needs %zu\n", path, got, count); return false; }
    return true;
}

// Every voxel above the cutoff active, in a fog volume (background 0).
static openvdb::FloatGrid::Ptr toGrid(const std::vector<float>& data, long long nx, long long ny, long long nz, double voxelSize,
    float cutoff, const std::string& name)
{
    openvdb::FloatGrid::Ptr grid = openvdb::FloatGrid::create(0.f);
    grid->setName(name);
    grid->setGridClass(openvdb::GRID_FOG_VOLUME);
    grid->setTransform(openvdb::math::Transform::createLinearTransform(voxelSize));
    openvdb::FloatGrid::Accessor acc = grid->getAccessor();
    size_t active = 0;
    float maxValue = 0.f;
    for (long long i = 0; i < nx; i++)
        for (long long j = 0; j < ny; j++)
            for (long long k = 0; k < nz; k++)
            {
                const float v = data[static_cast<size_t>((i * ny + j) * nz + k)];
                if (v > cutoff)
                {
                    acc.setValue(openvdb::Coord(static_cast<int>(i), static_cast<int>(j), static_cast<int>(k)), v);
                    active++;
                    if (v > maxValue) maxValue = v;
                }
            }
    printf("%s: %zu active voxels of %zu, max %.4f\n", name.c_str(), active, data.size(), maxValue);
    return grid;
}

int main(int argc, char** argv)
{
    if (argc < 7)
    {
        printf("Usage: VolFromRaw <in.raw> <nx> <ny> <nz> <voxelSize> <out.vdb> [cutoff=1e-4] [temperature.raw]\n");
        return 1;
    }
    const long long nx = atoll(argv[2]), ny = atoll(argv[3]), nz = atoll(argv[4]);
    const double voxelSize = atof(argv[5]);
    const float cutoff = argc > 7 ? static_cast<float>(atof(argv[7])) : 1e-4f;
    if (nx <= 0 || ny <= 0 || nz <= 0 || voxelSize <= 0) { printf("ERROR: bad dimensions or voxel size\n"); return 1; }

    const size_t count = static_cast<size_t>(nx * ny * nz);
    std::vector<float> data, temperature;
    if (!readRaw(argv[1], count, data)) return 2;
    if (argc > 8 && !readRaw(argv[8], count, temperature)) return 2;

    openvdb::initialize();
    openvdb::GridPtrVec grids{toGrid(data, nx, ny, nz, voxelSize, cutoff, "density")};
    if (!temperature.empty()) grids.push_back(toGrid(temperature, nx, ny, nz, voxelSize, cutoff, "temperature"));
    openvdb::io::File out(argv[6]);
    out.write(grids);
    out.close();
    printf("Wrote %s\n", argv[6]);
    return 0;
}
