#pragma comment(lib, "cudart.lib") 

#include "OIDNCudaInterop.h"
#include <cuda_runtime.h>
#include <cstdio>

namespace OIDNCuda
{
    void* importSharedHandle(void* handle, size_t sizeBytes)
    {
        cudaExternalMemoryHandleDesc desc = {};
        desc.type = cudaExternalMemoryHandleTypeD3D12Resource;
        desc.size = sizeBytes; 
        desc.handle.win32.handle = handle;

        desc.flags = cudaExternalMemoryDedicated;

        cudaExternalMemory_t extMem = nullptr;
        cudaError_t err = cudaImportExternalMemory(&extMem, &desc);

        if (err != cudaSuccess) {
            printf("CUDA Error (Import): %s (Size: %llu)\n", cudaGetErrorString(err), sizeBytes);
            return nullptr;
        }
        return (void*)extMem;
    }

    void* mapBuffer(void* externalMem, size_t sizeBytes)
    {
        if (!externalMem) return nullptr;

        cudaExternalMemoryBufferDesc bufDesc = {};
        bufDesc.offset = 0;
        bufDesc.size = sizeBytes;

        void* devPtr = nullptr;
        cudaError_t err = cudaExternalMemoryGetMappedBuffer(&devPtr, (cudaExternalMemory_t)externalMem, &bufDesc);

        if (err != cudaSuccess) {
            printf("CUDA Error (Map): %s\n", cudaGetErrorString(err));
            return nullptr;
        }
        return devPtr;
    }

    void freeBuffer(void* devicePtr)
    {
        if (devicePtr) cudaFree(devicePtr);
    }

    void destroyExternalMemory(void* externalMem)
    {
        if (externalMem) cudaDestroyExternalMemory((cudaExternalMemory_t)externalMem);
    }

    void synchronize()
    {
        cudaDeviceSynchronize();
    }
}