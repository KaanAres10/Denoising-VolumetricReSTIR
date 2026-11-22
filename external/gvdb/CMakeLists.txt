# GVDB Voxels (the library from NVIDIA's gvdb-voxels, with the fork's custom .vbx fields), for Falcor's volume loader
# on Linux. Windows links the prebuilt SDK instead, see Source/Falcor/CMakeLists.txt.
#
# Falcor only takes the CPU-only path, Initialize(true) + LoadVBX(path, true), so the CUDA kernels (PTX) are not built
# and OpenVDB is left out. The library still links CUDA and OpenGL, which the rest of its code refers to.
find_package(OpenGL REQUIRED)
find_package(X11 REQUIRED)

add_library(gvdb SHARED
    src/app_perf.cpp
    src/gvdb_allocator.cpp
    src/gvdb_camera.cpp
    src/gvdb_cutils.cu
    src/gvdb_model.cpp
    src/gvdb_node.cpp
    src/gvdb_render_opengl.cpp
    src/gvdb_scene.cpp
    src/gvdb_types.cpp
    src/gvdb_vec.cpp
    src/gvdb_volume_3D.cpp
    src/gvdb_volume_base.cpp
    src/gvdb_volume_gvdb.cpp
    src/loader_ObjarReader.cpp
    src/loader_OBJReader.cpp
    src/loader_Parser.cpp
    src/string_helper.cpp
    glew/src/glew.c
)

set(FALCOR_GVDB_INCLUDE_DIRS
    "${CMAKE_CURRENT_SOURCE_DIR}/src;${CMAKE_CURRENT_SOURCE_DIR}/kernels;${CUDAToolkit_INCLUDE_DIRS}"
    CACHE INTERNAL "Headers SceneGVDB.cpp compiles against")

target_include_directories(gvdb PRIVATE ${FALCOR_GVDB_INCLUDE_DIRS} glew/include)
target_compile_definitions(gvdb PRIVATE GVDB_SKIP_OPENVDB BUILD_OPENGL GVDB_EXPORTS GLEW_STATIC GLEW_NO_GLU
    # Names of the kernel modules, which the GPU path would load; it is never taken here.
    CUDA_GVDB_MODULE_PTX="cuda_gvdb_module.ptx"
    CUDA_GVDB_COPYDATA_PTX="cuda_gvdb_copydata.ptx")
target_compile_options(gvdb PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:-D_GLIBCXX_USE_CXX11_ABI=0>)
target_link_libraries(gvdb PRIVATE CUDA::cuda_driver OpenGL::GL ${X11_LIBRARIES})

set_target_properties(gvdb PROPERTIES
    CXX_STANDARD 11
    CUDA_STANDARD 14
    CUDA_RUNTIME_LIBRARY Static
    LIBRARY_OUTPUT_DIRECTORY ${FALCOR_LIBRARY_OUTPUT_DIRECTORY}
    FOLDER "Libraries"
)
