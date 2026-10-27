# SPDX-License-Identifier: GPL-2.0-only
"""Finite, synthetic operator probes at project shapes. Never loads model weights."""
import argparse, gc, importlib.util, json, math, os, pathlib, statistics, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('--project', choices=['moss', 'qwen'], required=True)
ap.add_argument('--mode', choices=['timing', 'counter'], default='timing')
ap.add_argument('--output', required=True)
ap.add_argument('--cases', default='')
a = ap.parse_args()
O = pathlib.Path(a.output); O.mkdir(parents=True, exist_ok=True)
import torch
import torch.nn.functional as F
import triton
import triton.language as tl
torch.set_num_threads(4); torch.manual_seed(20261026)
torch.cuda.set_per_process_memory_fraction(1400 * 2**20 / torch.cuda.get_device_properties(0).total_memory)
torch.backends.cuda.matmul.allow_tf32 = False

@triton.jit
def stream_kernel(X, Y, N: tl.constexpr, B: tl.constexpr):
    i = tl.program_id(0) * B + tl.arange(0, B)
    v = tl.load(X+i, i<N, 0).to(tl.int32)
    tl.store(Y+tl.program_id(0), tl.sum(v, 0))

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

def rand(*shape): return torch.randn(shape,device='cuda',dtype=torch.bfloat16)
def flat(x):
    if isinstance(x,torch.Tensor): return [x]
    if isinstance(x,(tuple,list)): return [t for y in x for t in flat(y)]
    return []

