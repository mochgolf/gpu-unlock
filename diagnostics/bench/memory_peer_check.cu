// SPDX-License-Identifier: GPL-2.0-only
// Bounded expanded-address and bidirectional peer-copy validation.
// 28 GiB is logical CUDA allocation coverage, not proof of physical DRAM mapping.
#include <cuda_runtime.h>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static void ck(cudaError_t e){if(e!=cudaSuccess)throw std::runtime_error(cudaGetErrorString(e));}
__device__ static uint64_t pattern(uint64_t i,uint64_t seed){uint64_t x=i^seed;x^=x>>30;x*=0xbf58476d1ce4e5b9ULL;x^=x>>27;x*=0x94d049bb133111ebULL;return x^(x>>31);}
__global__ static void fill(uint64_t* a,uint64_t count,uint64_t seed){for(uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;i<count;i+=uint64_t(gridDim.x)*blockDim.x)a[i]=pattern(i,seed);}
__global__ static void verify(const uint64_t* a,uint64_t count,uint64_t seed,unsigned long long* errors){for(uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;i<count;i+=uint64_t(gridDim.x)*blockDim.x)if(a[i]!=pattern(i,seed))atomicAdd(errors,1ULL);}
static void write_pattern(uint64_t* a,uint64_t count,uint64_t seed){fill<<<4096,256>>>(a,count,seed);ck(cudaGetLastError());ck(cudaDeviceSynchronize());}
static unsigned long long validate(uint64_t* a,uint64_t count,uint64_t seed){unsigned long long *errors=nullptr,result=0;ck(cudaMalloc((void**)&errors,8));ck(cudaMemset(errors,0,8));verify<<<4096,256>>>(a,count,seed,errors);ck(cudaGetLastError());ck(cudaDeviceSynchronize());ck(cudaMemcpy(&result,errors,8,cudaMemcpyDeviceToHost));ck(cudaFree(errors));return result;}
static void enable_peer(int from,int to){ck(cudaSetDevice(from));auto e=cudaDeviceEnablePeerAccess(to,0);if(e!=cudaErrorPeerAccessAlreadyEnabled)ck(e);else cudaGetLastError();}

int main(int argc,char** argv){try{
    if(argc!=2 || (std::string(argv[1])!="expanded"&&std::string(argv[1])!="peer"))throw std::runtime_error("usage: memory_peer_check expanded|peer (CUDA_VISIBLE_DEVICES must pin UUID order)");
    std::string mode=argv[1];int devices=0;ck(cudaGetDeviceCount(&devices));
    if((mode=="expanded"&&devices!=1)||(mode=="peer"&&devices!=2))throw std::runtime_error("incorrect visible-device count");
    const size_t bytes=28ULL*1024*1024*1024;const uint64_t words=bytes/8;unsigned long long errors=0;
    ck(cudaSetDevice(0));cudaDeviceProp p0{};ck(cudaGetDeviceProperties(&p0,0));size_t free0=0,total0=0;ck(cudaMemGetInfo(&free0,&total0));
    if(free0<bytes+2ULL*1024*1024*1024)throw std::runtime_error("insufficient free memory for bounded 28 GiB test");
    uint64_t* a=nullptr;ck(cudaMalloc((void**)&a,bytes));
    if(mode=="expanded"){
        for(uint64_t seed: {0x0123456789abcdefULL,0xfedcba9876543210ULL}){write_pattern(a,words,seed);errors+=validate(a,words,seed);}
        ck(cudaFree(a));std::cout<<"{\"mode\":\"expanded\",\"logical_bytes\":"<<bytes<<",\"passes\":2,\"mismatched_words\":"<<errors<<",\"pass\":"<<(errors?"false":"true")<<",\"limit\":\"logical CUDA address coverage; not physical DRAM mapping proof\"}"<<std::endl;return errors?2:0;
    }
    int forward=0,reverse=0;ck(cudaDeviceCanAccessPeer(&forward,0,1));ck(cudaDeviceCanAccessPeer(&reverse,1,0));if(!forward||!reverse)throw std::runtime_error("bidirectional peer capability missing");
    ck(cudaSetDevice(1));size_t free1=0,total1=0;ck(cudaMemGetInfo(&free1,&total1));if(free1<bytes+2ULL*1024*1024*1024)throw std::runtime_error("insufficient peer memory");
    uint64_t* b=nullptr;ck(cudaMalloc((void**)&b,bytes));enable_peer(0,1);enable_peer(1,0);
    for(int direction=0;direction<2;direction++){
        const int src=direction,dst=1-direction;uint64_t* source=direction?b:a;uint64_t* destination=direction?a:b;
        uint64_t seed=direction?0x3141592653589793ULL:0x2718281828459045ULL;
        ck(cudaSetDevice(src));write_pattern(source,words,seed);errors+=validate(source,words,seed);
        ck(cudaSetDevice(dst));ck(cudaMemset(destination,0,bytes));ck(cudaDeviceSynchronize());
        ck(cudaMemcpyPeer(destination,dst,source,src,bytes));ck(cudaDeviceSynchronize());errors+=validate(destination,words,seed);
    }
    ck(cudaSetDevice(1));ck(cudaFree(b));ck(cudaSetDevice(0));ck(cudaFree(a));
    std::cout<<"{\"mode\":\"peer\",\"logical_bytes_per_direction\":"<<bytes<<",\"directions\":2,\"peer_capability\":true,\"mismatched_words\":"<<errors<<",\"pass\":"<<(errors?"false":"true")<<",\"limit\":\"CUDA peer-copy correctness; no interconnect bandwidth or no-staging proof\"}"<<std::endl;return errors?2:0;
}catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}}
