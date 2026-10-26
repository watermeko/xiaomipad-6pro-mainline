// SPDX-License-Identifier: MIT
/*
 * Show a full-screen boot choice on the tablet panel from userspace.
 *
 * Runs before the display manager, after the kernel has bound the panel, so
 * it talks to the KMS device directly: dumb buffer, CRTC mode, page flip.
 * Volume up/down moves the highlight, power confirms, and the timeout picks
 * the already-highlighted entry.
 *
 * Exit 0: continue into Ubuntu.
 * Exit 10: the caller switches boot_a to HyperOS and reboots.
 *
 * No libdrm: the few ioctls needed are issued through drm.h, so the tool is a
 * small static binary that the initramfs and the installed root can share.
 */
#define _GNU_SOURCE

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>

#define TIMEOUT_MS 8000

/* libdrm's drmIoctl is a retrying ioctl wrapper; this is the subset used. */
static int drm_ioctl(int fd, unsigned long req, void *arg)
{
	int r;

	do {
		r = ioctl(fd, req, arg);
	} while (r < 0 && (errno == EINTR || errno == EAGAIN));
	return r;
}

/* Connection state values from the kernel ABI (drm_mode.h has no such enum
 * in the uapi header for these). */
#define CONNECTED 1

/* The few DRM helpers used here are inlined so the binary stays libdrm-free:
 * the same static file is dropped into the initramfs and the installed root.
 * The kernel ABI structs come from <drm/drm_mode.h>; only libdrm's wrapper
 * functions are avoided. */

enum { CARD_HYPEROS = 0, CARD_UBUNTU = 1 };

static int selected = CARD_UBUNTU;

/* 5x7 glyphs, one byte per column, bit 0 is the top row. */
static const uint8_t font5x7[][5] = {
	[' '] = { 0, 0, 0, 0, 0 },
	['-'] = { 0x08, 0x08, 0x08, 0x08, 0x08 },
	['0'] = { 0x3e, 0x51, 0x49, 0x45, 0x3e },
	['1'] = { 0x00, 0x42, 0x7f, 0x40, 0x00 },
	['2'] = { 0x42, 0x61, 0x51, 0x49, 0x46 },
	['3'] = { 0x21, 0x41, 0x45, 0x4b, 0x31 },
	['4'] = { 0x18, 0x14, 0x12, 0x7f, 0x10 },
	['5'] = { 0x27, 0x45, 0x45, 0x45, 0x39 },
	['6'] = { 0x3c, 0x4a, 0x49, 0x49, 0x30 },
	['7'] = { 0x01, 0x71, 0x09, 0x05, 0x03 },
	['8'] = { 0x36, 0x49, 0x49, 0x49, 0x36 },
	['9'] = { 0x06, 0x49, 0x49, 0x29, 0x1e },
	['A'] = { 0x7e, 0x11, 0x11, 0x11, 0x7e },
	['B'] = { 0x7f, 0x49, 0x49, 0x49, 0x36 },
	['C'] = { 0x3e, 0x41, 0x41, 0x41, 0x22 },
	['D'] = { 0x7f, 0x41, 0x41, 0x22, 0x1c },
	['E'] = { 0x7f, 0x49, 0x49, 0x49, 0x41 },
	['F'] = { 0x7f, 0x09, 0x09, 0x09, 0x01 },
	['G'] = { 0x3e, 0x41, 0x49, 0x49, 0x7a },
	['H'] = { 0x7f, 0x08, 0x08, 0x08, 0x7f },
	['I'] = { 0x00, 0x41, 0x7f, 0x41, 0x00 },
	['K'] = { 0x7f, 0x08, 0x14, 0x22, 0x41 },
	['L'] = { 0x7f, 0x40, 0x40, 0x40, 0x40 },
	['M'] = { 0x7f, 0x02, 0x0c, 0x02, 0x7f },
	['N'] = { 0x7f, 0x04, 0x08, 0x10, 0x7f },
	['O'] = { 0x3e, 0x41, 0x41, 0x41, 0x3e },
	['P'] = { 0x7f, 0x09, 0x09, 0x09, 0x06 },
	['R'] = { 0x7f, 0x09, 0x19, 0x29, 0x46 },
	['S'] = { 0x46, 0x49, 0x49, 0x49, 0x31 },
	['T'] = { 0x01, 0x01, 0x7f, 0x01, 0x01 },
	['U'] = { 0x3f, 0x40, 0x40, 0x40, 0x3f },
	['V'] = { 0x1f, 0x20, 0x40, 0x20, 0x1f },
	['W'] = { 0x3f, 0x40, 0x38, 0x40, 0x3f },
	['X'] = { 0x63, 0x14, 0x08, 0x14, 0x63 },
	['Y'] = { 0x07, 0x08, 0x70, 0x08, 0x07 },
	['Z'] = { 0x61, 0x51, 0x49, 0x45, 0x43 },
};

