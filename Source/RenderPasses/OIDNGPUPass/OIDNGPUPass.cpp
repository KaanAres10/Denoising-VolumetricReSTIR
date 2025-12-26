#include "OIDNGPUPass.h"
#include "OIDNCudaInterop.h" 
#include <d3d12.h>           
#include <wrl/client.h>


const char* OIDNGPUPass::kDesc = "Intel Open Image Denoise 2.x (CUDA Interop)";

static const std::string kSrc = "src";
static const std::string kDst = "dst";

static const std::string kConvertTexToBufFile = "RenderPasses/OIDNGPUPass/ConvertTexToBuf.cs.slang";
static const std::string kConvertBufToTexFile = "RenderPasses/OIDNGPUPass/ConvertBufToTex.ps.slang";

// dict keys
static const char kEnabled[] = "mEnabled";
static const char kQuality[] = "mQuality";
static const char kHdr[] = "mHdr";
static const char kSrgb[] = "mSrgb";
static const char kInputScale[] = "mInputScale";
static const char kCleanAux[] = "mCleanAux";
static const char kMaxMemMB[] = "mMaxMemoryMB";

extern "C" __declspec(dllexport) const char* getProjDir() { return PROJECT_DIR; }
extern "C" __declspec(dllexport) void getPasses(Falcor::RenderPassLibrary & lib) {
    lib.registerClass("OIDNGPUPass", OIDNGPUPass::kDesc, OIDNGPUPass::create);
}


OIDNGPUPass::SharedPtr OIDNGPUPass::create(RenderContext* pRenderContext, const Dictionary& dict) {
    return SharedPtr(new OIDNGPUPass(dict));
}

static oidn::Quality toOidnQuality(int q)
{
    switch (q)
    {
    default: return oidn::Quality::Default;
    case 1:  return oidn::Quality::Fast;
    case 2:  return oidn::Quality::Balanced;
    case 3:  return oidn::Quality::High;
    }
}

OIDNGPUPass::OIDNGPUPass(const Dictionary& dict) {
    mDevice = oidn::newDevice(oidn::DeviceType::CUDA);
    mDevice.commit();

    mFilter = mDevice.newFilter("RT");

    if (dict.keyExists(kEnabled))    mEnabled = (bool)dict[kEnabled];
    if (dict.keyExists(kHdr))        mHdr = (bool)dict[kHdr];
    if (dict.keyExists(kSrgb))       mSrgb = (bool)dict[kSrgb];
    if (dict.keyExists(kCleanAux))   mCleanAux = (bool)dict[kCleanAux];
    if (dict.keyExists(kQuality))    mQuality = (int)dict[kQuality];
    if (dict.keyExists(kMaxMemMB))   mMaxMemoryMB = (int)dict[kMaxMemMB];
    if (dict.keyExists(kInputScale)) mInputScale = (float)dict[kInputScale];

    mFilter.set("hdr", mHdr);
    mFilter.set("srgb", mSrgb);
    mFilter.set("cleanAux", mCleanAux);
    mFilter.set("quality", toOidnQuality(mQuality));
    if (!std::isnan(mInputScale))
        mFilter.set("inputScale", mInputScale);

    if (mMaxMemoryMB >= 0)
        mFilter.set("maxMemoryMB", mMaxMemoryMB);

    mFilter.commit(); 

    // shaders
    mpConvertTexToBuf = ComputePass::create(kConvertTexToBufFile, "main");
    mpConvertBufToTex = FullScreenPass::create(kConvertBufToTexFile);
    mpFbo = Fbo::create();
}

Dictionary OIDNGPUPass::getScriptingDictionary()
{
    Dictionary d;
    d[kEnabled] = mEnabled;
    d[kHdr] = mHdr;
    d[kSrgb] = mSrgb;
    d[kCleanAux] = mCleanAux;
    d[kQuality] = mQuality;
    d[kMaxMemMB] = mMaxMemoryMB;
    d[kInputScale] = mInputScale;
    return d;
}

RenderPassReflection OIDNGPUPass::reflect(const CompileData& compileData) {
    RenderPassReflection r;
    r.addInput(kSrc, "Input").format(ResourceFormat::RGBA32Float);
    r.addOutput(kDst, "Output").format(ResourceFormat::RGBA32Float);
    return r;
}

void OIDNGPUPass::releaseInterop() {
    // Use the Bridge functions to cleanup
    if (mCudaDevPtrIn) { OIDNCuda::freeBuffer(mCudaDevPtrIn); mCudaDevPtrIn = nullptr; }
    if (mCudaDevPtrOut) { OIDNCuda::freeBuffer(mCudaDevPtrOut); mCudaDevPtrOut = nullptr; }

    if (mExtMemIn) { OIDNCuda::destroyExternalMemory(mExtMemIn); mExtMemIn = nullptr; }
    if (mExtMemOut) { OIDNCuda::destroyExternalMemory(mExtMemOut); mExtMemOut = nullptr; }
}

using Microsoft::WRL::ComPtr;

