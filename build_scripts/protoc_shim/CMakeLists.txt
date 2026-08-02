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

# ---------------------------------------------------------------------------------------------
# Restore the two DLLs that keep disappearing from the output directory.
#
# Falcor.dll imports libprotoc.dll and z.dll at LOAD time. Both go missing from bin/<config>/ after
# builds -- observed four separate times in one session, including after builds that touched neither.
# No CMake step here deletes them and deploycommon.bat has no /PURGE into that directory, so the
# cause is outside the build; an unsigned, hand-built DLL named after a well-known library is a
# textbook antivirus false positive, and z.dll is a renamed zlib.
#
# Rather than keep diagnosing it, restore them on EVERY build. When they are missing the process dies
# at 0xC0000135 before main() -- no log, no window, `--help` fails too -- which reads as a corrupt
# build and has already been misdiagnosed as a missing package, a render-pass regression and a
# driver fault.
#
# A custom target with no OUTPUT is always considered out of date, so this runs even when nothing
# else rebuilds. `copy_if_different` makes the normal case a no-op.
set(_zlib_src ${CMAKE_SOURCE_DIR}/external/packman/nv-usd-release/bin/zlib.dll)
add_custom_target(restore_runtime_dlls ALL
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:protoc_shim> ${FALCOR_OUTPUT_DIRECTORY}/libprotoc.dll
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${_zlib_src} ${FALCOR_OUTPUT_DIRECTORY}/z.dll
    DEPENDS protoc_shim
    COMMENT "Restoring libprotoc.dll and z.dll (Falcor imports both at load time)"
    VERBATIM
)
set_target_properties(restore_runtime_dlls PROPERTIES FOLDER "Misc")