static uint32_t *canvas = NULL;
static int fb_w, fb_h, stride_px;

static int64_t now_ms(void)
{
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void px(int x, int y, uint32_t color)
{
	if (x < 0 || y < 0 || x >= fb_w || y >= fb_h)
		return;
	canvas[(size_t)y * stride_px + x] = color;
}

static void fill(int x, int y, int w, int h, uint32_t color)
{
	int ix, iy;
	for (iy = 0; iy < h; iy++)
		for (ix = 0; ix < w; ix++)
			px(x + ix, y + iy, color);
}

static void glyph(int x, int y, int scale, char ch, uint32_t color)
{
	unsigned c = (unsigned char)ch;
	const uint8_t *col;
	int cx, cy, sx, sy;
	unsigned ink = 0;

	if (c >= sizeof(font5x7) / sizeof(font5x7[0]))
		c = ' ';
	col = font5x7[c];
	for (cx = 0; cx < 5; cx++)
		ink |= col[cx];
	if (!ink)
		return;
	for (cx = 0; cx < 5; cx++)
		for (cy = 0; cy < 7; cy++)
			if (col[cx] & (1u << cy))
				for (sx = 0; sx < scale; sx++)
					for (sy = 0; sy < scale; sy++)
						px(x + cx * scale + sx, y + cy * scale + sy, color);
}

static int text_w(const char *s, int scale)
{
	return (int)strlen(s) * 6 * scale;
}

static void text(int x, int y, int scale, const char *s, uint32_t color)
{
	for (; *s; s++, x += 6 * scale)
		glyph(x, y, scale, *s, color);
}

static void text_center(int y, int scale, const char *s, uint32_t color)
{
	text((fb_w - text_w(s, scale)) / 2, y, scale, s, color);
}

static void card(int y, const char *title, const char *sub, int on)
{
	int x = fb_w / 10, w = fb_w - 2 * x, h = fb_h / 7;
	uint32_t bg = on ? 0xf2efe6 : 0x1c2430;
	uint32_t fg = on ? 0x14202b : 0xd7dee6;
	uint32_t edge = on ? 0xc4a35a : 0x2c3848;

	fill(x - 6, y - 6, w + 12, h + 12, edge);
	fill(x, y, w, h, bg);
	text(x + 36, y + h / 2 - 30, 6, title, fg);
	text(x + 36, y + h / 2 + 30, 3, sub, on ? 0x5c4a32 : 0x8ea0b4);
	if (on)
		fill(x + 8, y + 16, 8, h - 32, 0xc4a35a);
}

static void draw_countdown(int remaining, int previous)
{
	char hint[32];

	/* Only the countdown line is repainted.  Rewriting the whole canvas every
	 * second made the panel flash, because the scanout is reading the very
	 * buffer being written. */
	if (previous >= 0) {
		snprintf(hint, sizeof(hint), "CONTINUES IN %d", previous);
		fill(0, fb_h * 82 / 100 - 8, fb_w, 60, 0x10151c);
	}
	snprintf(hint, sizeof(hint), "CONTINUES IN %d", remaining);
	text_center(fb_h * 82 / 100, 3, hint, 0x7d8b99);
}

static void draw_frame(void)
{
	fill(0, 0, fb_w, fb_h, 0x10151c);
	fill(0, 0, fb_w, 8, 0xc4a35a);
	text_center(fb_h / 12, 7, "XIAOMI PAD 6 PRO", 0xf4efe4);
	text_center(fb_h / 12 + 100, 3, "CHOOSE A SYSTEM", 0x9eb0c2);
	card(fb_h * 32 / 100, "HYPEROS", "VOLUME TO MOVE", selected == CARD_HYPEROS);
	card(fb_h * 52 / 100, "UBUNTU", "POWER TO START", selected == CARD_UBUNTU);
	text_center(fb_h * 88 / 100, 2, "VOLUME UP   VOLUME DOWN   POWER", 0x5e6c7a);
}

static int has_key(int fd, int code)
{
	unsigned long bits[(KEY_MAX + 1 + 63) / 64];

	memset(bits, 0, sizeof(bits));
	if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) < 0)
		return 0;
	return (bits[code / 64] >> (code % 64)) & 1;
}

