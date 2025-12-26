#pragma once
#include <cstdint>

namespace OIDNCuda
{
    // Imports a Win32 Shared Handle from D3D12 into CUDA
    void* importSharedHandle(void* handle, size_t sizeBytes);

    // Maps the imported memory to a device pointer (float*)
    void* mapBuffer(void* externalMem, size_t sizeBytes);

    // Frees the mapped pointer
    void freeBuffer(void* devicePtr);

    // Destroys the external memory handle
    void destroyExternalMemory(void* externalMem);

    // Waits for the GPU to finish (cudaDeviceSynchronize)
    void synchronize();
}