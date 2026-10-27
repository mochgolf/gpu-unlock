# SPDX-License-Identifier: GPL-2.0-only
"""Interleaved implementations on identical BF16 inputs; no production changes."""
import argparse, gc, json, pathlib, statistics, time
ap=argparse.ArgumentParser();ap.add_argument('--project');ap.add_argument('--output',required=True);ap.add_argument('--mode',default='timing');ap.add_argument('--cases',default='');a=ap.parse_args()
O=pathlib.Path(a.output);O.mkdir(exist_ok=True,parents=True)
import torch,torch.nn.functional as F,triton,triton.language as tl
torch.set_num_threads(4);torch.cuda.set_per_process_memory_fraction(1400*2**20/torch.cuda.get_device_properties(0).total_memory)
torch.backends.cuda.matmul.allow_tf32=False
# Triton needs real file source for introspection, so keep its kernel in an importable sidecar.
from matmul_kernel import mm_kernel
rows=[]
for shape,n,k in [('qkv',3072,3072),('up',16384,3072),('down',3072,8192),('dgrad',3072,16384)]:
 torch.manual_seed(20261026);m=4160;x=torch.randn((m,k),device='cuda',dtype=torch.bfloat16);w=torch.randn((n,k),device='cuda',dtype=torch.bfloat16).mul_(k**-.5)
 y=torch.empty((m,n),device='cuda',dtype=torch.bfloat16)
 idxm=torch.tensor([0,1,17,m-1],device='cuda');idxn=torch.tensor([0,1,31,n-1],device='cuda')
 xd=x[idxm].cpu().double();wd=w[idxn].cpu().double();ref=xd@wd.T
 bound=(k*2**-24/(1-k*2**-24))*(xd.abs()@wd.abs().T)+2**-8*ref.abs()+1e-5
 variants=['cublas','cublaslt','triton128']
 if a.cases:variants=a.cases.split(',')
 graphs={};diagnostics={}
 for impl in variants:
  (O/'active.json').write_text(json.dumps({'case':shape+'-'+impl+'-setup','at':time.time()}))
  if impl=='triton128':
   def op():
    mm_kernel[(triton.cdiv(m,128),triton.cdiv(n,128))](x,w,y,m,n,k,128,128,32,num_warps=8);return y
  else:
   torch.backends.cuda.preferred_blas_library(impl)
   def op():return F.linear(x,w)
  for _ in range(8):out=op()
  torch.cuda.synchronize();actual=out[idxm[:,None],idxn[None,:]].cpu().double()
  diagnostics[impl]={'fp64_bound_pass':bool(((actual-ref).abs()<=bound).all()),'max_abs_error':float((actual-ref).abs().max())}
  assert diagnostics[impl]['fp64_bound_pass']
  g=torch.cuda.CUDAGraph()
  with torch.cuda.graph(g):
   for _ in range(8):out=op()
  graphs[impl]=g
 samples={v:[] for v in variants};start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
 for sweep in range(7):
  for impl in variants if sweep%2==0 else list(reversed(variants)):
   (O/'active.json').write_text(json.dumps({'case':shape+'-'+impl,'at':time.time(),'sweep':sweep}))
   warm=time.monotonic()
   while time.monotonic()-warm<.65:graphs[impl].replay();torch.cuda.synchronize()
   if a.mode=='counter' and sweep==0:
    torch.cuda.nvtx.range_push('operator_probe');graphs[impl].replay();torch.cuda.synchronize();torch.cuda.nvtx.range_pop()
   for _ in range(5):
    start.record();graphs[impl].replay();end.record();end.synchronize();samples[impl].append(start.elapsed_time(end)*1000/8)
  if a.mode=='counter':break
 row={'case':shape,'shape_mnk':[m,n,k],'results':{impl:{'median_us':statistics.median(s),'samples_us':s,'TFLOPS':2*m*n*k/statistics.median(s)/1e6,'diagnostic':diagnostics[impl]} for impl,s in samples.items()}}
 rows.append(row)
 with (O/'results.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
 del graphs,x,w,y,out;gc.collect();torch.cuda.empty_cache()
(O/'summary.json').write_text(json.dumps({'rows':rows},indent=2))
