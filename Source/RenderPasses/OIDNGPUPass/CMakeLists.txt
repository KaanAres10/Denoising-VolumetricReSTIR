if(NOT (FALCOR_HAS_OIDN AND FALCOR_HAS_CUDA))
    return()
endif()

add_plugin(OIDNGPUPass)

target_sources(OIDNGPUPass PRIVATE
    OIDNGPUPass.cpp
    OIDNGPUPass.h
    ConvertTexToBuf.cs.slang
    ConvertBufToTex.ps.slang
)

target_copy_shaders(OIDNGPUPass RenderPasses/OIDNGPUPass)

target_link_libraries(OIDNGPUPass PRIVATE oidn)

target_source_group(OIDNGPUPass "RenderPasses")

# Copy the OIDN runtime DLLs (main + core + CUDA device backend + TBB) next to the executables.
set(_oidn_gpu_dlls
    OpenImageDenoise.dll
    OpenImageDenoise_core.dll
    OpenImageDenoise_device_cuda.dll
    tbb12.dll
)
foreach(_dll ${_oidn_gpu_dlls})
    if(EXISTS "${FALCOR_OIDN_BIN_DIR}/${_dll}")
        add_custom_command(TARGET OIDNGPUPass POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${FALCOR_OIDN_BIN_DIR}/${_dll}" "${FALCOR_OUTPUT_DIRECTORY}/${_dll}"
        )
    endif()
endforeach()
