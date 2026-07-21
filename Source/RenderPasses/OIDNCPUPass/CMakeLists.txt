if(NOT FALCOR_HAS_OIDN)
    return()
endif()

add_plugin(OIDNCPUPass)

target_sources(OIDNCPUPass PRIVATE
    OIDNCPUPass.cpp
    OIDNCPUPass.h
    ConvertTexToBuf.cs.slang
    ConvertBufToTex.ps.slang
)

target_copy_shaders(OIDNCPUPass RenderPasses/OIDNCPUPass)

target_link_libraries(OIDNCPUPass PRIVATE oidn)

target_source_group(OIDNCPUPass "RenderPasses")

# Copy the OIDN runtime DLLs (main + core + CPU device backend + TBB) next to the executables.
set(_oidn_cpu_dlls
    OpenImageDenoise.dll
    OpenImageDenoise_core.dll
    OpenImageDenoise_device_cpu.dll
    tbb12.dll
)
foreach(_dll ${_oidn_cpu_dlls})
    if(EXISTS "${FALCOR_OIDN_BIN_DIR}/${_dll}")
        add_custom_command(TARGET OIDNCPUPass POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${FALCOR_OIDN_BIN_DIR}/${_dll}" "${FALCOR_OUTPUT_DIRECTORY}/${_dll}"
        )
    endif()
endforeach()