static int open_keys(struct pollfd *out, int cap)
{
	DIR *dir = opendir("/dev/input");
	struct dirent *ent;
	int n = 0;

	if (!dir)
		return 0;
	while ((ent = readdir(dir)) != NULL && n < cap) {
		char path[300];
		int fd;

		if (strncmp(ent->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", ent->d_name);
		fd = open(path, O_RDONLY | O_NONBLOCK);
		if (fd < 0)
			continue;
		if (!has_key(fd, KEY_VOLUMEUP) && !has_key(fd, KEY_VOLUMEDOWN) &&
		    !has_key(fd, KEY_POWER)) {
			close(fd);
			continue;
		}
		out[n].fd = fd;
		out[n].events = POLLIN;
		n++;
	}
	closedir(dir);
	return n;
}

/* First connected connector that publishes at least one mode.
 * Fills *conn_id and *mode, and returns the connector's current encoder id
 * (0 when the connector has never been bound). */
static uint32_t pick_connector(int fd, uint32_t *conn_id, struct drm_mode_modeinfo *mode,
			       int *found)
{
	struct drm_mode_card_res res;
	uint32_t conns[32], crtcs[32];
	uint32_t n, i;

	*found = 0;
	memset(&res, 0, sizeof(res));
	res.connector_id_ptr = (uint64_t)(uintptr_t)conns;
	res.crtc_id_ptr = (uint64_t)(uintptr_t)crtcs;
	res.count_connectors = 32;
	res.count_crtcs = 32;
	if (drm_ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res) < 0)
		return 0;
	n = res.count_connectors > 32 ? 32 : res.count_connectors;
	for (i = 0; i < n; i++) {
		struct drm_mode_get_connector c;
		struct drm_mode_modeinfo *modes;
		uint32_t count;

		memset(&c, 0, sizeof(c));
		c.connector_id = conns[i];
		if (drm_ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) < 0)
			continue;
		if (c.connection != CONNECTED)
			continue;
		/* A connector that reports zero modes can still carry one; the
		 * kernel asks for a one-entry probe before the real count is
		 * known (drm_mode.h, GETCONNECTOR). */
		count = c.count_modes ? c.count_modes : 1;
		modes = calloc(count, sizeof(*modes));
		if (!modes)
			continue;
		memset(&c, 0, sizeof(c));
		c.connector_id = conns[i];
		c.modes_ptr = (uint64_t)(uintptr_t)modes;
		c.count_modes = count;
		if (drm_ioctl(fd, DRM_IOCTL_MODE_GETCONNECTOR, &c) < 0 || c.count_modes == 0) {
			free(modes);
			continue;
		}
		*mode = modes[0];
		free(modes);
		*conn_id = c.connector_id;
		*found = 1;
		return c.encoder_id;
	}
	return 0;
}

