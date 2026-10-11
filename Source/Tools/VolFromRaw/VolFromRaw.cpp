/***************************************************************************
 # Volumetric ReSTIR port -- a dense density array -> a sparse .vdb, for authored volumes.
 #
 # Scripts/make_volumes.py builds a density field in numpy (stage haze, ground mist, smoke puffs) and
 # writes it as raw float32 in C order, shape nx x ny x nz (x slowest, z fastest). This writes it as an
 # OpenVDB FloatGrid named "density" (a fog volume, background 0) with every voxel above the cutoff
 # active, which gImportVDB then converts to the .vbx mips the renderer loads -- the same route the
 # EmberGen frames took through VDBPrep.
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
 # Usage: VolFromRaw <in.raw> <nx> <ny> <nz> <voxelSize> <out.vdb> [cutoff=1e-4]
 **************************************************************************/
#include <openvdb/openvdb.h>

#include <cstdio>
#include <cstdlib>
#include <vector>

int main(int argc, char** argv)
{
    if (argc < 7)
    {
        printf("Usage: VolFromRaw <in.raw> <nx> <ny> <nz> <voxelSize> <out.vdb> [cutoff=1e-4]\n");
        return 1;
    }
    const long long nx = atoll(argv[2]), ny = atoll(argv[3]), nz = atoll(argv[4]);
    const double voxelSize = atof(argv[5]);
    const float cutoff = argc > 7 ? static_cast<float>(atof(argv[7])) : 1e-4f;
    if (nx <= 0 || ny <= 0 || nz <= 0 || voxelSize <= 0) { printf("ERROR: bad dimensions or voxel size\n"); return 1; }

    std::vector<float> data(static_cast<size_t>(nx * ny * nz));
    FILE* f = fopen(argv[1], "rb");
    if (!f) { printf("ERROR: cannot open %s\n", argv[1]); return 1; }
    const size_t got = fread(data.data(), sizeof(float), data.size(), f);
    fclose(f);
    // A short read means the shape given does not match the file: refuse rather than write a volume
    // whose rows are shifted.
    if (got != data.size()) { printf("ERROR: %s holds %zu floats, the shape needs %zu\n", argv[1], got, data.size()); return 2; }

    openvdb::initialize();
    openvdb::FloatGrid::Ptr grid = openvdb::FloatGrid::create(0.f);
    grid->setName("density");
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

    openvdb::GridPtrVec grids{grid};
    openvdb::io::File out(argv[6]);
    out.write(grids);
    out.close();
    printf("Wrote %s: %zu active voxels of %zu, max %.4f\n", argv[6], active, data.size(), maxValue);
    return 0;
}
