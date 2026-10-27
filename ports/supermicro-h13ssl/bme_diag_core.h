/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef GPU_BME_DIAG_CORE_H
#define GPU_BME_DIAG_CORE_H
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/errno.h>
#else
#include <stdint.h>
#include <errno.h>
typedef uint16_t u16;
typedef uint32_t u32;
#endif
struct bme_diag_sample {
    u32 identity,chip,gfw_plm,gfw_boot,gfw_cpu,wpr_lo,wpr_hi;
    u32 feat_plm,readout,ss0,ss1,perm_cfg,perm_fbpa,perm_wpr,fb_mb,devcap;
    u16 command,pmcsr,devsta;
    int driver_bound,power_d0,boot_vga,has_pm;
};
struct bme_diag_result { int error,writes,after_valid;u16 wanted; };
struct bme_diag_ops {
    void *context;
    int (*write_command)(void *,u16);
    int (*sample)(void *,struct bme_diag_sample *);
};
static int bme_diag_bad(u32 value) { return value==~(u32)0 || (value&0xffff0000u)==0xbadf0000u; }
static int bme_diag_validate(const struct bme_diag_sample *s) {
    if(s->identity!=0x268410deu || s->chip!=0x192000a1u)return -ENODEV;
    if(s->driver_bound || s->boot_vga)return -EBUSY;
    if(!s->power_d0 || !s->has_pm || (s->pmcsr&3))return -EOPNOTSUPP;
    if(!(s->devcap&(1u<<28)))return -EOPNOTSUPP;
    if(s->devsta==0xffff || (s->devsta&0x20))return -EBUSY;
    if(s->command!=3 && s->command!=7)return -EINVAL;
    if(bme_diag_bad(s->gfw_plm) || bme_diag_bad(s->gfw_boot) || bme_diag_bad(s->gfw_cpu) ||
       !(s->gfw_plm&1) || (s->gfw_boot&255)!=255 || !(s->gfw_cpu&0x10))return -EBUSY;
    if(bme_diag_bad(s->wpr_hi) || s->wpr_hi>>4)return -EBUSY;
    if(s->feat_plm==~(u32)0 || (s->feat_plm&0xffff0000u)==0xbadf0000u ||
       bme_diag_bad(s->readout) || !(s->readout&0x07ffffffu) ||
       bme_diag_bad(s->ss0) || bme_diag_bad(s->ss1) || (s->ss0==0x88888888u && s->ss1==8))return -EBUSY;
    if(s->fb_mb!=49140)return -ERANGE; /* pinned usable capacity on this host */
    return 0;
}
static int bme_diag_normalize(const struct bme_diag_ops *ops,
                              const struct bme_diag_sample *before,
                              struct bme_diag_sample *after,
                              struct bme_diag_result *result) {
    int ret;
    *result=(struct bme_diag_result){0};
    ret=bme_diag_validate(before);
    if(ret)goto out;
    result->wanted=before->command&~4u;
    if(before->command&4) {
        result->writes=1;
        ret=ops->write_command(ops->context,result->wanted);
        if(ret){ret=-EIO;goto out;}
    }
    ret=ops->sample(ops->context,after);
    if(ret){ret=-EIO;goto out;}
    result->after_valid=1;
    if(after->command!=result->wanted){ret=-EIO;goto out;}
    ret=bme_diag_validate(after);
    if(ret)goto out;
    if(before->chip!=after->chip || before->wpr_lo!=after->wpr_lo || before->wpr_hi!=after->wpr_hi ||
       before->feat_plm!=after->feat_plm || before->readout!=after->readout ||
       before->ss0!=after->ss0 || before->ss1!=after->ss1 || before->perm_cfg!=after->perm_cfg ||
       before->perm_fbpa!=after->perm_fbpa || before->perm_wpr!=after->perm_wpr){ret=-EIO;goto out;}
out:
    /* No restoration or retry: never turn incoming firmware MASTER back on. */
    result->error=ret;return ret;
}
#endif