int main(void)
{
	struct drm_mode_create_dumb creq;
	struct drm_mode_map_dumb mreq;
	struct drm_mode_fb_cmd fbcmd;
	struct drm_mode_modeinfo mode;
	struct drm_mode_get_encoder enc;
	struct drm_mode_crtc set;
	struct pollfd keys[8];
	uint32_t conn_id = 0, fb_id = 0, crtc = 0;
	int fd, nkeys = 0, i, found;
	int64_t deadline;
	int shown = -1;

	fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	if (fd < 0)
		return 0;

	/* Reuse the CRTC the connector was last bound to; fall back to the first
	 * CRTC the card reports when the bootloader left it unprogrammed. */
	{
		struct drm_mode_card_res res;
		uint32_t crtcs[32];
		uint32_t enc_id;

		enc_id = pick_connector(fd, &conn_id, &mode, &found);
		if (!found)
			goto fail;
		if (enc_id) {
			memset(&enc, 0, sizeof(enc));
			enc.encoder_id = enc_id;
			if (drm_ioctl(fd, DRM_IOCTL_MODE_GETENCODER, &enc) == 0)
				crtc = enc.crtc_id;
		}
		if (!crtc) {
			memset(&res, 0, sizeof(res));
			res.crtc_id_ptr = (uint64_t)(uintptr_t)crtcs;
			res.count_crtcs = 32;
			if (drm_ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &res) < 0 ||
			    res.count_crtcs == 0)
				goto fail;
			crtc = crtcs[0];
		}
	}

	memset(&creq, 0, sizeof(creq));
	creq.width = mode.hdisplay;
	creq.height = mode.vdisplay;
	creq.bpp = 32;
	if (drm_ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq) < 0)
		goto fail;

	memset(&fbcmd, 0, sizeof(fbcmd));
	fbcmd.width = creq.width;
	fbcmd.height = creq.height;
	fbcmd.bpp = 32;
	fbcmd.depth = 24;
	fbcmd.pitch = creq.pitch;
	fbcmd.handle = creq.handle;
	if (drm_ioctl(fd, DRM_IOCTL_MODE_ADDFB, &fbcmd) < 0)
		goto fail;
	fb_id = fbcmd.fb_id;

	memset(&mreq, 0, sizeof(mreq));
	mreq.handle = creq.handle;
	if (drm_ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mreq) < 0)
		goto fail;
	canvas = mmap(NULL, creq.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, mreq.offset);
	if (canvas == MAP_FAILED) {
		canvas = NULL;
		goto fail;
	}
	fb_w = creq.width;
	fb_h = creq.height;
	stride_px = creq.pitch / 4;

	memset(&set, 0, sizeof(set));
	set.crtc_id = crtc;
	set.fb_id = fb_id;
	set.set_connectors_ptr = (uint64_t)(uintptr_t)&conn_id;
	set.count_connectors = 1;
	set.mode_valid = 1;
	memcpy(&set.mode, &mode, sizeof(mode));
	if (drm_ioctl(fd, DRM_IOCTL_MODE_SETCRTC, &set) < 0)
		goto fail;

	draw_frame();
	draw_countdown(TIMEOUT_MS / 1000, -1);

	nkeys = open_keys(keys, 8);
	deadline = now_ms() + TIMEOUT_MS;
	for (;;) {
		int left = (int)((deadline - now_ms() + 999) / 1000);
		int wait, ready;

		if (left < 0)
			left = 0;
		if (left != shown) {
			draw_countdown(left, shown);
			shown = left;
		}
		if (now_ms() >= deadline || nkeys == 0)
			break;
		wait = (int)(deadline - now_ms());
		if (wait > 200)
			wait = 200;
		ready = poll(keys, nkeys, wait);
		if (ready <= 0)
			continue;
		for (i = 0; i < nkeys; i++) {
			struct input_event ev;

			if (!(keys[i].revents & POLLIN))
				continue;
			while (read(keys[i].fd, &ev, sizeof(ev)) == (ssize_t)sizeof(ev)) {
				if (ev.type != EV_KEY || ev.value != 1)
					continue;
				if (ev.code == KEY_VOLUMEUP || ev.code == KEY_VOLUMEDOWN) {
					selected = selected == CARD_HYPEROS ? CARD_UBUNTU : CARD_HYPEROS;
					deadline = now_ms() + TIMEOUT_MS;
					draw_frame();
					shown = -1;
				} else if (ev.code == KEY_POWER) {
					goto done;
				}
			}
		}
	}
done:
	fill(0, 0, fb_w, fb_h, 0x10151c);
	text_center(fb_h / 2 - 30, 5, selected == CARD_HYPEROS ? "HYPEROS" : "UBUNTU", 0xf4efe4);
	usleep(250000);

fail:
	if (canvas)
		munmap(canvas, creq.size);
	for (i = 0; i < nkeys; i++)
		close(keys[i].fd);
	if (fb_id)
		drm_ioctl(fd, DRM_IOCTL_MODE_RMFB, &fb_id);
	close(fd);

	/* Exit 10 is also how the caller learns about the choice, but systemd can
	 * only trigger a unit on "failed", not on a specific exit code.  The marker
	 * lets the HyperOS switch discard every other failure (unreadable display,
	 * missing store) and act on this one only.  /run is fresh on each boot. */
	if (selected == CARD_HYPEROS) {
		int mark;

		mkdir("/run/liuqin-boot-menu", 0755);
		mark = open("/run/liuqin-boot-menu/hyperos", O_CREAT | O_WRONLY, 0644);
		if (mark >= 0)
			close(mark);
	}
	return selected == CARD_HYPEROS ? 10 : 0;
}
