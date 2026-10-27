# SPDX-License-Identifier: GPL-2.0-only
import triton
import triton.language as tl
@triton.jit
def mm_kernel(X, W, Y, M: tl.constexpr, N: tl.constexpr, K: tl.constexpr,
              BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    mi=tl.program_id(0)*BM+tl.arange(0,BM)
    ni=tl.program_id(1)*BN+tl.arange(0,BN)
    ki=tl.arange(0,BK)
    acc=tl.full((BM,BN),0,tl.float32)
    for base in range(tl.cdiv(K,BK)):
        kk=base*BK+ki
        x=tl.load(X+mi[:,None]*K+kk[None,:],(mi[:,None]<M)&(kk[None,:]<K),0)
        w=tl.load(W+ni[None,:]*K+kk[:,None],(ni[None,:]<N)&(kk[:,None]<K),0)
        acc=tl.dot(x,w,acc)
    tl.store(Y+mi[:,None]*N+ni[None,:],acc.to(tl.bfloat16),(mi[:,None]<M)&(ni[None,:]<N))
