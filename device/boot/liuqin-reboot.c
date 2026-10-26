// SPDX-License-Identifier: MIT
/*
 * reboot(2) with a reason string for the initramfs.
 *
 * BusyBox's reboot applet calls RB_AUTOBOOT and ignores /sys/kernel/reboot
 * mode, so it cannot ask the bootloader to come up on the fastboot screen.
 * LINUX_REBOOT_CMD_RESTART2 passes the string to the Qualcomm restart
 * handler, which is what `reboot bootloader` does on Android.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <sys/reboot.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LINUX_REBOOT_MAGIC1
#define LINUX_REBOOT_MAGIC1 0xfee1dead
#define LINUX_REBOOT_MAGIC2 672274793
#define LINUX_REBOOT_CMD_RESTART2 0xa1b2c3d4
#endif

int main(int argc, char **argv)
{
	const char *reason = argc > 1 ? argv[1] : "bootloader";

	sync();
	if (syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
		    LINUX_REBOOT_CMD_RESTART2, reason) < 0) {
		perror("reboot");
		return 1;
	}
	return 0;
}
