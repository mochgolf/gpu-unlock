// SPDX-License-Identifier: GPL-2.0-only
/* Single pinned function; no firmware, DMA, reset, selector writes or PCI bind. */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <linux/string.h>
#include <linux/dmi.h>
#include <linux/vgaarb.h>
#include "bme_diag_core.h"

static char *target;
module_param(target,charp,0444);
static bool allow_clear;
module_param(allow_clear,bool,0444);
struct diag_context {struct pci_dev *pdev;void __iomem *bar;};
static int sample(void *data,struct bme_diag_sample *s) {
    struct diag_context *c=data;struct pci_dev *p=c->pdev;
    int ret;
    *s=(struct bme_diag_sample){0};
    s->driver_bound=p->driver!=NULL;s->power_d0=p->current_state==PCI_D0;
    s->has_pm=p->pm_cap!=0;s->boot_vga=vga_default_device()==p;
    ret=pci_read_config_dword(p,PCI_VENDOR_ID,&s->identity);
    ret|=pci_read_config_word(p,PCI_COMMAND,&s->command);
    if(p->pm_cap)ret|=pci_read_config_word(p,p->pm_cap+PCI_PM_CTRL,&s->pmcsr);
    ret|=pcie_capability_read_dword(p,PCI_EXP_DEVCAP,&s->devcap);
    ret|=pcie_capability_read_word(p,PCI_EXP_DEVSTA,&s->devsta);
    if(ret)return -EIO;
#define R(field,offset) s->field=ioread32(c->bar+(offset))
    R(chip,0);R(gfw_plm,0x118128);R(gfw_boot,0x118234);R(gfw_cpu,0x110100);
    R(wpr_lo,0x1fa824);R(wpr_hi,0x1fa828);R(feat_plm,0x823804);
    R(readout,0x823818);R(ss0,0x82381c);R(ss1,0x823820);
    R(perm_cfg,0x1fa7cc);R(perm_fbpa,0x9a0148);R(perm_wpr,0x1fa7c4);R(fb_mb,0x1183a4);
#undef R
    return 0;
}
static int write_command(void *data,u16 value) {
    struct diag_context *c=data;
    return pci_write_config_word(c->pdev,PCI_COMMAND,value);
}
static void show(struct pci_dev *p,const char *phase,const struct bme_diag_sample *s) {
    dev_info(&p->dev,"gpu_bme_diag: %s command=%#x pmcsr=%#x devsta=%#x driver_bound=%d D0=%d chip=%#x gfw=%#x:%#x:%#x wpr2=%#x:%#x feat=%#x ss=%#x:%#x readout=%#x fb_mb=%u\n",
      phase,s->command,s->pmcsr,s->devsta,s->driver_bound,s->power_d0,s->chip,s->gfw_plm,s->gfw_boot,s->gfw_cpu,s->wpr_lo,s->wpr_hi,s->feat_plm,s->ss0,s->ss1,s->readout,s->fb_mb);
}
static int __init diag_init(void) {
    struct pci_dev *p,*display;
    struct diag_context c={0};
    struct bme_diag_sample before={0},after={0};
    struct bme_diag_result result={0};
    struct bme_diag_ops ops={.context=&c,.write_command=write_command,.sample=sample};
    bool claimed=false;int ret;
    if(!target || (strcmp(target,"0000:41:00.0") && strcmp(target,"0000:01:00.0")) || !allow_clear)return -EINVAL;
    if(!dmi_match(DMI_BOARD_NAME,"H13SSL-N") || !dmi_match(DMI_BIOS_VERSION,"3.5"))return -ENODEV;
    display=vga_default_device();
    if(!display || strcmp(pci_name(display),"0000:c6:00.0"))return -ENODEV;
    p=pci_get_domain_bus_and_slot(0,!strcmp(target,"0000:41:00.0")?0x41:0x01,PCI_DEVFN(0,0));
    if(!p)return -ENODEV;
    c.pdev=p;pci_dev_lock(p);
    if(p->vendor!=0x10de || p->device!=0x2684 || p->driver || p->current_state!=PCI_D0 ||
       !pci_is_pcie(p) || (p->dev_flags&PCI_DEV_FLAGS_NO_FLR_RESET) ||
       !(pci_resource_flags(p,0)&IORESOURCE_MEM) || pci_resource_len(p,0)<0x9a014c){ret=-EBUSY;goto out;}
    /* Decode must already be present; this module never enables a function. */
    ret=pci_read_config_word(p,PCI_COMMAND,&before.command);
    if(ret || (before.command!=3 && before.command!=7)){ret=-EINVAL;goto out;}
    ret=pci_request_region(p,0,"gpu_bme_diag");if(ret)goto out;claimed=true;
    c.bar=pci_iomap(p,0,0);if(!c.bar){ret=-ENOMEM;goto out;}
    ret=sample(&c,&before);if(ret)goto out;
    show(p,"before",&before);
    ret=bme_diag_normalize(&ops,&before,&after,&result);
    if(result.after_valid)show(p,"after",&after);
    dev_info(&p->dev,"gpu_bme_diag: result=%d writes=%d before=%#x expected=%#x after=%#x after_valid=%d firmware_started=0 flr=0 dma_allocations=0\n",
      ret,result.writes,before.command,result.wanted,after.command,result.after_valid);
    if(!ret)dev_info(&p->dev,"gpu_bme_diag: QUALIFIED target=%s only\n",target);
out:
    if(c.bar)pci_iounmap(p,c.bar);
    if(claimed)pci_release_region(p,0);
    pci_dev_unlock(p);pci_dev_put(p);
    return ret;
}
static void __exit diag_exit(void) { }
module_init(diag_init);module_exit(diag_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Pinned H13SSL-N AD102 BME-only diagnostic, no firmware or reset");
MODULE_VERSION("0.1.0");
