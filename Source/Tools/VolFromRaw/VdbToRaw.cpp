/***************************************************************************
 # Volumetric ReSTIR port -- a .vdb grid -> a dense raw array, the inverse of VolFromRaw.
 #
 # Scripts/make_volumes.py reshapes an EmberGen frame in numpy (the dust shockwave: its hole cleared, its density
 # rebuilt at billow scale); this reads the frame's grid into memory for it. Writes the grid's active bounding box as
 # raw float32 in C order, shape nx x ny x nz (x slowest, z fastest: OpenVDB's default Dense layout, LayoutZYX), and
 # prints the box (index space) and the voxel size on one line:
 #     bbox <minx> <miny> <minz> dims <nx> <ny> <nz> voxel <size> components <1|3>
 # A vector grid (Bifrost's voxel_velocity, a Vec3SGrid) is written with its three components fastest.
 #
 # Runs from Falcor's runtime directory, as VolFromRaw and VDBPrep do (their headers say why). Build (repo root,
 # vcvars64 shell), as VolFromRaw:
 #   cl /std:c++17 /EHsc /MD /DIMATH_HALF_NO_LOOKUP_TABLE /I external\packman\deps\include
 #      Source\Tools\VolFromRaw\VdbToRaw.cpp
 #      /link /LIBPATH:external\packman\deps\lib
 #      /OUT:build\windows-vs2022\bin\Release\VdbToRaw.exe openvdb.lib
 #
 # Usage: VdbToRaw <in.vdb> <grid name> <out.raw> [<minx> <miny> <minz> <maxx> <maxy> <maxz>]
 #   (the optional box, inclusive index coordinates, clips the grid: Bifrost keeps a temperature grid active far past
 #   its smoke, whose dense copy would not fit in memory)
 **************************************************************************/
#include <openvdb/openvdb.h>
#include <openvdb/tools/Dense.h>

#include <cstdio>
#include <cstdlib>

// Writes the grid's active box (clipped to `clip` if given) as dense raw values and reports it; 0 on success.
template<typename GridT>
static int dump(const GridT& grid, const char* name, const char* path, const openvdb::CoordBBox* clip, int components)
{
    using ValueT = typename GridT::ValueType;
    openvdb::CoordBBox box = grid.evalActiveVoxelBoundingBox();
    if (clip)  // a clip box: Bifrost keeps a temperature grid active far past its smoke (ambient tiles)
    {
        box.intersect(*clip);
        if (box.empty()) { printf("ERROR: grid '%s' has nothing inside the clip box\n", name); return 2; }
    }
    openvdb::tools::Dense<ValueT, openvdb::tools::LayoutZYX> dense(box);  // z fastest: data[(x * ny + y) * nz + z]
    openvdb::tools::copyToDense(grid, dense);

    FILE* f = fopen(path, "wb");
    if (!f) { printf("ERROR: cannot write %s\n", path); return 1; }
    const size_t n = dense.valueCount();
    if (fwrite(dense.data(), sizeof(ValueT), n, f) != n) { printf("ERROR: short write to %s\n", path); fclose(f); return 1; }
    fclose(f);
    const openvdb::Coord d = box.dim();
    printf("bbox %d %d %d dims %d %d %d voxel %g components %d\n", box.min().x(), box.min().y(), box.min().z(), d.x(), d.y(),
           d.z(), grid.voxelSize().x(), components);
    return 0;
}

int main(int argc, char** argv)
{
    if (argc < 4)
    {
        printf("Usage: VdbToRaw <in.vdb> <grid name> <out.raw> [<minx> <miny> <minz> <maxx> <maxy> <maxz>]\n");
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
    openvdb::CoordBBox clip;
    if (argc >= 10)
        clip = openvdb::CoordBBox(openvdb::Coord(atoi(argv[4]), atoi(argv[5]), atoi(argv[6])),
                                  openvdb::Coord(atoi(argv[7]), atoi(argv[8]), atoi(argv[9])));
    if (openvdb::FloatGrid::Ptr grid = openvdb::gridPtrCast<openvdb::FloatGrid>(base))
        return dump(*grid, argv[2], argv[3], argc >= 10 ? &clip : nullptr, 1);
    if (openvdb::Vec3SGrid::Ptr grid = openvdb::gridPtrCast<openvdb::Vec3SGrid>(base))
        return dump(*grid, argv[2], argv[3], argc >= 10 ? &clip : nullptr, 3);
    printf("ERROR: grid '%s' is neither a float nor a Vec3s grid (%s)\n", argv[2], base->type().c_str());
    return 2;
}
