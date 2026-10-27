/* SPDX-License-Identifier: GPL-2.0-only
 * Independent pre-driver sampler. O_RDONLY PCI config/resource0, PROT_READ
 * BAR mapping, volatile loads only. Never enables a PCI function, writes a
 * register, resets hardware, binds a driver, or starts firmware.
 * Pure parsers/layout routines are copied byte-for-byte from the pinned fork.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include "prep_610.h"
#include "vbios_610.h"
#include "gfw_eval.h"

static const char *bdfs[] = {"0000:41:00.0", "0000:01:00.0"};
#ifndef PCI_SYSFS_ROOT
#define PCI_SYSFS_ROOT "/sys/bus/pci/devices"
#endif
#ifndef PROBE_ASSETS
#define PROBE_ASSETS "/gpu-ab/firmware"
#endif
enum { CHIP, GFW_PLM, GFW_BOOT, GFW_CPU, WPR_LO, WPR_HI, FEAT_PLM,
       READOUT0, READOUT1, SS0, SS1, FB_MB, VGA, MMU_PLM, MMU_LO, MMU_HI,
       WPR_CFG, FBPA, WPR_PLM, BOOT_FUSE, REG_COUNT };
static const uint32_t offsets[REG_COUNT] = {
  0,0x118128,0x118234,0x110100,0x1fa824,0x1fa828,0x823804,
  0x823814,0x823818,0x82381c,0x823820,0x1183a4,0x625f04,0x1fa7c8,
  0x1fa82c,0x1fa830,0x1fa7cc,0x9a0148,0x1fa7c4,0x824148
};
static const char *names[REG_COUNT] = {
  "chip","gfw_plm","gfw_boot","gfw_cpuctl","wpr2_lo","wpr2_hi","feat_plm",
  "readout0","readout1","ss0","ss1","fb_mb","vga","mmu_plm","mmu_lo",
  "mmu_hi","wpr_cfg_plm","fbpa_plm","wpr_plm","booter_ucode3_fuse"
};
static uint64_t image_size;
static uint32_t boot_size;
static int candidate_pre;
static int bad(uint32_t v) { return v == UINT32_MAX || (v & 0xffff0000u) == 0xbadf0000u; }
static uint16_t le16(const unsigned char *p) { return p[0] | (uint16_t)p[1]<<8; }
static uint32_t le32(const unsigned char *p) { return le16(p) | (uint32_t)le16(p+2)<<16; }
static void die(const char *what) { perror(what); exit(3); }
static void *readfile(const char *path, size_t *size, size_t maximum) {
  struct stat st; int fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0) die(path);
  if(fstat(fd,&st) || st.st_size<0 || (uint64_t)st.st_size>maximum) die("file size");
  *size=st.st_size; unsigned char *p=malloc(*size?*size:1); if(!p) die("malloc");
  size_t n=0; while(n<*size) { ssize_t got=read(fd,p+n,*size-n); if(got<=0) die("read"); n+=got; }
  close(fd); return p;
}
static void savefile(const char *dir,const char *name,const void *data,size_t size) {
  char path[1024]; if(snprintf(path,sizeof(path),"%s/%s",dir,name)>=(int)sizeof(path)) die("path");
  int fd=open(path,O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC,0600); if(fd<0) die(path);
  const unsigned char *p=data; size_t n=0;
  while(n<size) { ssize_t got=write(fd,p+n,size-n); if(got<=0) die("write output"); n+=got; }
  if(fsync(fd)) die("fsync output");
  close(fd);
}
static int geometry(const char *dir) {
  char path[1024]; size_t n,nd,nb; struct gpu_unlock_span image,signature;
  struct gpu_unlock_boot_desc desc;
  snprintf(path,sizeof(path),"%s/gsp_ga10x.bin",dir); void *gsp=readfile(path,&n,128u<<20);
  int ret=gpu_unlock_elf_section(gsp,n,".fwimage",&image);
  ret |= gpu_unlock_elf_section(gsp,n,".fwsignature_ga10x",&signature);
  free(gsp); if(ret || !image.size || image.size>(128u<<20) || signature.size!=4096) return 1;
  snprintf(path,sizeof(path),"%s/gsp_boot_ad102.bin",dir); void *boot=readfile(path,&nb,1u<<20);free(boot);
  snprintf(path,sizeof(path),"%s/gsp_boot_desc_ad102.bin",dir); void *d=readfile(path,&nd,4096);
  ret=gpu_unlock_boot_desc_parse(d,nd,nb,&desc);free(d); if(ret) return 1;
  image_size=image.size;boot_size=desc.image_size;
  return 0;
}
static int layout(const uint32_t *r,struct gpu_unlock_layout_out *out) {
  struct gpu_unlock_layout_in in={0};
  if(!r[FB_MB] || bad(r[FB_MB]) || bad(r[VGA]) || bad(r[MMU_PLM]) || !(r[MMU_PLM]&1) || bad(r[MMU_LO]) || bad(r[MMU_HI])) return 1;
  in.usable_fb=(uint64_t)r[FB_MB]<<20;
  if(in.usable_fb<(256ull<<20)) return 1;
  in.vga_base=in.usable_fb-(1ull<<20);
  if(r[VGA] & 8) { in.vga_base=(uint64_t)(r[VGA]>>8)<<16; if(in.vga_base<in.usable_fb-(1ull<<20)) in.vga_base=in.usable_fb-0x20000; }
  if(in.vga_base>=in.usable_fb) return 1;
  in.mmu_lock_low=(uint64_t)(r[MMU_LO]>>4)<<12;
  uint64_t hi=(uint64_t)(r[MMU_HI]>>4)<<12, top=(hi+0xffffull)&~0xffffull;
  in.mmu_lock_valid=hi>=in.mmu_lock_low && (top>>20)==(in.usable_fb>>20);
  in.frts_size=1ull<<20;in.boot_size=boot_size;in.image_size=image_size;
  in.nonwpr_size=1ull<<20;in.heap_request=88ull<<20;
  int ret=gpu_unlock_layout(&in,out);
  return ret || out->nonwpr_start<in.usable_fb-(256ull<<20);
}
static unsigned sample(unsigned card,const char *dir,int post) {
  char base[256],path[512],text[128]={0}; unsigned mask=0; uint32_t r[REG_COUNT]={0};
  unsigned char config[256]={0}; uint16_t command=0xffff,pmcsr=0xffff,devsta=0xffff; uint32_t devcap=0;
  int flr=0,power_d0=0,pm_present=0,fd=-1; volatile unsigned char *bar=MAP_FAILED;
  struct gpu_unlock_layout_out lo={0}; struct gpu_unlock_fwsec fw={0};
  int layout_result=-1,fw_result=-1; uint32_t fuse=0,sigoff=0;
  snprintf(base,sizeof(base),"%s/%s",PCI_SYSFS_ROOT,bdfs[card]);
  snprintf(path,sizeof(path),"%s/driver",base); if(access(path,F_OK)==0) mask|=1;
  snprintf(path,sizeof(path),"%s/config",base); fd=open(path,O_RDONLY|O_CLOEXEC);
  if(fd<0 || pread(fd,config,sizeof(config),0)!=(ssize_t)sizeof(config)) mask|=2;
  if(fd>=0) close(fd);
  fd=-1;
  if(le32(config)!=0x268410deu) mask|=2;
  command=le16(config+4);if(!(command&2))mask|=4;if(command&4)mask|=8;
  if(candidate_pre && command!=3 && command!=7)mask|=65536;
  unsigned seen[256]={0},cap=config[0x34]&0xfc;
  for(unsigned count=0;cap && count<48;count++) {
    if(cap<0x40 || cap>0xf0 || seen[cap]) { mask|=2;break; } seen[cap]=1;
    if(config[cap]==1) { pm_present=1;pmcsr=le16(config+cap+4); }
    if(config[cap]==0x10) {devcap=le32(config+cap+4);devsta=le16(config+cap+10);}
    cap=config[cap+1]&0xfc;
  }
  snprintf(path,sizeof(path),"%s/power_state",base);fd=open(path,O_RDONLY|O_CLOEXEC);
  if(fd>=0) { int n=read(fd,text,sizeof(text)-1);close(fd);if(n>0)power_d0=!strcmp(text,"D0\n"); }
  if(!power_d0 || (pm_present && (pmcsr&3)))mask|=16;
  memset(text,0,sizeof(text));snprintf(path,sizeof(path),"%s/reset_method",base);fd=open(path,O_RDONLY|O_CLOEXEC);
  if(fd>=0) { int n=read(fd,text,sizeof(text)-1);close(fd);if(n>0)flr=strstr(text,"flr")!=NULL; }
  if(!flr || !(devcap&(1u<<28)))mask|=32;
  if(devsta==0xffff || (devsta&0x20))mask|=32768;
  /* BME is only recorded/rejected; it is never cleared. No mapping at all if
   * identity, decode, power, or exclusive driver absence cannot be established. */
  if(!(mask & (1|2|4|16))) {
    snprintf(path,sizeof(path),"%s/resource0",base);fd=open(path,O_RDONLY|O_CLOEXEC);
    struct stat st;
    if(fd<0 || fstat(fd,&st) || st.st_size<0x9a014c)mask|=64;
    else bar=mmap(NULL,st.st_size,PROT_READ,MAP_SHARED,fd,0);
    if(bar==MAP_FAILED)mask|=64;
    else {
      for(unsigned i=0;i<REG_COUNT;i++)r[i]=*(volatile const uint32_t *)(bar+offsets[i]);
      if(!r[CHIP] || bad(r[CHIP]) || bad(r[READOUT1]))mask|=64;
      struct gpu_unlock_gfw_sample gs={.config_ok=true,.plm=r[GFW_PLM],.boot=r[GFW_BOOT],.cpuctl=r[GFW_CPU]};
      if(gpu_unlock_gfw_assess(&gs))mask|=128;
      if(post!=1 && (r[FEAT_PLM]==UINT32_MAX || (r[SS0]==0x88888888 && r[SS1]==8)))mask|=256;
      if(bad(r[WPR_HI]) || (r[WPR_HI]>>4))mask|=512;
      if(!post) {
        layout_result=layout(r,&lo);
        /* Use the fork's actual usable-FB calculation and range checks. The
         * board reports 49140 MiB usable, not the advertised 49152 MiB raw size.
         * Post-driver capacity is independently pinned by the controller. */
        if(layout_result)mask|=1024;
        size_t n=1u<<20;unsigned char *rom=malloc(n);if(!rom)die("PROM buffer");
        for(size_t j=0;j<n;j++)rom[j]=bar[0x300000+j];
        snprintf(path,sizeof(path),"%s.prom.bin",card?"control":"target");savefile(dir,path,rom,n);
        fw_result=gpu_unlock_vbios_fwsec(rom,n,&fw);
        if(!fw_result && fw.ucode_id && fw.ucode_id<=64) {
          fuse=*(volatile const uint32_t *)(bar+0x8241c0+(fw.ucode_id-1)*4);
          fw_result=gpu_unlock_fwsec_sig_offset(fw.sig_versions,gpu_unlock_fuse_version(fuse),384,&sigoff);
        } else fw_result=1;
        if(fw_result || bad(fuse) || fw.engine_mask!=0x400 ||
           ((fw.imem_size+255u)&~255u)>fw.image_size ||
           (uint64_t)fw.data_off+((fw.dmem_size+255u)&~255u)>fw.image_size) mask|=2048;
        free(rom);
      }
      if(post==1 && (r[SS0]!=0x88888888 || r[SS1]!=8 || r[READOUT1]&0x07ffffff ||
          r[FEAT_PLM]!=UINT32_MAX || !(r[GFW_CPU]&0x10) || bad(r[GFW_CPU]))) mask|=4096;
      {
        uint32_t fingerprint[]={r[FEAT_PLM],r[READOUT0],r[READOUT1],r[SS0],r[SS1],r[WPR_CFG],r[FBPA],r[WPR_PLM]};
        if(!post) {
          snprintf(path,sizeof(path),"%s-fingerprint.bin",card?"control":"target");savefile(dir,path,fingerprint,sizeof(fingerprint));
          snprintf(path,sizeof(path),"%s-command.bin",card?"control":"target");savefile(dir,path,&command,sizeof(command));
        } else {
          size_t n;
          if(post==1) {
            /* FLR restores ordinary WPR/FBPA permissions. The fork requires
             * full FEAT/selectors/readout after FLR, not payload-time WPR PLMs.
             * Pin these restored permissions to this boot's cold snapshot. */
            snprintf(path,sizeof(path),"%s/%s-fingerprint.bin",dir,card?"control":"target");
            uint32_t *prior=readfile(path,&n,sizeof(fingerprint));
            if(n!=sizeof(fingerprint) || prior[5]!=fingerprint[5] || prior[6]!=fingerprint[6] || prior[7]!=fingerprint[7])mask|=131072;
            free(prior);
          }
          if(post==2) {
            snprintf(path,sizeof(path),"%s/%s-fingerprint.bin",dir,card?"control":"target");
            void *prior=readfile(path,&n,sizeof(fingerprint));if(n!=sizeof(fingerprint)||memcmp(prior,fingerprint,n))mask|=8192;free(prior);
          }
          snprintf(path,sizeof(path),"%s/%s-command.bin",dir,card?"control":"target");
          uint16_t *prior=readfile(path,&n,2);
          if(n!=2 || command!=(*prior&~4u))mask|=65536;
          free(prior);
        }
      }
      if(munmap((void *)bar,st.st_size))die("munmap");
    }
    if(fd>=0)close(fd);
    /* Detect unexpected identity/command/driver drift during the sample. */
    snprintf(path,sizeof(path),"%s/config",base);fd=open(path,O_RDONLY|O_CLOEXEC);unsigned char after[6];
    if(fd<0 || pread(fd,after,6,0)!=6 || memcmp(after,config,6))mask|=16384;
    if(fd>=0)close(fd);
    snprintf(path,sizeof(path),"%s/driver",base);if(access(path,F_OK)==0)mask|=16384;
  }
  printf("{\"bdf\":\"%s\",\"mask\":%u,\"command\":%u,\"power_d0\":%s,\"pmcsr\":%u,\"devcap\":%u,\"devsta\":%u,\"flr\":%s,\"registers\":{",bdfs[card],mask,command,power_d0?"true":"false",pmcsr,devcap,devsta,flr?"true":"false");
  for(unsigned i=0;i<REG_COUNT;i++)printf("%s\"%s\":%u",i?",":"",names[i],r[i]);
  printf("},\"layout_result\":%d,\"layout\":{\"nonwpr\":%llu,\"wpr_start\":%llu,\"heap\":%llu,\"gsp\":%llu,\"boot\":%llu,\"frts\":%llu,\"wpr_end\":%llu},",layout_result,(unsigned long long)lo.nonwpr_start,(unsigned long long)lo.wpr_start,(unsigned long long)lo.heap_offset,(unsigned long long)lo.gsp_offset,(unsigned long long)lo.boot_offset,(unsigned long long)lo.frts_offset,(unsigned long long)lo.wpr_end);
  printf("\"fwsec\":{\"parse_result\":%d,\"engine_mask\":%u,\"ucode_id\":%u,\"fuse\":%u,\"signature_offset\":%u,\"image_size\":%u,\"imem_size\":%u,\"data_offset\":%u,\"dmem_size\":%u}}",fw_result,fw.engine_mask,fw.ucode_id,fuse,sigoff,fw.image_size,fw.imem_size,fw.data_off,fw.dmem_size);
  return mask;
}
int main(int argc,char **argv) {
  if(argc!=3 || (strcmp(argv[1],"--assets") && strcmp(argv[1],"--cold") && strcmp(argv[1],"--cold-candidate") && strcmp(argv[1],"--post-bme-diag") && strcmp(argv[1],"--post-unlock")))return 3;
  if(!strcmp(argv[1],"--assets")) {
    if(geometry(argv[2]))return 3;
    printf("{\"image_size\":%llu,\"boot_size\":%u}\n",(unsigned long long)image_size,boot_size);return 0;
  }
  int post=!strcmp(argv[1],"--post-unlock")?1:!strcmp(argv[1],"--post-bme-diag")?2:0;
  candidate_pre=!strcmp(argv[1],"--cold-candidate");
  if(geteuid()!=0 || (!post && geometry(PROBE_ASSETS)))return 3;
  printf("{\"schema\":2,\"mode\":\"%s\",\"devices\":[",argv[1]+2);
  unsigned target_mask=sample(0,argv[2],post);printf(",");unsigned control_mask=sample(1,argv[2],post);
  unsigned raw=target_mask|control_mask;
  unsigned policy=candidate_pre?((target_mask|control_mask)&~8u):raw;
  printf("],\"eligible\":%s,\"policy_pass\":%s,\"bme_normalization_profile\":%s}\n",raw?"false":"true",policy?"false":"true",candidate_pre||post?"true":"false");
  return policy?2:0;
}
