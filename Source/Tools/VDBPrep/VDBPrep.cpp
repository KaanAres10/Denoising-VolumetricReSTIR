/***************************************************************************
 # Volumetric ReSTIR port -- standalone VDB grid renamer.
 #
 # EmberGen exports a combustion field named "flames", which GVDB's loader skips unless it is
 # the first grid in the file. Renaming it to "temperature" routes it into the emission slot.
 # Values are NOT modified: the 0-1 -> Kelvin mapping is a runtime affine transform applied in
 # VolumeBase.slang (temp = min(6400, (v - temperatureCutOff) * temperatureScale)), so fire
 # colour stays tunable without re-baking.
 #
 # Runs as its own process, so Falcor's OpenVDB and the gvdb.dll OpenVDB never meet.
 #
 # IMPORTANT -- where this binary lives is load-bearing. It MUST be built into Falcor's runtime
 # directory (build\windows-vs2022\bin\Release), never next to GVDBBake.exe: that folder ships
 # the 2021 GVDB-era openvdb.dll (1.9 MB) and Windows searches the executable's own directory
 # first, so a VDBPrep.exe placed there would load the very OpenVDB whose ABI conflict this whole
 # prebake design exists to avoid. Falcor's openvdb.dll (24 MB) and tbb.dll sit in the Release dir.
 #
 # Build (from the repo root, inside a vcvars64 shell). /LIBPATH is required: openvdb.lib pulls
 # in tbb.lib, which lives beside it in deps\lib.
 #   cl /std:c++17 /EHsc /MD /I external\packman\deps\include
 #      Source\Tools\VDBPrep\VDBPrep.cpp
 #      /link /LIBPATH:external\packman\deps\lib
 #      /OUT:build\windows-vs2022\bin\Release\VDBPrep.exe openvdb.lib
 #
 # Usage: VDBPrep <in.vdb> <out.vdb> <oldName>=<newName> [...]
 **************************************************************************/
#include <openvdb/openvdb.h>

#include <cstdio>
#include <cstring>
#include <map>
#include <string>

int main(int argc, char** argv)
{
    if (argc < 4)
    {
        printf("Usage: VDBPrep <in.vdb> <out.vdb> <oldName>=<newName> [...]\n");
        return 1;
    }

    std::map<std::string, std::string> renames;
    for (int i = 3; i < argc; i++)
    {
        const char* eq = strchr(argv[i], '=');
        if (!eq) { printf("Bad rename '%s', expected old=new\n", argv[i]); return 1; }
        // (pointer, length), not the iterator pair: argv[i] is char* and eq is const char*,
        // so the two-iterator constructor does not match.
        renames[std::string(argv[i], static_cast<size_t>(eq - argv[i]))] = std::string(eq + 1);
    }

    openvdb::initialize();

    openvdb::io::File in(argv[1]);
    in.open();
    openvdb::GridPtrVecPtr grids = in.getGrids();
    in.close();

    std::map<std::string, int> hits;
    for (auto& g : *grids)
    {
        auto it = renames.find(g->getName());
        if (it != renames.end())
        {
            printf("  renaming '%s' -> '%s'\n", it->first.c_str(), it->second.c_str());
            g->setName(it->second);
            hits[it->first]++;
        }
    }

    // A rename that matched nothing would silently produce a volume with no temperature grid,
    // which renders black and looks like a tuning problem. Fail loudly instead.
    int missed = 0;
    for (auto& r : renames)
        if (hits[r.first] == 0) { printf("ERROR: no grid named '%s' in %s\n", r.first.c_str(), argv[1]); missed++; }
    if (missed) return 2;

    openvdb::io::File out(argv[2]);
    out.write(*grids);
    out.close();
    printf("Wrote %s\n", argv[2]);
    return 0;
}
