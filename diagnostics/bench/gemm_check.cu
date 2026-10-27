// SPDX-License-Identifier: GPL-2.0-only
// Frozen finite-normal validation for the existing A/B contract.
// CPU reference consumes the exact same quantized inputs; no GPU result defines tolerance.
#include <cuda_runtime.h>
#include <cuda_bf16.h>
#include <cuda_fp16.h>
#include <cublas_v2.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

static void ck(cudaError_t e) { if (e != cudaSuccess) throw std::runtime_error(cudaGetErrorString(e)); }
static void cb(cublasStatus_t e) { if(e != CUBLAS_STATUS_SUCCESS) throw std::runtime_error("cuBLAS error " + std::to_string(e)); }
static uint32_t mix(uint32_t x) { x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; return x ^ (x >> 16); }
static float random_value(uint32_t index, uint32_t seed) { return (int(mix(index ^ seed) % 2049) - 1024) / 1024.f; }
template<class T> static T quant(float x) { if constexpr (std::is_same<T,__nv_bfloat16>::value) return __float2bfloat16_rn(x); else return __float2half_rn(x); }
template<class T> static float value(T x) { if constexpr (std::is_same<T,__nv_bfloat16>::value) return __bfloat162float(x); else return __half2float(x); }
static double gamma_n(int n, double u) { return (n*u)/(1-n*u); }
static double budget(int k, double abs_sum) { return (gamma_n(2*k,std::ldexp(1.,-23))+gamma_n(2*k,std::ldexp(1.,-53)))*abs_sum; }

