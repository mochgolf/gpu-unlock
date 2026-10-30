// SPDX-License-Identifier: GPL-2.0-only
// Dense register-resident instruction throughput. No firmware or MMIO access.
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

#define CUDA_OK(call) do { cudaError_t e = (call); if (e != cudaSuccess) { \
    fprintf(stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #call, cudaGetErrorString(e)); \
    std::exit(2); } } while (0)

// All source elements are 2^-6, nonzero and exactly representable.
// K=32 therefore adds 2^-7; K=16 adds 2^-8 to each accumulator element.
enum Input { E4M3, E5M2, F16, BF16 };
template<Input I> __device__ unsigned packed_input() {
    if constexpr (I == E4M3) return 0x08080808u;
    if constexpr (I == E5M2) return 0x24242424u;
    if constexpr (I == F16) return 0x24002400u;
    return 0x3c803c80u;
}

template<Input I> __device__ __forceinline__ void mma32(float (&d)[4], unsigned a, unsigned b) {
#define MMA32(shape, types) asm volatile( \
    "mma.sync.aligned." shape ".row.col.f32." types ".f32 " \
    "{%0,%1,%2,%3}, {%4,%4,%4,%4}, {%5,%5}, {%0,%1,%2,%3};" \
    : "+f"(d[0]), "+f"(d[1]), "+f"(d[2]), "+f"(d[3]) : "r"(a), "r"(b))
    if constexpr (I == E4M3) { MMA32("m16n8k32", "e4m3.e4m3"); }
    else if constexpr (I == E5M2) { MMA32("m16n8k32", "e5m2.e5m2"); }
    else if constexpr (I == F16) { MMA32("m16n8k16", "f16.f16"); }
    else { MMA32("m16n8k16", "bf16.bf16"); }
#undef MMA32
}

template<Input I> __device__ __forceinline__ void mma16(unsigned (&d)[2], unsigned a, unsigned b) {
#define MMA16(shape, types) asm volatile( \
    "mma.sync.aligned." shape ".row.col.f16." types ".f16 " \
    "{%0,%1}, {%2,%2,%2,%2}, {%3,%3}, {%0,%1};" \
    : "+r"(d[0]), "+r"(d[1]) : "r"(a), "r"(b))
    if constexpr (I == E4M3) { MMA16("m16n8k32", "e4m3.e4m3"); }
    else if constexpr (I == E5M2) { MMA16("m16n8k32", "e5m2.e5m2"); }
    else { MMA16("m16n8k16", "f16.f16"); }
#undef MMA16
}

__device__ __forceinline__ unsigned long long global_ns() {
    unsigned long long value;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(value));
    return value;
}

struct BlockClock { unsigned long long cycles, ns; };

template<Input I, bool HalfAcc, int Chains, bool Capture>
__global__ void kernel(int iters, float *sink, BlockClock *clocks) {
    const unsigned a = packed_input<I>(), b = packed_input<I>();
    float c32[Chains][4];
    unsigned c16[Chains][2];
#pragma unroll
    for (int j = 0; j < Chains; ++j) {
        const float seed = float(j) / 32.0f;
        if constexpr (HalfAcc) {
            unsigned short h = __half_as_ushort(__float2half_rn(seed));
            c16[j][0] = c16[j][1] = unsigned(h) | (unsigned(h) << 16);
        } else {
#pragma unroll
            for (int k = 0; k < 4; ++k) c32[j][k] = seed;
        }
    }
    unsigned long long c0 = 0, t0 = 0;
    if (threadIdx.x == 0) { t0 = global_ns(); c0 = clock64(); }
    __syncthreads();
    for (int it = 0; it < iters; ++it) {
#pragma unroll
        for (int j = 0; j < Chains; ++j) {
            if constexpr (HalfAcc) mma16<I>(c16[j], a, b);
            else mma32<I>(c32[j], a, b);
        }
    }
    __syncthreads();
    if (threadIdx.x == 0) {
        const unsigned long long c1 = clock64(), t1 = global_ns();
        clocks[blockIdx.x] = {c1-c0, t1-t0};
    }
    float checksum = 0;
    const size_t thread = size_t(blockIdx.x) * blockDim.x + threadIdx.x;
#pragma unroll
    for (int j = 0; j < Chains; ++j) {
#pragma unroll
        for (int k = 0; k < 4; ++k) {
            float value;
            if constexpr (HalfAcc) {
                const unsigned word = c16[j][k/2];
                value = __half2float(__ushort_as_half((word >> (16*(k%2))) & 0xffff));
            } else value = c32[j][k];
            checksum += value;
            if constexpr (Capture) sink[(thread*Chains+j)*4+k] = value;
        }
    }
    if constexpr (!Capture) sink[thread] = checksum;
}

