cbuffer GlobalCB { uint gStride; };
Texture2D<float4> gInTex;

// FIX: Use float (scalar) buffer to avoid stride ambiguity
RWStructuredBuffer<float> gOutBuf; 

[numthreads(16, 16, 1)]
void main(uint3 dispatchThreadId : SV_DispatchThreadID) {
    uint2 pos = dispatchThreadId.xy;
    uint width, height;
    gInTex.GetDimensions(width, height);
    
    if (pos.x >= width || pos.y >= height) return;
    
    float4 color = gInTex[pos];

    // Calculate base index for 4 floats per pixel
    uint baseIndex = (pos.y * gStride + pos.x) * 4;

    gOutBuf[baseIndex + 0] = color.r;
    gOutBuf[baseIndex + 1] = color.g;
    gOutBuf[baseIndex + 2] = color.b;
    gOutBuf[baseIndex + 3] = color.a;
}