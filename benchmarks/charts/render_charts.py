"""Render fixed benchmark evidence. This program does not access a GPU or service."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OLD = REPO / 'benchmarks/2026-10-26'
NEW = REPO / 'benchmarks/2026-10-29'
OUT = HERE / 'output'
COL = {'old':'#94A3B8', 'new':'#1976B7', 'a2':'#D5DEE8', 'impl':'#8458B3',
       'resident':'#168B78', 'gpu1':'#D88A23', 'text':'#172B3A', 'muted':'#526575', 'grid':'#DFE6EC'}
LANG = 'zh-CN'
CSV_ROWS = []
SOURCE_HASHES = {}

def T(zh, en):
    return zh if LANG == 'zh-CN' else en

def load(path):
    text = path.read_text(encoding='utf8')
    # Match the repository JSON bytes across Windows and Linux checkouts.
    SOURCE_HASHES[path.relative_to(REPO).as_posix()] = hashlib.sha256(text.encode('utf8')).hexdigest()
    return json.loads(text)

def extract():
    ab = load(OLD/'ab-a-matched.json')
    fp = load(NEW/'results.json')
    ops = load(OLD/'operators.json')
    hist = load(OLD/'historical-applications.json')
    qwen = load(OLD/'qwen-single.json')
    deploy = load(HERE/'deployment-summary.json')
    modes = ['f16/f32','bf16/f32','f16/f16','s8/s32','dp4a','ffma']
    mma = [{ 'mode':mode, 'phases':{phase:ab['phases'][phase]['mma']['target'][mode]
            for phase in ['A1','B1','A2']} } for mode in modes]
    gemm = []
    for dtype in ['bf16','fp16']:
        for shape in [(4096,4096,4096),(8192,8192,8192),(256,512,16384)]:
            key = 'target-'+dtype+'-random-'+'-'.join(map(str,shape))
            vals = {phase:ab['phases'][phase]['large_gemm'][key] for phase in ['A1','B1','A2']}
            gemm.append({'dtype':dtype,'shape':shape,'phases':{
                phase:{'tflops':row['median_tflops'],'n':row['event_ms']['n'],
                    'ms_samples':row['event_ms']['all']} for phase,row in vals.items()}})
    phases = {phase['label']:{row['case']:row for row in phase['rows']} for phase in ops['phases']}
    paired = []
    for gpu in [0,1]:
        for case,row in phases[f'paired-g{gpu}-450'].items():
            paired.append({'gpu':gpu,'case':case,'shape':row['shape_mnk'],'implementations':{
                impl:{'median_ms':v['median_us']/1000,'samples_ms':[x/1000 for x in v['samples_us']]}
                for impl,v in row['results'].items()}})
    power = []
    for project in ['moss','qwen']:
        a,b = phases[f'{project}-g0-300'],phases[f'{project}-g0-450b']
        for case,row in a.items():
            if case == 'stream_read':
                continue
            base = b[case]['median_us']; low = row['median_us']
            power.append({'project':project,'case':case,'base_us':base,'low_us':low,
                          'delta_percent':(low/base-1)*100,'cache':'ordinary'})
            if case == 'qwen_gemv_gdn_input':
                base = b[case]['evicted_median_us']; low = row['evicted_median_us']
                power.append({'project':project,'case':case,'base_us':base,'low_us':low,
                              'delta_percent':(low/base-1)*100,'cache':'evicted'})
    fp8 = [arm for arm in fp['arms'] if arm['chains']==8 and arm['iters']==20000]
    assert len(fp8)==2 and all(v['phases']['A1']['n']==30 for v in mma)
    assert all(len(v['implementations']['cublas']['samples_ms'])==35 for v in paired)
    assert qwen['measured_requests']==17 and sum(v['n'] for v in qwen['groups'].values())==17
    d = {'mma':mma,'gemm':gemm,'fp8':fp8,'fp8_reference':fp['network_reference'],
         'paired':paired,'power':power,'history':hist,'qwen':qwen['groups'],'deployment':deploy,
         'source_sha256':SOURCE_HASHES,'scope':'Fixed 2026-10-26 and 2026-10-29 measurements; no new live measurements.'}
    return d

def record(chart, metric, variant, value, unit, kind, n, source):
    CSV_ROWS.append(dict(chart=chart,metric=metric,variant=variant,value=float(value),unit=unit,
                         comparison_kind=kind,n=n,source=source))

def clean_svg(path):
    text=path.read_text(encoding='utf8')
    path.write_text('\n'.join(line.rstrip() for line in text.splitlines())+'\n',encoding='utf8',newline='\n')

def style():
    plt.rcParams.update({'font.size':11,'axes.titlesize':12,'axes.labelsize':10.5,
        'xtick.labelsize':9.5,'ytick.labelsize':10.5,'legend.fontsize':9.5,
        'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False,
        'axes.edgecolor':COL['grid'],'axes.labelcolor':COL['text'],'text.color':COL['text'],
        'xtick.color':COL['muted'],'ytick.color':COL['text'],'axes.unicode_minus':False,
        'svg.fonttype':'path','pdf.fonttype':42,'ps.fonttype':42,'figure.facecolor':'white',
        'axes.facecolor':'white','savefig.facecolor':'white','axes.titleweight':'normal'})

def finish(fig, title, subtitle, foot, source):
    fig.suptitle(title,x=.06,y=.978,ha='left',fontsize=15.5,fontweight='normal')
    fig.text(.06,.915,subtitle,ha='left',fontsize=10,color=COL['muted'])
    fig.text(.06,.095,foot,ha='left',va='top',fontsize=9.4,linespacing=1.6,color=COL['muted'])
    fig.text(.06,.015,source,ha='left',fontsize=8.2,color=COL['muted'])
    return fig

def axis(ax, xlabel):
    ax.set_xlabel(xlabel)
    ax.xaxis.grid(True,color=COL['grid'],linewidth=.7)
    ax.set_axisbelow(True)
    ax.tick_params(axis='both',length=0,pad=6)

def ratio_panel(ax, labels, vals, title, color=COL['new'], second=None):
    y=np.arange(len(labels)); height=.32 if second is not None else .49
    ax.barh(y-(.17 if second is not None else 0),vals,height,color=color)
    if second is not None:
        ax.barh(y+.17,second,height,color=COL['a2'],hatch='///',edgecolor=COL['muted'],linewidth=0)
    for i,v in enumerate(vals):
        ax.text(v+.035,i-(.17 if second is not None else 0),f'{v:.3f}x',va='center',fontsize=9.4)
    ax.axvline(1,color=COL['muted'],lw=.9,ls='--')
    ax.set(yticks=y,yticklabels=labels,xlim=(0,2.32))
    ax.invert_yaxis();ax.set_title(title,loc='left',pad=13)
    axis(ax,T('相对吞吐（对应基线 = 1）','Relative throughput (respective baseline = 1)'))

def overview(d):
    fig,axs=plt.subplots(2,2,figsize=(12.4,10.2))
    fig.subplots_adjust(left=.15,right=.965,top=.86,bottom=.16,wspace=.63,hspace=.56)
    labels=['FP16 / FP32','BF16 / FP32','FP16 / FP16','INT8 / INT32','dp4a','Scalar FP32']
    a=[v['phases']['B1']['median']/v['phases']['A1']['median'] for v in d['mma']]
    a2=[v['phases']['A2']['median']/v['phases']['A1']['median'] for v in d['mma']]
    ratio_panel(axs[0,0],labels,a,T('指令吞吐 · A/B/A','Instruction throughput · A/B/A'),second=a2)
    axs[0,0].legend(handles=[Patch(facecolor=COL['new'],label=T('B1 解锁 / A1','B1 unlocked / A1')),
        Patch(facecolor=COL['a2'],hatch='///',edgecolor=COL['muted'],label=T('A2 冷锁定 / A1','A2 cold locked / A1'))],
        frameon=False,loc='lower right',fontsize=8.8)
    labs=[v['dtype'].upper()+' '+('4096³' if v['shape'][0]==4096 else '8192³' if v['shape'][0]==8192 else 'skinny*') for v in d['gemm']]
    a=[v['phases']['B1']['tflops']/v['phases']['A1']['tflops'] for v in d['gemm']]
    a2=[v['phases']['A2']['tflops']/v['phases']['A1']['tflops'] for v in d['gemm']]
    ratio_panel(axs[0,1],labs,a,T('cuBLAS GEMM · A/B/A','cuBLAS GEMM · A/B/A'),second=a2)
    paired=[v for v in d['paired'] if v['gpu']==0]
    ratios=[v['implementations']['cublas']['median_ms']/v['implementations']['triton128']['median_ms'] for v in paired]
    ratio_panel(axs[1,0],[v['case'] for v in paired],ratios,T('MOSS 算子 · Triton128 / cuBLAS','MOSS kernels · Triton128 / cuBLAS'),COL['impl'])
    h=d['history'];old=h['moss_training']['historical']['tokens_per_second']
    values=[h['moss_training']['current_same_offload']['tokens_per_second']/old,
            h['moss_training']['current_resident']['tokens_per_second']/old,
            h['qwen_comparable_service_log_bins']['short']['new_median_tps']/h['qwen_comparable_service_log_bins']['short']['old_median_tps'],
            h['qwen_comparable_service_log_bins']['medium']['new_median_tps']/h['qwen_comparable_service_log_bins']['medium']['old_median_tps']]
    ratio_panel(axs[1,1],['MOSS offload','MOSS resident',T('Qwen 短分组','Qwen short bin'),T('Qwen 中分组','Qwen medium bin')],values,
                T('服务吞吐 · 当前 / 历史','Service throughput · current / historical'),COL['resident'])
    return finish(fig,T('算力、算子与生产服务的性能对比','Performance across instructions, kernels, and services'),
        T('双 RTX 4090 · 48 GiB/卡 · 450 W/卡','Dual RTX 4090 · 48 GiB/card · 450 W/card'),
        T('* skinny = 256×512×16384；指令 n=30/模式，GEMM n=10/形状。',
          '* skinny = 256x512x16384; instruction n=30/mode, GEMM n=10/shape.'),
        'Sources: ab-a-matched.json | operators.json | historical-applications.json (2026-10-26)')

def fp8_chart(d):
    fig,axs=plt.subplots(1,2,figsize=(12.8,7.5),gridspec_kw={'width_ratios':[1.25,1]})
    fig.subplots_adjust(left=.13,right=.96,top=.82,bottom=.25,wspace=.55)
    modes=['e4m3/f32','e5m2/f32','e4m3/f16','e5m2/f16'];y=np.arange(4)
    for j,(variant,color) in enumerate([('spec',COL['old']),('gpu0',COL['new']),('gpu1',COL['gpu1'])]):
        values=[];lo=[];hi=[]
        for mode in modes:
            if variant=='spec':
                val=d['fp8_reference']['fp8_fp32_accum_dense_tflops' if mode.endswith('f32') else 'fp8_fp16_accum_dense_tflops'];mn=mx=val
            else:
                arm=next(v for v in d['fp8'] if v['gpu']==int(variant[-1]));s=arm['results'][mode]['tflops'];val=s['median'];mn=s['min'];mx=s['max']
            values.append(val);lo.append(val-mn);hi.append(mx-val)
            record('02-fp8',mode,variant,val,'dense TFLOP/s','network_spec' if variant=='spec' else 'current_native',None if variant=='spec' else 21,'2026-10-29/results.json')
        yy=y+(j-1)*.24
        axs[0].barh(yy,values,.21,color=color,label=T('原版规格 2520 MHz','Stock spec, 2520 MHz') if variant=='spec' else variant.upper(),hatch='///' if variant=='spec' else None)
        if variant!='spec':axs[0].errorbar(values,yy,xerr=[lo,hi],fmt='none',ecolor=COL['muted'],elinewidth=.8,capsize=2)
        for k,val in enumerate(values):axs[0].text(val+9,yy[k],f'{val:.1f}',va='center',fontsize=9)
    axs[0].set(yticks=y,yticklabels=['E4M3 / FP32','E5M2 / FP32','E4M3 / FP16','E5M2 / FP16'],xlim=(0,805))
    axs[0].invert_yaxis();axis(axs[0],T('稠密 TFLOP/s（越高越好）','Dense TFLOP/s (higher is better)'))
    axs[0].set_title(T('原版规格参考与当前实测','Stock specification and current measurements'),loc='left',pad=15)
    axs[0].legend(frameon=False,loc='lower left',bbox_to_anchor=(0,-.23),ncol=2)
    for gpu,color in [(0,COL['new']),(1,COL['gpu1'])]:
        arm=next(v for v in d['fp8'] if v['gpu']==gpu)
        vals=[arm['results'][m]['f32_over_f16_accum_clock_normalized']['median'] for m in modes[:2]]
        yy=np.arange(2)+(gpu-.5)*.26
        axs[1].barh(yy,vals,.23,color=color,label=f'GPU{gpu}')
        for k,val in enumerate(vals):axs[1].text(val+.025,yy[k],f'{val:.4f}',va='center',fontsize=10)
    axs[1].axvline(.5,color=COL['old'],ls='--',lw=1)
    axs[1].axvline(1,color=COL['muted'],ls='--',lw=1)
    axs[1].text(.5,.985,T('原版规格比 0.5','Stock ratio 0.5'),transform=axs[1].get_xaxis_transform(),ha='center',va='top',fontsize=9)
    axs[1].text(1,.985,T('同速 = 1','Equal rate = 1'),transform=axs[1].get_xaxis_transform(),ha='center',va='top',fontsize=9)
    axs[1].set(yticks=[0,1],yticklabels=['E4M3','E5M2'],xlim=(0,1.23),ylim=(-.5,1.5))
    axs[1].invert_yaxis();axis(axs[1],T('FP32 / FP16 累加吞吐比（按时钟归一化）','FP32 / FP16 accumulation rate (clock-normalized)'))
    axs[1].set_title(T('同卡 FP32 与 FP16 累加对照','FP32 versus FP16 accumulation on each card'),loc='left',pad=15)
    return finish(fig,T('FP8 原生算力','Native FP8 throughput'),
        T('已解锁双卡 · 每模式 n=21 · 稠密计算 · 误差线 min-max','Both cards unlocked · n=21/mode · dense operations · whiskers: min-max'),
        T('时钟：GPU0 约 2710 MHz · GPU1 约 2744 MHz · 原版规格 2520 MHz。',
          'Clocks: GPU0 ~2710 MHz · GPU1 ~2744 MHz · stock specification 2520 MHz.'),
        'Source: 2026-10-29/results.json | NVIDIA Ada whitepaper V2.02, Appendix A')

def moss_kernels(d):
    fig,axs=plt.subplots(1,2,figsize=(12.8,7.6),sharex=True)
    fig.subplots_adjust(left=.19,right=.96,top=.82,bottom=.24,wspace=.45)
    names=['qkv','up','down','dgrad'];impls=[('cublas','cuBLAS',COL['old']),('cublaslt','cuBLASLt',COL['new']),('triton128','Triton128',COL['impl'])]
    for gpu,ax in enumerate(axs):
        rows=[v for v in d['paired'] if v['gpu']==gpu];y=np.arange(4)
        for j,(impl,label,color) in enumerate(impls):
            vals=[row['implementations'][impl]['median_ms'] for row in rows]
            lower=[];upper=[]
            for row,val in zip(rows,vals):
                a=np.percentile(row['implementations'][impl]['samples_ms'],[10,90]);lower.append(val-a[0]);upper.append(a[1]-val)
                record('03-moss-kernels',row['case'],f'GPU{gpu}/{impl}',val,'ms','independent_implementation',35,'2026-10-26/operators.json')
            yy=y+(j-1)*.24
            ax.barh(yy,vals,.21,color=color,label=label)
            ax.errorbar(vals,yy,xerr=[lower,upper],fmt='none',ecolor=COL['muted'],elinewidth=.7,capsize=2)
            for k,v in enumerate(vals):ax.text(v+.045,yy[k],f'{v:.3f}',va='center',fontsize=9.1)
        labs=[row['case']+'\n'+' × '.join(map(str,row['shape'])) for row in rows]
        ax.set(yticks=y,yticklabels=labs,xlim=(0,3.05));ax.invert_yaxis()
        ax.set_title(f'GPU{gpu}',loc='left',pad=15);axis(ax,T('中位延迟 ms（越低越好）','Median latency, ms (lower is better)'))
    axs[0].legend(frameon=False,loc='lower left',bbox_to_anchor=(0,-.25),ncol=3)
    return finish(fig,T('MOSS 算子延迟','MOSS kernel latency'),
        T('同一已解锁状态、相同 BF16 输入、450 W；每实现 35 次，误差线为观测 P10-P90。','Same unlocked state, identical BF16 inputs, 450 W; 35 samples per implementation; whiskers: observed P10-P90.'),
        T('输入形状标为 M × N × K。','Input shapes are M × N × K.'),
        'Source: 2026-10-26/operators.json, paired-g0-450 and paired-g1-450')

def power_chart(d):
    fig,axs=plt.subplots(1,2,figsize=(12.8,8.4))
    fig.subplots_adjust(left=.20,right=.96,top=.84,bottom=.22,wspace=.62)
    labels={'moss_mm_qkv_default':'QKV','moss_mm_up_default':'FFN up','moss_mm_down_default':'FFN down',
        'moss_mm_dgrad_default':'dgrad','moss_attention':'Attention','moss_attention_bwd':'Attention backward',
        'moss_situ':'SiTU','moss_norm':'Norm','moss_mm_up_triton_t128':'FFN up / Triton128',
        'qwen_gemv_lm_head':'LM-head GEMV','qwen_gemv_gdn_input':'GDN-input GEMV',
        'qwen_hc':'HC','qwen_moe_b1':'MoE B1','qwen_gdn_recurrent_b1':'GDN recurrent B1'}
    for project,ax in zip(['moss','qwen'],axs):
        rows=[v for v in d['power'] if v['project']==project]
        vals=[v['delta_percent'] for v in rows];y=np.arange(len(rows))
        ax.barh(y,vals,.55,color=COL['new'] if project=='moss' else COL['resident'])
        for i,val in enumerate(vals):ax.text(max(val,0)+1.1,i,f'{val:+.2f}%',va='center',fontsize=10)
        labs=[labels[v['case']]+(T('（驱逐缓存）',' (evicted)') if v['cache']=='evicted' else T('（热缓存）',' (hot cache)') if v['case']=='qwen_gemv_gdn_input' else '') for v in rows]
        ax.set(yticks=y,yticklabels=labs,xlim=(-2,65));ax.invert_yaxis();ax.axvline(0,color=COL['muted'],lw=.8)
        ax.set_title(project.upper(),loc='left',pad=15)
        axis(ax,T('300 W 相对恢复后 450 W 的延迟增幅 (%)','Latency increase at 300 W versus restored 450 W (%)'))
        for row in rows:record('04-power',row['case']+'/'+row['cache'],project,row['delta_percent'],'percent latency','power_perturbation',31 if row['cache']=='evicted' else 21,'2026-10-26/operators.json')
    return finish(fig,T('MOSS / Qwen 算子功耗敏感度','MOSS / Qwen kernel power sensitivity'),
        T('同卡、同输入，比较 300 W 与恢复后的 450 W；两面板使用相同横轴。','Same card and inputs: 300 W versus restored 450 W. Both panels use the same horizontal scale.'),
        T('GPU0 · CUDA event 计时 · 常规 n=21，驱逐缓存 n=31。',
          'GPU0 · CUDA event timing · ordinary n=21, evicted-cache n=31.'),
        'Source: 2026-10-26/operators.json, *-g0-300 and *-g0-450b')

def moss_service(d):
    h=d['history'];m=h['moss_training'];im=h['moss_image_generation']
    fig=plt.figure(figsize=(12.8,10.3));gs=fig.add_gridspec(2,2,height_ratios=[1,1.05])
    ax1=fig.add_subplot(gs[0,0]);ax2=fig.add_subplot(gs[0,1]);ax3=fig.add_subplot(gs[1,:])
    fig.subplots_adjust(left=.10,right=.96,top=.84,bottom=.17,wspace=.34,hspace=.73)
    vals=[m[k]['tokens_per_second'] for k in ['historical','current_same_offload','current_resident']]
    colors=[COL['old'],COL['new'],COL['resident']]
    ax1.bar(range(3),vals,color=colors,width=.58)
    labs=[T('历史 offload','Historical\noffload'),T('当前同 offload','Current same\noffload'),T('当前 resident','Current\nresident')]
    for i,v in enumerate(vals):
        ax1.text(i,v+65,f'{v:,.2f}',ha='center',fontsize=10)
        if i:ax1.text(i,v-250,f'{(v/vals[0]-1)*100:+.2f}%',ha='center',color='white',fontsize=11)
        record('05-moss-service','training',str(i),v,'token/s','historical_confounded',90,'2026-10-26/historical-applications.json')
    ax1.set(xticks=range(3),xticklabels=labs,ylim=(0,3900),ylabel=T('训练 token/s（越高越好）','Training token/s (higher is better)'))
    ax1.set_title(T('匹配训练区间：948,960 token / 90 step','Matched training interval: 948,960 tokens / 90 steps'),loc='left',pad=15)
    ax1.yaxis.grid(True,color=COL['grid'],lw=.7);ax1.set_axisbelow(True)
    vals=[im['historical_seconds_per_image'],*im['current_seconds_per_image']]
    ax2.bar(range(3),vals,color=[COL['old'],COL['new'],COL['gpu1']],width=.58)
    for i,v in enumerate(vals):
        ax2.text(i,v+1,f'{v:.2f}',ha='center',fontsize=11)
        record('05-moss-service','image_generation',str(i),v,'s/image','historical_different_profiles',32 if i==0 else 4,'2026-10-26/historical-applications.json')
    ax2.set(xticks=range(3),xticklabels=[T('历史 balanced\nn=32','Historical balanced\nn=32'),'GPU0 speed\nn=4','GPU1 speed\nn=4'],ylim=(0,52),ylabel=T('秒/图（越低越好）','Seconds/image (lower is better)'))
    ax2.set_title(T('图像生成','Image generation'),loc='left',pad=15)
    ax2.yaxis.grid(True,color=COL['grid'],lw=.7);ax2.set_axisbelow(True)
    windows=m['paired_10_step_windows'];x=[w['end_step'] for w in windows]
    for key,label,color in [('old_seconds',T('历史 offload','Historical offload'),COL['old']),('current_seconds',T('当前同 offload','Current same offload'),COL['new']),('resident_seconds',T('当前 resident','Current resident'),COL['resident'])]:
        ax3.plot(x,[w['tokens']/w[key] for w in windows],'-o',label=label,color=color,lw=1.8,ms=4)
    ax3.set(xticks=x,xlabel=T('配对 10-step 窗口的结束 step','End step of each matched 10-step window'),ylabel='token/s',ylim=(2300,3700))
    ax3.set_title(T('九个匹配训练窗口','Nine matched training windows'),loc='left',pad=15)
    ax3.yaxis.grid(True,color=COL['grid'],lw=.7);ax3.legend(frameon=False,loc='upper left',ncol=3,fontsize=9.4)
    return finish(fig,T('MOSS 训练与推理性能','MOSS training and inference performance'),
        T('训练吞吐 = 总 token / 总区间时间','Training throughput = total tokens / interval time'),
        T('训练区间：step 51-140 · 90 step · 237 样本 · 948,960 token。',
          'Training interval: steps 51-140 · 90 steps · 237 samples · 948,960 tokens.'),
        'Source: 2026-10-26/historical-applications.json')

def qwen_service(d):
    fig,axs=plt.subplots(2,2,figsize=(12.8,10.3))
    fig.subplots_adjust(left=.10,right=.96,top=.84,bottom=.17,wspace=.36,hspace=.64)
    bins=d['history']['qwen_comparable_service_log_bins'];keys=['short','medium'];x=np.arange(2)
    for j,(key,label,color) in enumerate([('old_median_tps',T('历史日志','Historical logs'),COL['old']),('new_median_tps',T('当前日志','Current logs'),COL['new'])]):
        vals=[bins[k][key] for k in keys];bars=axs[0,0].bar(x+(j-.5)*.32,vals,.29,color=color,label=label)
        axs[0,0].bar_label(bars,labels=[f'{v:.2f}' for v in vals],padding=4,fontsize=10)
    for i,k in enumerate(keys):
        v=bins[k];axs[0,0].text(i,104,f'{(v["new_median_tps"]/v["old_median_tps"]-1)*100:+.2f}%',ha='center',fontsize=10)
    axs[0,0].set(xticks=x,xticklabels=[T('短分组','Short bin')+f'\n{bins["short"]["old_log_windows"]} → {bins["short"]["new_log_windows"]} '+T('窗口','windows'),T('中分组','Medium bin')+f'\n{bins["medium"]["old_log_windows"]} → {bins["medium"]["new_log_windows"]} '+T('窗口','windows')],ylim=(0,116),ylabel=T('decode token/s（越高越好）','Decode token/s (higher is better)'))
    axs[0,0].set_title(T('同 profile 历史日志','Same-profile service logs'),loc='left',pad=15)
    axs[0,0].legend(frameon=False,loc='upper left',bbox_to_anchor=(0,-.32),ncol=2,fontsize=9)
    q=[d['qwen'][k] for k in ['short','medium','long']];vals=[v['decode_tps_median'] for v in q]
    axs[0,1].bar(range(3),vals,.55,color=COL['new'])
    axs[0,1].errorbar(range(3),vals,yerr=[[v['decode_tps_median']-v['decode_tps_min'] for v in q],[v['decode_tps_max']-v['decode_tps_median'] for v in q]],fmt='none',ecolor=COL['muted'],capsize=3,lw=1)
    for i,v in enumerate(vals):axs[0,1].text(i,v+3.3,f'{v:.2f}',ha='center',fontsize=11)
    labs=[f'{v["prompt_tokens_min"]:,}\nn={v["n"]}' for v in q]
    axs[0,1].set(xticks=range(3),xticklabels=labs,ylim=(0,112),xlabel=T('输入 token 数','Input tokens'),ylabel='decode token/s')
    axs[0,1].set_title(T('当前 C1：86-89 token/s','Current concurrency 1: 86-89 token/s'),loc='left',pad=15)
    vals=[v['ttft_s_median'] for v in q];axs[1,0].bar(range(3),vals,.55,color=COL['new'])
    for i,v in enumerate(vals):axs[1,0].text(i,v+.045,f'{v:.3f}',ha='center',fontsize=11)
    axs[1,0].set(xticks=range(3),xticklabels=labs,ylim=(0,1.9),xlabel=T('输入 token 数','Input tokens'),ylabel=T('TTFT 秒（越低越好）','TTFT seconds (lower is better)'))
    axs[1,0].set_title(T('当前 C1：首 token 延迟','Current concurrency 1: time to first token'),loc='left',pad=15)
    service=d['deployment'];ax=axs[1,1];v=service['output_tokens_per_second']
    ax.barh([0],[v],height=.45,color=COL['resident']);ax.text(v+5,0,f'{v:.2f}',va='center',fontsize=12)
    ax.set(yticks=[0],yticklabels=[T('混合负载','Mixed load')],xlim=(0,272),ylim=(-.6,.6))
    ax.invert_yaxis();axis(ax,T('服务总吞吐 output token/s','Total service output token/s'))
    ax.set_title(T('混合负载总吞吐','Mixed-load total throughput'),loc='left',pad=15)
    ax.text(.02,.025,T('460 请求 · 0 个观察错误\n输入 cache hit 约 79.8%','460 requests · 0 observed errors\nInput-cache hits ~79.8%'),transform=ax.transAxes,va='bottom',fontsize=9,color=COL['muted'])
    for ax in [axs[0,0],axs[0,1],axs[1,0]]:ax.yaxis.grid(True,color=COL['grid'],lw=.7);ax.set_axisbelow(True)
    return finish(fig,T('Qwen 服务性能','Qwen service performance'),
        T('C1 · TP2 · prefix-cache hit = 0 · 每请求输出 512 token · 预热 2 次、测量 17 次',
          'C1 · TP2 · prefix-cache hits = 0 · 512 output tokens/request · 2 warm-ups, 17 measured requests'),
        T('当前 C1 误差线为观测 min-max；历史日志样本数标在横轴。',
          'Current C1 whiskers: observed min-max. Historical log-window counts appear on the x-axis.'),
        'Sources: historical-applications.json | qwen-single.json | deployment-summary.json (2026-10-26)')

def export_tables(d):
    for row in d['mma']:
        for phase,v in row['phases'].items():record('01-overview',row['mode'],phase,v['median'],'TOP/s' if row['mode'] in ['s8/s32','dp4a'] else 'TFLOP/s','controlled_unlock',v['n'],'2026-10-26/ab-a-matched.json')
        for phase in ['B1','A2']:record('01-overview-ratio',row['mode'],phase+'/A1',row['phases'][phase]['median']/row['phases']['A1']['median'],'ratio','controlled_unlock',30,'2026-10-26/ab-a-matched.json')
    for row in d['gemm']:
        for phase,v in row['phases'].items():record('01-overview',row['dtype']+'/'+'x'.join(map(str,row['shape'])),phase,v['tflops'],'TFLOP/s','controlled_unlock',v['n'],'2026-10-26/ab-a-matched.json')
        for phase in ['B1','A2']:record('01-overview-ratio',row['dtype']+'/'+'x'.join(map(str,row['shape'])),phase+'/A1',row['phases'][phase]['tflops']/row['phases']['A1']['tflops'],'ratio','controlled_unlock',10,'2026-10-26/ab-a-matched.json')
    for key,row in d['qwen'].items():
        for metric in ['decode_tps_median','ttft_s_median']:record('06-qwen-service',metric,key,row[metric],'token/s' if metric.startswith('decode') else 's','current_absolute',row['n'],'2026-10-26/qwen-single.json')
    for key in ['short','medium']:
        row=d['history']['qwen_comparable_service_log_bins'][key]
        for v in ['old','new']:record('06-qwen-service','decode',key+'/'+v,row[v+'_median_tps'],'token/s','historical_confounded',row[v+'_log_windows'],'2026-10-26/historical-applications.json')
    record('06-qwen-service','mixed_service_total','current',d['deployment']['output_tokens_per_second'],'output token/s','current_absolute',460,'charts/deployment-summary.json')

def main():
    global LANG
    parser=argparse.ArgumentParser();parser.add_argument('--font');args=parser.parse_args()
    font=Path(args.font or 'C:/Windows/Fonts/msyh.ttc')
    if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    else:plt.rcParams['font.family']='Noto Sans CJK SC'
    style();d=extract()
    HERE.mkdir(exist_ok=True);(HERE/'chart-data.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    specs=[('01-overview',overview),('02-fp8',fp8_chart),('03-moss-kernels',moss_kernels),('04-power-sensitivity',power_chart),('05-moss-service',moss_service),('06-qwen-service',qwen_service)]
    artifacts=[];(OUT/'pdf').mkdir(parents=True,exist_ok=True)
    for lang in ['zh-CN','en']:
        LANG=lang;dest=OUT/lang;dest.mkdir(parents=True,exist_ok=True)
        pdf=OUT/'pdf'/f'benchmark-production-comparison-{lang}.pdf'
        with PdfPages(pdf,metadata={'Title':T('GPU 解锁与生产性能对比','GPU unlock and production performance'),'Author':'mochgolf','Subject':'Fixed 2026-10-26 and 2026-10-29 benchmark evidence'}) as pages:
            for page,(stem,fn) in enumerate(specs,1):
                fig=fn(d)
                fig.text(.965,.015,f'{page:02d} / {len(specs):02d}',ha='right',fontsize=8.2,color=COL['muted'])
                fig.canvas.draw()
                for fmt in ['png','svg']:
                    path=dest/(stem+'.'+fmt);fig.savefig(path,dpi=220)
                    if fmt=='svg':clean_svg(path)
                    artifacts.append(path.relative_to(HERE).as_posix())
                pages.savefig(fig);plt.close(fig)
        artifacts.append(pdf.relative_to(HERE).as_posix())
    # Rendering both languages produces duplicate numeric rows; keep one copy.
    unique={tuple(row.items()):row for row in CSV_ROWS}
    CSV_ROWS[:]=list(unique.values());export_tables(d)
    with (HERE/'chart-data.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['chart','metric','variant','value','unit','comparison_kind','n','source'],lineterminator='\n');writer.writeheader();writer.writerows(CSV_ROWS)
    (HERE/'artifact-manifest.json').write_text(json.dumps({'artifacts':artifacts,'source_sha256':SOURCE_HASHES,'csv_rows':len(CSV_ROWS)},indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({'figures':12,'pdfs':2,'artifacts':len(artifacts),'csv_rows':len(CSV_ROWS)}))

if __name__=='__main__':main()
