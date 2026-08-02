# Builds libprotoc.dll containing only the sized-operator-delete that Falcor.dll imports.
# See protoc_shim.cpp for why this is needed and when it can be deleted.
#
# Guarded: if a real libprotoc.dll is ever present in the dependency set, do not build over it.
find_file(FALCOR_REAL_LIBPROTOC
    NAMES libprotoc.dll
    PATHS
        ${CMAKE_SOURCE_DIR}/external/packman/deps/bin
        ${CMAKE_SOURCE_DIR}/external/packman/nv-usd-release/bin
        ${CMAKE_SOURCE_DIR}/external/packman/nv-usd-release/lib
    NO_DEFAULT_PATH
)

if(FALCOR_REAL_LIBPROTOC)
    message(STATUS "protoc_shim: skipped, a real libprotoc.dll is available (${FALCOR_REAL_LIBPROTOC})")
    return()
endif()

add_library(protoc_shim SHARED protoc_shim.cpp)

set_target_properties(protoc_shim
    PROPERTIES
        # The import binds by the name Falcor was linked against, so the file has to be called
        # exactly libprotoc.dll and has to sit next to the executable -- the loader searches the
        # executable's directory, not plugins/.
        OUTPUT_NAME "libprotoc"
        PREFIX ""
        # Bare RUNTIME_OUTPUT_DIRECTORY only -- with a multi-config generator CMake appends the
        # config subdirectory itself, and setting the per-config variants would suppress that and
        # drop the DLL in bin/ instead of bin/Release/. Same pattern as the rest of the build.
        RUNTIME_OUTPUT_DIRECTORY ${FALCOR_RUNTIME_OUTPUT_DIRECTORY}
)

target_link_options(protoc_shim PRIVATE "/EXPORT:?__global_delete@@YAXPEAX_K@Z")