template<int Chains> void launch(int mode, bool capture, int iters, int blocks, int threads,
                                 float *sink, BlockClock *clocks) {
#define LAUNCH(I, H) do { \
    if (capture) kernel<I,H,Chains,true><<<blocks,threads>>>(iters,sink,clocks); \
    else kernel<I,H,Chains,false><<<blocks,threads>>>(iters,sink,clocks); \
} while (0)
    switch (mode) {
        case 0: LAUNCH(E4M3,false); break;
        case 1: LAUNCH(E5M2,false); break;
        case 2: LAUNCH(E4M3,true); break;
        case 3: LAUNCH(E5M2,true); break;
        case 4: LAUNCH(BF16,false); break;
        case 5: LAUNCH(F16,false); break;
        case 6: LAUNCH(F16,true); break;
        default: std::exit(3);
    }
    CUDA_OK(cudaGetLastError());
#undef LAUNCH
}

void dispatch(int chains, int mode, bool capture, int iters, int blocks, int threads,
              float *sink, BlockClock *clocks) {
    if (chains == 4) launch<4>(mode,capture,iters,blocks,threads,sink,clocks);
    else if (chains == 8) launch<8>(mode,capture,iters,blocks,threads,sink,clocks);
    else if (chains == 16) launch<16>(mode,capture,iters,blocks,threads,sink,clocks);
    else std::exit(4);
}

