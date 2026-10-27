# SPDX-License-Identifier: GPL-2.0-only
ROOT := $(abspath ../..)
KDIR ?= /lib/modules/$(shell uname -r)/build
BUILD ?= $(ROOT)/build/h13ssl
CC ?= cc
PARSERS := $(addprefix $(ROOT)/kernel/gpu_unlock/,prep_610.c layout_610.c vbios_610.c gfw_eval.c)

.PHONY: all module cold-probe test
all: module cold-probe

module:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

cold-probe:
	mkdir -p $(BUILD)
	$(CC) -O2 -Wall -Wextra -Werror -static -I$(ROOT)/kernel/gpu_unlock \
		gpu_cold_probe.c $(PARSERS) -o $(BUILD)/gpu_cold_probe

test:
	mkdir -p $(BUILD)
	$(CC) -std=c11 -O2 -Wall -Wextra -Werror -I. tests/test_bme_diag.c -o $(BUILD)/test_bme_diag
	$(BUILD)/test_bme_diag