template<class T> int run(const std::string& dtype, const std::string& pattern, int m, int n, int k, const std::string& output) {
    const size_t as = size_t(m)*k, bs = size_t(k)*n, cs = size_t(m)*n;
    std::vector<T> a(as), b(bs);
    auto fill = [&](bool is_a, size_t idx, int row, int col) {
        float x = random_value(uint32_t(idx),is_a?0x9e3779b9U:0x243f6a88U);
        if(pattern=="zero" && is_a) x=0;
        if(pattern=="identity" && is_a) x=(row==col?1.f:0.f);
        if(pattern=="dyadic") x=(is_a?((row+col)%7-3):((row*3+col)%5-2))*.125f;
        if(pattern=="cancellation") x=is_a?((col&1)?-.0625f:.0625f):.25f;
        if(pattern=="long") x=std::ldexp(1.f,-12);
        if(pattern=="sentinel") x=1.f+std::ldexp(1.f,std::is_same<T,__nv_bfloat16>::value?-7:-10);
        return quant<T>(x);
    };
    for(int t=0;t<k;t++) for(int i=0;i<m;i++) a[size_t(i)+size_t(t)*m]=fill(true,size_t(i)+size_t(t)*m,i,t);
    for(int j=0;j<n;j++) for(int t=0;t<k;t++) b[size_t(t)+size_t(j)*k]=fill(false,size_t(t)+size_t(j)*k,t,j);
    T *da=nullptr,*db=nullptr; float* dc=nullptr; void* workspace=nullptr;
    ck(cudaMalloc((void**)&da,as*sizeof(T))); ck(cudaMalloc((void**)&db,bs*sizeof(T)));
    ck(cudaMalloc((void**)&dc,cs*sizeof(float))); ck(cudaMalloc(&workspace,16*1024*1024));
    ck(cudaMemcpy(da,a.data(),as*sizeof(T),cudaMemcpyHostToDevice));
    ck(cudaMemcpy(db,b.data(),bs*sizeof(T),cudaMemcpyHostToDevice));
    cudaStream_t stream; ck(cudaStreamCreateWithFlags(&stream,cudaStreamNonBlocking));
    cublasHandle_t h; cb(cublasCreate(&h)); cb(cublasSetStream(h,stream));
    cb(cublasSetWorkspace(h,workspace,16*1024*1024));
    cb(cublasSetPointerMode(h,CUBLAS_POINTER_MODE_HOST));
    cb(cublasSetAtomicsMode(h,CUBLAS_ATOMICS_NOT_ALLOWED));
    cb(cublasSetMathMode(h,static_cast<cublasMath_t>(CUBLAS_DEFAULT_MATH|CUBLAS_MATH_DISALLOW_REDUCED_PRECISION_REDUCTION)));
    int version=0; cb(cublasGetVersion(h,&version));
    auto type=std::is_same<T,__nv_bfloat16>::value?CUDA_R_16BF:CUDA_R_16F;
    float alpha=1,beta=0;
    auto gemm=[&](){ cb(cublasGemmEx(h,CUBLAS_OP_N,CUBLAS_OP_N,m,n,k,&alpha,
        da,type,m,db,type,k,&beta,dc,CUDA_R_32F,m,CUBLAS_COMPUTE_32F,CUBLAS_GEMM_DEFAULT_TENSOR_OP)); ck(cudaPeekAtLastError()); };
    for(int i=0;i<3;i++) gemm(); ck(cudaStreamSynchronize(stream));
    std::vector<float> first(cs),last(cs); ck(cudaMemcpy(first.data(),dc,cs*sizeof(float),cudaMemcpyDeviceToHost));
    cudaEvent_t start,stop; ck(cudaEventCreate(&start));ck(cudaEventCreate(&stop));
    std::vector<double> event_ms,wall_ms;
    for(int repeat=0;repeat<10;repeat++) {
        auto begin=std::chrono::steady_clock::now(); ck(cudaEventRecord(start,stream));gemm();ck(cudaEventRecord(stop,stream));ck(cudaEventSynchronize(stop));
        auto end=std::chrono::steady_clock::now();float ms=0;ck(cudaEventElapsedTime(&ms,start,stop));
        event_ms.push_back(ms);wall_ms.push_back(std::chrono::duration<double,std::milli>(end-begin).count());
    }
    ck(cudaMemcpy(last.data(),dc,cs*sizeof(float),cudaMemcpyDeviceToHost));
    size_t nonfinite=0;for(float x:last) if(!std::isfinite(x)) nonfinite++;
    size_t checked=0,bound_fail=0,exact_fail=0,negative_reject=0;double max_abs=0,max_ratio=0,sqerr=0,sqref=0;
    const size_t points=cs<=65536?cs:256;
    for(size_t sample=0;sample<points;sample++) {
        const size_t pos=cs<=65536?sample:(size_t(mix(uint32_t(sample)^0xa4093822U))%cs);
        const int i=int(pos%size_t(m)),j=int(pos/size_t(m));double ref=0,abs_sum=0;
        for(int t=0;t<k;t++) { double p=double(value(a[size_t(i)+size_t(t)*m]))*double(value(b[size_t(t)+size_t(j)*k]));ref+=p;abs_sum+=std::abs(p); }
        double limit=budget(k,abs_sum),error=std::abs(double(last[pos])-ref);checked++;
        if(!std::isfinite(last[pos]) || error>limit) bound_fail++;
        if(pattern=="zero" || pattern=="dyadic" || pattern=="cancellation" || pattern=="long" || pattern=="sentinel") {
            double analytic=ref;
            if(pattern=="zero" || pattern=="cancellation") analytic=0;
            if(pattern=="long") analytic=std::ldexp(double(k),-24);
            if(pattern=="sentinel") {double u=std::ldexp(1.,std::is_same<T,__nv_bfloat16>::value?-7:-10);analytic=1+2*u+u*u;}
            if(double(last[pos])!=analytic) exact_fail++;
        }
        if(pattern=="identity") { double expected=value(b[size_t(i)+size_t(j)*k]);if(double(last[pos])!=expected) exact_fail++; }
        if(pattern=="sentinel") { float wrong=value(quant<T>(last[pos]));if(std::abs(double(wrong)-ref)>limit) negative_reject++; }
        max_abs=std::max(max_abs,error);max_ratio=std::max(max_ratio,limit?error/limit:(error?1e300:0));sqerr+=error*error;sqref+=ref*ref;
    }
    bool repeat_equal=std::memcmp(first.data(),last.data(),cs*sizeof(float))==0;
    bool pass=!nonfinite&&!bound_fail&&!exact_fail&&repeat_equal&&(pattern!="sentinel"||negative_reject==checked);
    std::ofstream file(output,std::ios::binary|std::ios::out|std::ios::trunc);
    file.write(reinterpret_cast<const char*>(last.data()),cs*sizeof(float)); if(!file) throw std::runtime_error("output write failed");file.close();
    cudaDeviceProp prop{};int device=0;ck(cudaGetDevice(&device));ck(cudaGetDeviceProperties(&prop,device));
    std::cout<<std::setprecision(17)<<"{\"dtype\":\""<<dtype<<"\",\"pattern\":\""<<pattern<<"\",\"m\":"<<m<<",\"n\":"<<n<<",\"k\":"<<k
      <<",\"cublas_version\":"<<version<<",\"device_name\":\""<<prop.name<<"\",\"compute\":\"CUBLAS_COMPUTE_32F\",\"reduced_precision_reduction\":false,\"atomics\":false,\"workspace_bytes\":16777216,\"algorithm\":\"CUBLAS_GEMM_DEFAULT_TENSOR_OP\",\"output_order\":\"column_major_fp32\",\"nonfinite\":"<<nonfinite<<",\"reference_points\":"<<checked<<",\"full_reference\":"<<(points==cs?"true":"false")
      <<",\"bound_failures\":"<<bound_fail<<",\"exact_failures\":"<<exact_fail<<",\"negative_control_rejections\":"<<negative_reject<<",\"max_abs_error\":"<<max_abs<<",\"max_error_budget_ratio\":"<<max_ratio
      <<",\"reference_sample_relative_frobenius\":"<<std::sqrt(sqerr/(sqref?sqref:1))<<",\"first_last_bitwise_equal\":"<<(repeat_equal?"true":"false")<<",\"pass\":"<<(pass?"true":"false")<<",\"cuda_event_ms\":[";
    for(size_t x=0;x<event_ms.size();x++){if(x)std::cout<<',';std::cout<<event_ms[x];}std::cout<<"],\"host_wall_ms\":[";
    for(size_t x=0;x<wall_ms.size();x++){if(x)std::cout<<',';std::cout<<wall_ms[x];}std::cout<<"]}"<<std::endl;
    ck(cudaEventDestroy(start));ck(cudaEventDestroy(stop));cb(cublasDestroy(h));ck(cudaStreamDestroy(stream));
    ck(cudaFree(workspace));ck(cudaFree(dc));ck(cudaFree(db));ck(cudaFree(da));return pass?0:2;
}