def factory(name):
    meta={}; oracle=None
    if name.startswith('moss_mm_'):
        n,k={'qkv':(3072,3072),'up':(16384,3072),'down':(3072,8192),'dgrad':(3072,16384)}[name.split('_')[2]]
        m=4160; x=rand(m,k); w=rand(n,k).mul_(k**-.5)
        strict=name.endswith('strict'); torch.backends.cuda.matmul.allow_bf16_reduced_precision_reduction=not strict
        if 'triton' in name:
            bm,bn,bk=(64,64,32) if name.endswith('t64') else (128,128,32)
            y=torch.empty((m,n),device='cuda',dtype=torch.bfloat16)
            def op():
                mm_kernel[(triton.cdiv(m,bm),triton.cdiv(n,bn))](x,w,y,m,n,k,bm,bn,bk,num_warps=4 if bm==64 else 8)
                return y
        else: op=lambda:F.linear(x,w)
        ids=torch.tensor([0,1,17,m-1],device='cuda'); cols=torch.tensor([0,1,31,n-1],device='cuda')
        ref=x[ids].cpu().double()@w[cols].cpu().double().T
        def oracle(out):
            got=out[ids[:,None],cols[None,:]].cpu().double()
            err=(got-ref).abs(); scale=(x[ids].cpu().double().abs()@w[cols].cpu().double().abs().T)
            bound=(k*2**-24/(1-k*2**-24))*scale+2**-8*ref.abs()+.00001
            return {'sampled_values':16,'fp64_bound_pass':bool((err<=bound).all()),'max_abs_error':float(err.max())}
        meta.update(shape_mnk=[m,n,k],flops=2*m*n*k,minimum_payload_bytes=2*(m*k+n*k+m*n),reduced_precision_reduction=not strict)
    elif name.startswith('moss_'):
        from kohakumoss_kernels import registry
        registry.load_backends()
        key=name[5:]; n=4160
        if key in ['attention','attention_bwd']:
            q,k,v=rand(n,24,128),rand(n,24,128),rand(n,24,128)
            cu=torch.tensor([0,n],device='cuda',dtype=torch.int32)
            fn=registry.resolve('attention_varlen','cuda',torch.bfloat16,head_dim=128)
            if key=='attention_bwd':
                q.requires_grad_();k.requires_grad_();v.requires_grad_();dy=rand(n,24,128)
                op=lambda:torch.autograd.grad(fn(q,k,v,cu,n,128**-.5),(q,k,v),dy)
            else:op=lambda:fn(q,k,v,cu,n,128**-.5)
            meta.update(shape=[n,24,128],flops=4*24*n*n*128)
        elif key=='lora':
            x=rand(n,3072); down=rand(16,3072).mul_(.01); up=rand(3072,16).mul_(.01)
            op=lambda:F.linear(F.linear(x,down),up); fn=op
            meta.update(shape=[n,3072,16],flops=4*n*3072*16)
        elif key=='situ':
            x=rand(n,16384); fn=registry.resolve('situ_glu','cuda',torch.bfloat16);op=lambda:fn(x)
            meta.update(shape=list(x.shape),minimum_payload_bytes=n*(16384+8192)*2)
        else:
            x=rand(n,3072); w=torch.ones(3072,device='cuda'); seg=torch.zeros(n,device='cuda',dtype=torch.long)
            s=torch.randn((1,3072),device='cuda')*.01; b=torch.randn_like(s)*.01
            fn=registry.resolve('rms_norm_mod','cuda',torch.bfloat16);op=lambda:fn(x,w,b,s,seg,1e-6)
            meta.update(shape=list(x.shape),minimum_payload_bytes=x.numel()*4)
        meta['implementation']={'backend':getattr(fn,'backend',None),'function':repr(getattr(fn,'fn',fn))}
    elif name in ['stream_read','pcie_h2d','pcie_d2h']:
        size=512*2**20 if name=='stream_read' else 128*2**20
        data=torch.randint(0,100,(size//4,),device='cuda',dtype=torch.int32)
        if name=='stream_read':
            out=torch.empty((triton.cdiv(data.numel(),16384),),device='cuda',dtype=torch.int32)
            def op():
                stream_kernel[(out.numel(),)](data,out,data.numel(),16384,num_warps=8);return out
            expected=int(data.cpu().sum())
            oracle=lambda y:{'exact_checksum_pass':int(y.cpu().long().sum())==expected}
        else:
            host=torch.empty_like(data,device='cpu',pin_memory=True); host.fill_(3)
            op=(lambda:data.copy_(host,non_blocking=True)) if name.endswith('h2d') else (lambda:host.copy_(data,non_blocking=True))
        meta.update(minimum_payload_bytes=size,stream_bytes=size)
    elif name.startswith('qwen_gdn_recurrent'):
        from sglang.kernels.ops.attention.fla.fused_recurrent import fused_recurrent_gated_delta_rule_packed_decode
        batch=1 if name.endswith('b1') else 8;hv=24;hk=8;d=128
        qkv=rand(batch,(2*hk+hv)*d);aa=torch.zeros((batch,hv),device='cuda');bb=torch.zeros_like(aa)
        alog=torch.zeros(hv,device='cuda');bias=torch.zeros_like(alog)
        state=torch.zeros((batch,hv,d,d),device='cuda');out=torch.empty((batch,1,hv,d),device='cuda',dtype=torch.bfloat16)
        ids=torch.arange(batch,device='cuda',dtype=torch.int32)
        op=lambda:fused_recurrent_gated_delta_rule_packed_decode(qkv,aa,bb,alog,bias,d**-.5,state,out,ids,True)
        meta.update(shape=[batch,hv,d,d],scope='production TP2 packed recurrent GDN, synthetic steady recurrent state',minimum_payload_bytes=state.numel()*state.element_size()*2)
    elif name.startswith('qwen_gemv_'):
        key=name[10:]; n,k={'lm_head':(124160,2560),'gdn_input':(8240,2560),'gdn_out':(2560,3072),'router':(512,2560)}[key]
        x=rand(1,k);w=rand(n,k).mul_(k**-.5);op=lambda:F.linear(x,w)
        meta.update(shape_mnk=[1,n,k],flops=2*n*k,minimum_payload_bytes=2*(n*k+n+k))
        ids=torch.tensor([0,1,31,n-1],device='cuda'); ref=w[ids].cpu().double()@x.cpu().double().T
        oracle=lambda y:{'sampled_values':4,'fp64_max_abs_error':float((y[:,ids].cpu().double().T-ref).abs().max())}
    elif name.startswith('qwen_hc'):
        from sglang.kernels.ops.gemm.hc_mix import fused_hc_mix
        x=rand(1,10240);d=rand(320,10240).mul_(.01);u=rand(10240,320).mul_(.01)
        op=lambda:fused_hc_mix(x,d,u,4,2560)
        ref0=F.silu(x.cpu().double()@d.cpu().double().T/4).to(torch.bfloat16).double()
        ref=(torch.sigmoid(ref0@u.cpu().double().T).reshape(1,4,2560)*x.cpu().double().reshape(1,4,2560)).mean(1)
        oracle=lambda y:{'fp64_relative_l2_error':float(torch.linalg.vector_norm(y.cpu().double()-ref)/torch.linalg.vector_norm(ref))}
        meta.update(shape=[1,10240,320,4,2560],minimum_payload_bytes=(d.numel()+u.numel())*2)
    elif name.startswith('qwen_marlin'):
        from sglang.test.test_marlin_utils import marlin_quantize
        from sgl_kernel.scalar_type import scalar_types
        from sglang.kernels.ops.gemm.gptq_marlin import gptq_marlin_gemm
        from sglang.srt.layers.quantization.marlin_utils import marlin_make_workspace
        k,n=2560,768; m=1 if name.endswith('b1') else 8
        x=rand(m,k);w=rand(k,n).mul_(k**-.5)
        wr,qw,sc,gi,sort,_=marlin_quantize(w,scalar_types.uint4b8,128,False)
        workspace=marlin_make_workspace('cuda',4)
        def op():return gptq_marlin_gemm(x,None,qw,sc,None,None,gi,sort,workspace,scalar_types.uint4b8,m,n,k,True,False,True,False)
        ref=x.float()@wr.float()
        oracle=lambda y:{'dequantized_reference_relative_l2':float(torch.linalg.vector_norm(y.float()-ref)/torch.linalg.vector_norm(ref))}
        meta.update(shape_mnk=[m,n,k],flops=2*m*n*k,scope='one local W4A16 expert projection, not full routed MoE')
    elif name.startswith('qwen_moe'):
        from sglang_qsa_hisparse.patches.model_compat.marlin import fused_marlin_moe
        # TP2 local 320 intermediate values are padded to 384 by production Marlin.
        # Keep the complete 512-expert W4 bank, with synthetic packed weights.
        m=1 if name.endswith('b1') else 8; e,k,n,top=512,2560,384,10
        x=rand(m,k);w1=torch.randint(-2**30,2**30,(e,k//16,n*4),device='cuda',dtype=torch.int32)
        w2=torch.randint(-2**30,2**30,(e,n//16,k*2),device='cuda',dtype=torch.int32)
        s1=torch.full((e,k//128,n*2),.01,device='cuda',dtype=torch.bfloat16)
        s2=torch.full((e,n//128,k),.01,device='cuda',dtype=torch.bfloat16)
        ids=torch.arange(m*top,device='cuda',dtype=torch.int32).reshape(m,top)%e
        weights=torch.full((m,top),1/top,device='cuda');gate=torch.zeros((m,e),device='cuda')
        def op():return fused_marlin_moe(x,w1,w2,s1,s2,gate,weights,ids,num_bits=4,activation='situ')
        meta.update(shape=[m,e,k,n,top],scope='complete synthetic W4A16 expert bank at TP2 padded local dimensions; finite diagnostic only',minimum_payload_bytes=top*k*n*3/2)
    else: raise ValueError(name)
    return op,meta,oracle

cases=(['moss_mm_qkv_default','moss_mm_qkv_strict','moss_mm_qkv_triton_t64','moss_mm_qkv_triton_t128','moss_mm_up_default','moss_mm_up_strict','moss_mm_up_triton_t64','moss_mm_up_triton_t128','moss_mm_down_default','moss_mm_dgrad_default','moss_attention','moss_attention_bwd','moss_lora','moss_situ','moss_norm','pcie_h2d','pcie_d2h'] if a.project=='moss' else ['stream_read','qwen_gemv_lm_head','qwen_gemv_gdn_input','qwen_gemv_gdn_out','qwen_gemv_router','qwen_hc','qwen_marlin_b1','qwen_marlin_b8','qwen_moe_b1','qwen_moe_b8','qwen_gdn_recurrent_b1','qwen_gdn_recurrent_b8'])
if a.cases: cases=a.cases.split(',')
allrows=[]
for name in cases:
    marker=O/'active.json';marker.write_text(json.dumps({'case':name,'mode':a.mode,'at':time.time()}))
    try:
        torch.cuda.synchronize();gc.collect();torch.cuda.empty_cache()
        torch.manual_seed(20261026)
        op,meta,oracle=factory(name)
        for _ in range(4):answer=op()
        torch.cuda.synchronize()
        diagnostic={'finite':all(bool(torch.isfinite(t).all()) for t in flat(answer) if t.is_cuda)}
        if oracle:diagnostic.update(oracle(answer))
        assert diagnostic['finite'] and diagnostic.get('fp64_bound_pass',True) and diagnostic.get('exact_checksum_pass',True),diagnostic
        warm=time.monotonic()
        while time.monotonic()-warm<1.0:
            for _ in range(8):answer=op()
            torch.cuda.synchronize()
        if a.mode=='counter':
            if a.project=='qwen':
                eviction=torch.empty((96*2**20//4,),device='cuda',dtype=torch.int32)
                partial=torch.empty((triton.cdiv(eviction.numel(),16384),),device='cuda',dtype=torch.int32)
                stream_kernel[(partial.numel(),)](eviction,partial,eviction.numel(),16384,num_warps=8)
                torch.cuda.synchronize()
            torch.cuda.nvtx.range_push('operator_probe')
            answer=op();torch.cuda.synchronize();torch.cuda.nvtx.range_pop()
            row={'case':name,'meta':meta,'diagnostic':diagnostic,'mode':'counter'}
        else:
            # Warm-up before choosing a finite graph body. No model or service graphs touched.
            start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
            start.record()
            for _ in range(8):answer=op()
            end.record();torch.cuda.synchronize();rough=start.elapsed_time(end)/8
            repeats=max(1,min(256,math.ceil(8/max(rough,.001))))
            g=torch.cuda.CUDAGraph()
            with torch.cuda.graph(g):
                for _ in range(repeats):answer=op()
            for _ in range(4):g.replay()
            torch.cuda.synchronize();samples=[];wall=[]
            for _ in range(21):
                t=time.perf_counter();start.record();g.replay();end.record();end.synchronize()
                samples.append(start.elapsed_time(end)*1000/repeats);wall.append((time.perf_counter()-t)*1e6/repeats)
            median=statistics.median(samples)
            row={'case':name,'mode':'timing','meta':meta,'diagnostic':diagnostic,'samples_us':samples,'median_us':median,'min_us':min(samples),'max_us':max(samples),'repeats_per_graph':repeats,'logical_GBps_not_dram_counter':meta.get('minimum_payload_bytes',0)/median/1000,'TFLOPS':meta.get('flops',0)/median/1e6,'torch':torch.__version__,'cuda':torch.version.cuda,'max_allocated_mib':torch.cuda.max_memory_allocated()/2**20}
            del g
            if a.project=='qwen':
                eviction=torch.empty((96*2**20//4,),device='cuda',dtype=torch.int32)
                partial=torch.empty((triton.cdiv(eviction.numel(),16384),),device='cuda',dtype=torch.int32)
                coldstart=torch.cuda.Event(enable_timing=True,external=True);coldend=torch.cuda.Event(enable_timing=True,external=True)
                coldg=torch.cuda.CUDAGraph()
                with torch.cuda.graph(coldg):
                    stream_kernel[(partial.numel(),)](eviction,partial,eviction.numel(),16384,num_warps=8)
                    coldstart.record();answer=op();coldend.record()
                cold=[]
                for _ in range(31):
                    coldg.replay();torch.cuda.synchronize();cold.append(coldstart.elapsed_time(coldend)*1000)
                row.update(evicted_samples_us=cold,evicted_median_us=statistics.median(cold))
                del coldg,eviction,partial
        allrows.append(row)
        with (O/'results.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps({'case':name,'status':'completed','us':row.get('median_us')}),flush=True)
        del op,oracle,answer;gc.collect();torch.cuda.empty_cache()
    except Exception as e:
        row={'case':name,'status':'failed','error':repr(e)};allrows.append(row)
        with (O/'results.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if 'out of memory' in str(e).lower():break
(O/'summary.json').write_text(json.dumps({'rows':allrows,'project':a.project,'mode':a.mode},indent=2))
marker.write_text(json.dumps({'case':'complete','at':time.time()}))
