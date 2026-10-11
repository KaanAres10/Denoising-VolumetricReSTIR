/***************************************************************************
 # Volumetric ReSTIR port -- a .vdb grid -> a dense raw array, the inverse of VolFromRaw.
 #
 # Scripts/make_volumes.py reshapes an EmberGen frame in numpy (the dust shockwave: its hole cleared, its density
 # rebuilt at billow scale); this reads the frame's grid into memory for it. Writes the grid's active bounding box as
 # raw float32 in C order, shape nx x ny x nz (x slowest, z fastest: OpenVDB's default Dense layout, LayoutZYX), and
 # prints the box (index space) and the voxel size on one line:
 #     bbox <minx> <miny> <minz> dims <nx> <ny> <nz> voxel <size>
 #
 # Runs from Falcor's runtime directory, as VolFromRaw and VDBPrep do (their headers say why). Build (repo root,
 # vcvars64 shell), as VolFromRaw:
 #   cl /std:c++17 /EHsc /MD /DIMATH_HALF_NO_LOOKUP_TABLE /I external\packman\deps\include
 #      Source\Tools\VolFromRaw\VdbToRaw.cpp
 #      /link /LIBPATH:external\packman\deps\lib
 #      /OUT:build\windows-vs2022\bin\Release\VdbToRaw.exe openvdb.lib
 #
 # Usage: VdbToRaw <in.vdb> <grid name> <out.raw>
 **************************************************************************/
#include <openvdb/openvdb.h>
#include <openvdb/tools/Dense.h>

#include <cstdio>

int main(int argc, char** argv)
{
    if (argc < 4)
    {
        printf("Usage: VdbToRaw <in.vdb> <grid name> <out.raw>\n");
        return 1;
    }
    openvdb::initialize();
    openvdb::io::File in(argv[1]);
    in.open();
    openvdb::GridBase::Ptr base;
    for (openvdb::io::File::NameIterator it = in.beginName(); it != in.endName(); ++it)
        if (it.gridName() == argv[2]) base = in.readGrid(it.gridName());
    if (!base)
    {
        printf("ERROR: no grid named '%s' in %s; it has:", argv[2], argv[1]);
        for (openvdb::io::File::NameIterator it = in.beginName(); it != in.endName(); ++it) printf(" '%s'", it.gridName().c_str());
        printf("\n");
        return 2;
    }
    in.close();
    openvdb::FloatGrid::Ptr grid = openvdb::gridPtrCast<openvdb::FloatGrid>(base);
    if (!grid) { printf("ERROR: grid '%s' is not a float grid\n", argv[2]); return 2; }

    const openvdb::CoordBBox box = grid->evalActiveVoxelBoundingBox();
    openvdb::tools::Dense<float, openvdb::tools::LayoutZYX> dense(box);  // z fastest: data[(x * ny + y) * nz + z]
    openvdb::tools::copyToDense(*grid, dense);

    FILE* f = fopen(argv[3], "wb");
    if (!f) { printf("ERROR: cannot write %s\n", argv[3]); return 1; }
    const size_t n = dense.valueCount();
    if (fwrite(dense.data(), sizeof(float), n, f) != n) { printf("ERROR: short write to %s\n", argv[3]); fclose(f); return 1; }
    fclose(f);
    const openvdb::Coord d = box.dim();
    printf("bbox %d %d %d dims %d %d %d voxel %g\n", box.min().x(), box.min().y(), box.min().z(), d.x(), d.y(), d.z(),
           grid->voxelSize().x());
    return 0;
}