void OIDNGPUPass::initInterop(RenderContext* pCtx, uint32_t width, uint32_t height) {
    if (mFrameDim.x == width && mFrameDim.y == height && mInputBuf) return;

    releaseInterop();
    mFrameDim = { width, height };

    ID3D12Device* d3d12Device = (ID3D12Device*)gpDevice->getApiHandle();

    uint32_t numPixels = width * height;
    size_t logicalSize = numPixels * 4 * sizeof(float);

    size_t alignedWidth = (logicalSize + 65535) & ~65535;

    D3D12_RESOURCE_DESC desc = {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Alignment = 0;
    desc.Width = alignedWidth;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = DXGI_FORMAT_UNKNOWN;
    desc.SampleDesc.Count = 1;
    desc.SampleDesc.Quality = 0;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;

    D3D12_RESOURCE_ALLOCATION_INFO allocInfo = d3d12Device->GetResourceAllocationInfo(0, 1, &desc);
    size_t physicalSize = allocInfo.SizeInBytes;

    D3D12_HEAP_PROPERTIES heapProps = {};
    heapProps.Type = D3D12_HEAP_TYPE_DEFAULT;
    heapProps.CreationNodeMask = 1;
    heapProps.VisibleNodeMask = 1;

    Microsoft::WRL::ComPtr<ID3D12Resource> d3dIn, d3dOut;

    // Input
    HRESULT hr = d3d12Device->CreateCommittedResource(
        &heapProps,
        D3D12_HEAP_FLAG_SHARED,
        &desc,
        D3D12_RESOURCE_STATE_COMMON,
        nullptr,
        IID_PPV_ARGS(&d3dIn)
    );
    if (FAILED(hr)) { logError("Failed to create Input Buffer"); return; }

    // Output
    hr = d3d12Device->CreateCommittedResource(
        &heapProps,
        D3D12_HEAP_FLAG_SHARED,
        &desc,
        D3D12_RESOURCE_STATE_COMMON,
        nullptr,
        IID_PPV_ARGS(&d3dOut)
    );
    if (FAILED(hr)) { logError("Failed to create Output Buffer"); return; }

 
    mInputBuf = Buffer::createFromApiHandle(
        d3dIn.Get(), alignedWidth,
        Resource::BindFlags::ShaderResource | Resource::BindFlags::UnorderedAccess,
        Buffer::CpuAccess::None
    );

    mOutputBuf = Buffer::createFromApiHandle(
        d3dOut.Get(), alignedWidth,
        Resource::BindFlags::ShaderResource | Resource::BindFlags::UnorderedAccess,
        Buffer::CpuAccess::None
    );

    HANDLE handleIn = nullptr;
    HANDLE handleOut = nullptr;

    d3d12Device->CreateSharedHandle(d3dIn.Get(), nullptr, GENERIC_ALL, nullptr, &handleIn);
    d3d12Device->CreateSharedHandle(d3dOut.Get(), nullptr, GENERIC_ALL, nullptr, &handleOut);

    mExtMemIn = OIDNCuda::importSharedHandle(handleIn, physicalSize);
    mExtMemOut = OIDNCuda::importSharedHandle(handleOut, physicalSize);

    if (mExtMemIn && mExtMemOut) {
        mCudaDevPtrIn = OIDNCuda::mapBuffer(mExtMemIn, alignedWidth);
        mCudaDevPtrOut = OIDNCuda::mapBuffer(mExtMemOut, alignedWidth);
    }
    else {
        logError("Failed to map D3D12 resources to CUDA.");
    }

    CloseHandle(handleIn);
    CloseHandle(handleOut);
}
void OIDNGPUPass::execute(RenderContext* pRenderContext, const RenderData& renderData) {
    auto pSrc = renderData[kSrc]->asTexture();
    auto pDst = renderData[kDst]->asTexture();
    if (!pSrc || !pDst) return;

    uint32_t width = pSrc->getWidth();
    uint32_t height = pSrc->getHeight();

    initInterop(pRenderContext, width, height);
    if (!mCudaDevPtrIn || !mCudaDevPtrOut) return;

    auto vars = mpConvertTexToBuf->getVars();
    vars["GlobalCB"]["gStride"] = width;
    vars["gInTex"] = pSrc;
    vars["gOutBuf"] = mInputBuf;
    mpConvertTexToBuf->execute(pRenderContext, width, height);

    pRenderContext->flush(true);

    // CUDA: Run OIDN
    mFilter.setImage("color", mCudaDevPtrIn, oidn::Format::Float3, width, height, 0, 16);
    mFilter.setImage("output", mCudaDevPtrOut, oidn::Format::Float3, width, height, 0, 16);
    mFilter.commit();
    mFilter.execute();

    // Sync via Bridge
    OIDNCuda::synchronize();

    auto outVars = mpConvertBufToTex->getVars();
    outVars["GlobalCB"]["gStride"] = width;
    outVars["gInBuf"] = mOutputBuf;
    mpFbo->attachColorTarget(pDst, 0);
    mpConvertBufToTex->execute(pRenderContext, mpFbo);
}