int main(int argc,char** argv) {
    try {
        if(argc!=7) throw std::runtime_error("usage: gemm_check bf16|fp16 zero|identity|dyadic|cancellation|long|sentinel|random M N K output.bin");
        std::string dtype=argv[1],pattern=argv[2];int m=std::stoi(argv[3]),n=std::stoi(argv[4]),k=std::stoi(argv[5]);
        if(m<1||n<1||k<1||m>32768||n>32768||k>32768)throw std::runtime_error("shape outside frozen normal range");
        if(pattern!="zero"&&pattern!="identity"&&pattern!="dyadic"&&pattern!="cancellation"&&pattern!="long"&&pattern!="sentinel"&&pattern!="random")throw std::runtime_error("unknown pattern");
        if((pattern=="identity"&&(m!=n||n!=k))||(pattern=="cancellation"&&(k%2))||(pattern=="sentinel"&&k!=1))throw std::runtime_error("invalid analytic shape");
        if(dtype=="bf16")return run<__nv_bfloat16>(dtype,pattern,m,n,k,argv[6]);
        if(dtype=="fp16")return run<__half>(dtype,pattern,m,n,k,argv[6]);
        throw std::runtime_error("unknown dtype");
    } catch(const std::exception& e) { std::cerr<<e.what()<<std::endl;return 1; }
}
