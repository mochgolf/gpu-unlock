/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "bme_diag_core.h"
struct fake {struct bme_diag_sample state;int mode,writes,reads;};
static int write_fake(void *p,u16 v) {
    struct fake *f=p;f->writes++;assert(!(v&4));
    if(f->mode==1)return -1;
    f->state.command=v;
    if(f->mode==2)f->state.command|=4;
    if(f->mode==3)return -1;
    if(f->mode==6)f->state.command^=1;
    return 0;
}
static int read_fake(void *p,struct bme_diag_sample *s) {
    struct fake *f=p;f->reads++;*s=f->state;
    if(f->mode==4)return -1;
    if(f->mode==5)s->command=0xffff;
    if(f->mode==7)s->devsta=0x20;
    if(f->mode==8)s->ss0^=1;
    return 0;
}
static struct bme_diag_sample base(void) {
    return (struct bme_diag_sample){.identity=0x268410de,.chip=0x192000a1,.command=7,
      .power_d0=1,.has_pm=1,.pmcsr=8,.devcap=1u<<28,.gfw_plm=1,.gfw_boot=255,.gfw_cpu=0x10,
      .feat_plm=0xffffff8f,.readout=0x410080,.ss0=0x03061074,.ss1=1,.fb_mb=49140};
}
int main(void) {
    unsigned count=0;
    for(int mode=0;mode<=8;mode++) {
        struct fake f={.state=base(),.mode=mode};struct bme_diag_sample before=f.state,after={0};
        struct bme_diag_ops ops={&f,write_fake,read_fake};struct bme_diag_result result;
        int ret=bme_diag_normalize(&ops,&before,&after,&result);
        assert((ret==0)==(mode==0));assert(f.writes==1 && result.writes==1);
        assert(f.state.command==7 || f.state.command==3 || (mode==6 && f.state.command==2));
        assert(f.reads==(mode==1 || mode==3?0:1));count++;
    }
    for(int mode=0;mode<11;mode++) {
        struct fake f={.state=base()};
        if(mode==0)f.state.driver_bound=1;
        if(mode==1)f.state.power_d0=0;
        if(mode==2)f.state.pmcsr=3;
        if(mode==3)f.state.boot_vga=1;
        if(mode==4)f.state.wpr_hi=0x1000;
        if(mode==5)f.state.devsta=0x20;
        if(mode==6)f.state.identity=0x220410de;
        if(mode==7)f.state.chip=~0u;
        if(mode==8)f.state.gfw_cpu=0;
        if(mode==9)f.state.readout=0;
        if(mode==10)f.state.fb_mb=24576;
        struct bme_diag_sample after={0};struct bme_diag_ops ops={&f,write_fake,read_fake};struct bme_diag_result result;
        assert(bme_diag_normalize(&ops,&f.state,&after,&result));assert(!f.writes && !f.reads);count++;
    }
    struct fake f={.state=base()};f.state.command=3;
    struct bme_diag_sample after={0};struct bme_diag_ops ops={&f,write_fake,read_fake};struct bme_diag_result result;
    assert(!bme_diag_normalize(&ops,&f.state,&after,&result));assert(!f.writes && f.reads==1);count++;
    printf("{\"cases\":%u,\"pass\":true,\"hardware_accesses\":0}\n",count);
}