int main(int argc, char **argv) {
    const int iters = argc > 1 ? std::atoi(argv[1]) : 20000;
    const int reps = argc > 2 ? std::atoi(argv[2]) : 21;
    const int chains = argc > 3 ? std::atoi(argv[3]) : 8;
    if (iters < 1 || iters > 100000 || reps < 1 || reps > 100 ||
        (chains != 4 && chains != 8 && chains != 16)) return 4;
    setvbuf(stdout,nullptr,_IOLBF,0);
    constexpr int blocks = 1056, threads = 256;
    const char *names[] = {"e4m3/f32","e5m2/f32","e4m3/f16","e5m2/f16","bf16/f32","f16/f32","f16/f16"};
    cudaDeviceProp prop;
    CUDA_OK(cudaGetDeviceProperties(&prop,0));
    if (prop.major != 8 || prop.minor != 9 || prop.multiProcessorCount != 128) {
        fprintf(stderr,"Expected tested AD102 with 128 SMs\n"); return 5;
    }
    printf("{\"type\":\"metadata\",\"device\":\"%s\",\"sms\":%d,\"sm\":89,\"iters\":%d,\"reps\":%d,\"chains\":%d,\"blocks\":%d,\"threads\":%d,\"dense\":true,\"ops_per_mac\":2,\"input_value\":0.015625}\n",
           prop.name,prop.multiProcessorCount,iters,reps,chains,blocks,threads);
    float *sink;
    BlockClock *clocks;
    CUDA_OK(cudaMalloc(&sink,blocks*threads*sizeof(float)));
    CUDA_OK(cudaMalloc(&clocks,blocks*sizeof(BlockClock)));
    // Read every lane, chain, and output element for short exact-reference checks.
    for (int mode = 0; mode < 7; ++mode) {
        for (int n : {1,2,32}) {
            dispatch(chains,mode,true,n,1,32,sink,clocks);
            CUDA_OK(cudaDeviceSynchronize());
            std::vector<float> result(32*chains*4);
            CUDA_OK(cudaMemcpy(result.data(),sink,result.size()*sizeof(float),cudaMemcpyDeviceToHost));
            const float increment = mode < 4 ? 1.0f/128 : 1.0f/256;
            double max_error = 0;
            for (int lane = 0; lane < 32; ++lane) for (int j = 0; j < chains; ++j) for (int k = 0; k < 4; ++k) {
                const float actual = result[(lane*chains+j)*4+k];
                const float expected = float(j)/32 + n*increment;
                if (!std::isfinite(actual) || actual != expected) {
                    fprintf(stderr,"Reference failure: mode=%s n=%d lane=%d chain=%d elem=%d actual=%g expected=%g\n",names[mode],n,lane,j,k,actual,expected);
                    return 6;
                }
                max_error = std::max(max_error,double(std::abs(actual-expected)));
            }
            printf("{\"type\":\"validation\",\"mode\":\"%s\",\"iters\":%d,\"elements\":%zu,\"max_abs_error\":%.9g,\"passed\":true}\n",names[mode],n,result.size(),max_error);
        }
    }
    // Warm the card before sampling. This does not change clock or power settings.
    for (int w = 0; w < 80; ++w) {
        dispatch(chains,w%7,false,10000,blocks,threads,sink,clocks);
        CUDA_OK(cudaDeviceSynchronize());
    }
    cudaEvent_t start,stop;
    CUDA_OK(cudaEventCreate(&start)); CUDA_OK(cudaEventCreate(&stop));
    std::vector<BlockClock> times(blocks);
    std::vector<float> sums(blocks*threads);
    for (int rep = 0; rep < reps; ++rep) {
        for (int step = 0; step < 7; ++step) {
            const int mode = rep%2 ? (rep+6-step)%7 : (rep+step)%7;
            CUDA_OK(cudaEventRecord(start));
            dispatch(chains,mode,false,iters,blocks,threads,sink,clocks);
            CUDA_OK(cudaEventRecord(stop)); CUDA_OK(cudaEventSynchronize(stop));
            float ms; CUDA_OK(cudaEventElapsedTime(&ms,start,stop));
            if (!(ms > 0)) return 7;
            CUDA_OK(cudaMemcpy(times.data(),clocks,blocks*sizeof(BlockClock),cudaMemcpyDeviceToHost));
            CUDA_OK(cudaMemcpy(sums.data(),sink,sums.size()*sizeof(float),cudaMemcpyDeviceToHost));
            for (float value:sums) if (!std::isfinite(value)) {
                fprintf(stderr,"Nonfinite timed checksum\n"); return 8;
            }
            std::vector<double> mhz;
            for (auto t:times) if (t.ns) mhz.push_back(1000.0*double(t.cycles)/double(t.ns));
            std::sort(mhz.begin(),mhz.end());
            const double clock_mhz = mhz[mhz.size()/2];
            const double ops = double(blocks)*(threads/32)*iters*chains*(mode < 4 ? 8192 : 4096);
            const double tflops = ops/(double(ms)*1e9);
            printf("{\"type\":\"sample\",\"mode\":\"%s\",\"rep\":%d,\"step\":%d,\"ms\":%.9g,\"tflops\":%.9g,\"block_clock_mhz_median\":%.9g,\"flops_per_sm_cycle\":%.9g,\"finite\":true}\n",
                   names[mode],rep,step,ms,tflops,clock_mhz,tflops*1e6/(prop.multiProcessorCount*clock_mhz));
        }
    }
    CUDA_OK(cudaEventDestroy(start)); CUDA_OK(cudaEventDestroy(stop));
    CUDA_OK(cudaFree(sink)); CUDA_OK(cudaFree(clocks));
    CUDA_OK(cudaDeviceSynchronize());
    printf("{\"type\":\"complete\",\"passed\":true}\n");
    return 0;
}
