/*
 * (C) Gražvydas "notaz" Ignotas, 2006-2012
 *
 * This work is licensed under the terms of any of these licenses
 * (at your option):
 *  - GNU GPL, version 2 or later.
 *  - GNU LGPL, version 2.1 or later.
 *  - MAME license.
 * See the COPYING file in the top-level directory.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <time.h>
#include <locale.h> // savestate date

#include "menu.h"
#include "fonts.h"
#include "readpng.h"
#include "lprintf.h"
#include "input.h"
#include "plat.h"
#include "posix.h"

#if defined(__GNUC__) && __GNUC__ >= 7
#pragma GCC diagnostic ignored "-Wformat-truncation"
#endif

static char static_buff[64];
static int  menu_error_time = 0;
char menu_error_msg[64] = { 0, };
// g_menuscreen is the current output buffer the menu is rendered to.
void *g_menuscreen_ptr;
// g_menubg is the menu background and has the same w/h as g_menuscreen, but
// pp=w. It is filled on menu entry from file or from g_menubg_src if available.
void *g_menubg_ptr;
// g_menubg_src points to a buffer containing a bg image. This is usually either
// the emulator screen buffer or the host frame buffer.
void *g_menubg_src_ptr;

int g_menuscreen_w;
int g_menuscreen_h;
int g_menuscreen_pp;
int g_menubg_src_w;
int g_menubg_src_h;
int g_menubg_src_pp;

int g_autostateld_opt;

static unsigned char *menu_font_data = NULL;
static int menu_text_color = 0xfffe; // default to white
static int menu_sel_color = -1; // disabled

/* note: these might become non-constant in future */
#if MENU_X2
static const int me_mfont_w = 16, me_mfont_h = 20;
static const int me_sfont_w = 12, me_sfont_h = 20;
#else
static const int me_mfont_w = 8, me_mfont_h = 10;
static const int me_sfont_w = 6, me_sfont_h = 10;
#endif

static int g_menu_filter_off;
static int g_border_style;
static int border_left, border_right, border_top, border_bottom;

void menuscreen_memset_lines(unsigned short *dst, int c, int l)
{
	for (; l > 0; l--, dst += g_menuscreen_pp)
		memset(dst, c, g_menuscreen_w * 2);
}

void menu_draw_rect(int x, int y, int w, int h, unsigned short color)
{
	unsigned short *dst;
	int i;

	if (x < 0) w += x, x = 0;
	if (y < 0) h += y, y = 0;
	if (x + w > g_menuscreen_w) w = g_menuscreen_w - x;
	if (y + h > g_menuscreen_h) h = g_menuscreen_h - y;
	if (w <= 0 || h <= 0)
		return;

	dst = (unsigned short *)g_menuscreen_ptr + y * g_menuscreen_pp + x;
	while (h-- > 0) {
		for (i = 0; i < w; i++)
			dst[i] = color;
		dst += g_menuscreen_pp;
	}
}

void menu_draw_frame(int x, int y, int w, int h, unsigned short color)
{
	menu_draw_rect(x, y, w, 1, color);
	menu_draw_rect(x, y + h - 1, w, 1, color);
	menu_draw_rect(x, y, 1, h, color);
	menu_draw_rect(x + w - 1, y, 1, h, color);
}

#ifdef __PSP__
static void menu_draw_image(int x, int y, int w, int h,
	const unsigned short *src, int src_pitch)
{
	unsigned short *dst;
	int row;

	if (src == NULL || src_pitch < w || w <= 0 || h <= 0)
		return;
	if (x >= g_menuscreen_w || y >= g_menuscreen_h ||
		(long long)x + w <= 0 || (long long)y + h <= 0)
		return;
	if (x < 0) {
		src -= x;
		w += x;
		x = 0;
	}
	if (y < 0) {
		src -= y * src_pitch;
		h += y;
		y = 0;
	}
	if (x + w > g_menuscreen_w)
		w = g_menuscreen_w - x;
	if (y + h > g_menuscreen_h)
		h = g_menuscreen_h - y;
	if (w <= 0 || h <= 0)
		return;
	dst = (unsigned short *)g_menuscreen_ptr + y * g_menuscreen_pp + x;
	for (row = 0; row < h; row++) {
		memcpy(dst, src, w * sizeof(*src));
		dst += g_menuscreen_pp;
		src += src_pitch;
	}
}
#endif

// draws text to current bbp16 screen
static void text_out16_(int x, int y, const char *text, int color)
{
	int i, lh, tr, tg, tb, len;
	unsigned short *dest = (unsigned short *)g_menuscreen_ptr + x + y * g_menuscreen_pp;
	tr = PXGETR(color);
	tg = PXGETG(color);
	tb = PXGETB(color);

	if (text == (void *)1)
	{
		// selector symbol
		text = "";
		len = 1;
	}
	else
	{
		const char *p;
		for (p = text; *p != 0 && *p != '\n'; p++)
			;
		len = p - text;
	}

	lh = me_mfont_h;
	if (y + lh > g_menuscreen_h)
		lh = g_menuscreen_h - y;

	for (i = 0; i < len; i++)
	{
		unsigned char  *src = menu_font_data + (unsigned int)text[i] * me_mfont_w * me_mfont_h / 2;
		unsigned short *dst = dest;
		int u, l;

		for (l = 0; l < lh; l++, dst += g_menuscreen_pp - me_mfont_w)
		{
			for (u = me_mfont_w / 2; u > 0; u--, src++)
			{
				int c, r, g, b;
				c = *src >> 4;
				r = PXGETR(*dst);
				g = PXGETG(*dst);
				b = PXGETB(*dst);
				r = (c^0xf)*r/15 + c*tr/15;
				g = (c^0xf)*g/15 + c*tg/15;
				b = (c^0xf)*b/15 + c*tb/15;
				*dst++ = PXMAKE(r, g, b);
				c = *src & 0xf;
				r = PXGETR(*dst);
				g = PXGETG(*dst);
				b = PXGETB(*dst);
				r = (c^0xf)*r/15 + c*tr/15;
				g = (c^0xf)*g/15 + c*tg/15;
				b = (c^0xf)*b/15 + c*tb/15;
				*dst++ = PXMAKE(r, g, b);
			}
		}
		dest += me_mfont_w;
	}

	if (x < border_left)
		border_left = x;
	if (x + i * me_mfont_w > border_right)
		border_right = x + i * me_mfont_w;
	if (y < border_top)
		border_top = y;
	if (y + me_mfont_h > border_bottom)
		border_bottom = y + me_mfont_h;
}

void text_out16(int x, int y, const char *texto, ...)
{
	va_list args;
	char    buffer[256];
	int     maxw = (g_menuscreen_w - x) / me_mfont_w;

	if (maxw < 0)
		return;

	va_start(args, texto);
	vsnprintf(buffer, sizeof(buffer), texto, args);
	va_end(args);

	if (maxw > sizeof(buffer) - 1)
		maxw = sizeof(buffer) - 1;
	buffer[maxw] = 0;

	text_out16_(x,y,buffer,menu_text_color);
}

/* draws in 6x8 font, might multiply size by integer */
static void smalltext_out16_(int x, int y, const char *texto, int color)
{
	unsigned char  *src;
	unsigned short *dst;
	int multiplier = me_sfont_w / 6;
	int i;

	for (i = 0;; i++, x += me_sfont_w)
	{
		unsigned char c = (unsigned char) texto[i];
		int h = 8;

		if (!c || c == '\n')
			break;

		src = fontdata6x8[c];
		dst = (unsigned short *)g_menuscreen_ptr + x + y * g_menuscreen_pp;

		while (h--)
		{
			int m, w2, h2;
			for (h2 = multiplier; h2 > 0; h2--)
			{
				for (m = 0x20; m; m >>= 1) {
					if (*src & m)
						for (w2 = multiplier; w2 > 0; w2--)
							*dst++ = color;
					else
						dst += multiplier;
				}

				dst += g_menuscreen_pp - me_sfont_w;
			}
			src++;
		}
	}
}

static void smalltext_out16(int x, int y, const char *texto, int color)
{
	char buffer[128];
	int maxw = (g_menuscreen_w - x) / me_sfont_w;

	if (maxw < 0)
		return;
	if (maxw > sizeof(buffer) - 1)
		maxw = sizeof(buffer) - 1;

	strncpy(buffer, texto, maxw);
	buffer[maxw] = 0;

	smalltext_out16_(x, y, buffer, color);
}

static void menu_draw_selection(int x, int y, int w)
{
	int i, h;
	unsigned short *dst, *dest;

	text_out16_(x, y, (void *)1, (menu_sel_color < 0) ? menu_text_color : menu_sel_color);

	if (menu_sel_color < 0) return; // no selection hilight

	if (y > 0) y--;
	dest = (unsigned short *)g_menuscreen_ptr + x + y * g_menuscreen_pp + me_mfont_w * 2 - 2;
	for (h = me_mfont_h + 1; h > 0; h--)
	{
		dst = dest;
		for (i = w - (me_mfont_w * 2 - 2); i > 0; i--)
			*dst++ = menu_sel_color;
		dest += g_menuscreen_pp;
	}
}

static int parse_hex_color(char *buff)
{
	char *endp = buff;
	int t = (int) strtoul(buff, &endp, 16);
	if (endp != buff)
		return PXMAKE((t>>16)&0xff, (t>>8)&0xff,t&0xff);
	return -1;
}

static char tolower_simple(char c)
{
	if ('A' <= c && c <= 'Z')
		c = c - 'A' + 'a';
	return c;
}

void menu_init_base(void)
{
	int i, c, l, pos;
	unsigned char *fd, *fds;
	char buff[256];
	FILE *f;

	if (menu_font_data != NULL)
		free(menu_font_data);

	menu_font_data = calloc((MENU_X2 ? 256 * 320 : 128 * 160) / 2, 1);
	if (menu_font_data == NULL)
		return;

	// generate default 8x10 font from fontdata8x8
	for (c = 0, fd = menu_font_data; c < 128; c++)
	{
		for (l = 0; l < 8; l++)
		{
			unsigned char fd8x8 = fontdata8x8[c*8+l];
			if (fd8x8&0x80) { *fd  = 0xf0; }
			if (fd8x8&0x40) { *fd |= 0x0f; }; fd++;
			if (fd8x8&0x20) { *fd  = 0xf0; }
			if (fd8x8&0x10) { *fd |= 0x0f; }; fd++;
			if (fd8x8&0x08) { *fd  = 0xf0; }
			if (fd8x8&0x04) { *fd |= 0x0f; }; fd++;
			if (fd8x8&0x02) { *fd  = 0xf0; }
			if (fd8x8&0x01) { *fd |= 0x0f; }; fd++;
		}
		fd += 8*2/2; // 2 empty lines
	}

	if (MENU_X2) {
		// expand default font
		fds = menu_font_data + 128 * 160 / 2 - 4;
		fd  = menu_font_data + 256 * 320 / 2 - 1;
		for (c = 255; c >= 0; c--)
		{
			for (l = 9; l >= 0; l--, fds -= 4)
			{
				for (i = 3; i >= 0; i--) {
					int px = fds[i] & 0x0f;
					*fd-- = px | (px << 4);
					px = (fds[i] >> 4) & 0x0f;
					*fd-- = px | (px << 4);
				}
				for (i = 3; i >= 0; i--) {
					int px = fds[i] & 0x0f;
					*fd-- = px | (px << 4);
					px = (fds[i] >> 4) & 0x0f;
					*fd-- = px | (px << 4);
				}
			}
		}
	}

	// load custom font and selector (stored as 1st symbol in font table)
	pos = plat_get_skin_dir(buff, sizeof(buff));
	strcpy(buff + pos, "font.png");
	readpng(menu_font_data, buff, READPNG_FONT,
		MENU_X2 ? 256 : 128, MENU_X2 ? 320 : 160);
	// default selector symbol is '>'
	memcpy(menu_font_data, menu_font_data + ((int)'>') * me_mfont_w * me_mfont_h / 2,
		me_mfont_w * me_mfont_h / 2);
	strcpy(buff + pos, "selector.png");
	readpng(menu_font_data, buff, READPNG_SELECTOR, me_mfont_w, me_mfont_h);

	// load custom colors
	strcpy(buff + pos, "skin.txt");
	f = fopen(buff, "r");
	if (f != NULL)
	{
		lprintf("found skin.txt\n");
		while (!feof(f))
		{
			if (fgets(buff, sizeof(buff), f) == NULL)
				break;
			if (buff[0] == '#'  || buff[0] == '/')  continue; // comment
			if (buff[0] == '\r' || buff[0] == '\n') continue; // empty line
			if (strncmp(buff, "text_color=", 11) == 0)
			{
				int tmp = parse_hex_color(buff+11);
				if (tmp >= 0) menu_text_color = tmp;
				else lprintf("skin.txt: parse error for text_color\n");
			}
			else if (strncmp(buff, "selection_color=", 16) == 0)
			{
				int tmp = parse_hex_color(buff+16);
				if (tmp >= 0) menu_sel_color = tmp;
				else lprintf("skin.txt: parse error for selection_color\n");
			}
			else
				lprintf("skin.txt: parse error: %s\n", buff);
		}
		fclose(f);
	}

	// use user's locale for savestate date display
	setlocale(LC_TIME, "");
}

static void menu_darken_bg(void *dst, void *src, int pixels, int darker)
{
	unsigned int *dest = dst;
	unsigned int *sorc = src;
	pixels /= 2;
	if (darker)
	{
		while (pixels--)
		{
			unsigned int p = *sorc++;
			*dest++ = (PXMASKH(p,1)>>1) - (PXMASKH(p,3)>>3);
		}
	}
	else
	{
		while (pixels--)
		{
			unsigned int p = *sorc++;
			*dest++ = (PXMASKH(p,1)>>1);
		}
	}
}

static void menu_darken_text_bg(void)
{
	int x, y, xmin, xmax, ymax, ls;
	unsigned short *screen = g_menuscreen_ptr;

	xmin = border_left - 3;
	if (xmin < 0)
		xmin = 0;
	xmax = border_right + 2;
	if (xmax > g_menuscreen_w - 1)
		xmax = g_menuscreen_w - 1;

	y = border_top - 3;
	if (y < 0)
		y = 0;
	ymax = border_bottom + 2;
	if (ymax > g_menuscreen_h - 1)
		ymax = g_menuscreen_h - 1;

	for (x = xmin; x <= xmax; x++)
		screen[y * g_menuscreen_pp + x] = PXMAKE(0xa0, 0xa0, 0xa0);
	for (y++; y < ymax; y++)
	{
		ls = y * g_menuscreen_pp;
		screen[ls + xmin] = 0xffff;
		for (x = xmin + 1; x < xmax; x++)
		{
			unsigned int p = screen[ls + x];
			if (p != menu_text_color)
				screen[ls + x] = (PXMASKH(p,1)>>1) - (PXMASKH(p,3)>>3);
		}
		screen[ls + xmax] = 0xffff;
	}
	ls = y * g_menuscreen_pp;
	for (x = xmin; x <= xmax; x++)
		screen[ls + x] = 0xffff;
}

static int borders_pending;

static void menu_reset_borders(void)
{
	border_left = g_menuscreen_w;
	border_right = 0;
	border_top = g_menuscreen_h;
	border_bottom = 0;
}

static void menu_draw_begin(int need_bg, int no_borders)
{
	int y;

	plat_video_menu_begin();

	menu_reset_borders();
	borders_pending = g_border_style && !no_borders;

	if (need_bg) {
		if (g_border_style && no_borders) {
			for (y = 0; y < g_menuscreen_h; y++)
				menu_darken_bg((short *)g_menuscreen_ptr + g_menuscreen_pp * y,
					(short *)g_menubg_ptr + g_menuscreen_w * y, g_menuscreen_w, 1);
		}
		else {
			for (y = 0; y < g_menuscreen_h; y++)
				memcpy((short *)g_menuscreen_ptr + g_menuscreen_pp * y,
					(short *)g_menubg_ptr + g_menuscreen_w * y, g_menuscreen_w * 2);
		}
	}
}

static void menu_draw_end(void)
{
	if (borders_pending)
		menu_darken_text_bg();
	plat_video_menu_end();
}

static void menu_separation(void)
{
	if (borders_pending) {
		menu_darken_text_bg();
		menu_reset_borders();
	}
}

static int me_id2offset(const menu_entry *ent, menu_id id)
{
	int i;
	for (i = 0; ent->name; ent++, i++)
		if (ent->id == id) return i;

	lprintf("%s: id %i not found\n", __FUNCTION__, id);
	return 0;
}

static void me_enable(menu_entry *entries, menu_id id, int enable)
{
	int i = me_id2offset(entries, id);
	entries[i].enabled = !!enable;
}

static int me_count(const menu_entry *ent)
{
	int ret;

	for (ret = 0; ent->name; ent++, ret++)
		;

	return ret;
}

static unsigned int me_read_onoff(const menu_entry *ent)
{
	return *(unsigned int *)ent->var & ent->mask;
}

static void me_toggle_onoff(menu_entry *ent)
{
	*(unsigned int *)ent->var ^= ent->mask;
}

static void me_draw(const menu_entry *entries, int sel, void (*draw_more)(void))
{
	const menu_entry *ent, *ent_sel = entries;
	int x, y, w = 0, h = 0;
	int offs, col2_offs = 27 * me_mfont_w;
	int vi_sel_ln = 0;
	const char *name;
	int i, n;

	/* calculate size of menu rect */
	for (ent = entries, i = n = 0; ent->name; ent++, i++)
	{
		int wt;

		if (!ent->enabled)
			continue;

		if (i == sel) {
			ent_sel = ent;
			vi_sel_ln = n;
		}

		name = NULL;
		wt = strlen(ent->name) * me_mfont_w;
		if (wt == 0 && ent->generate_name)
			name = ent->generate_name(ent->id, &offs);
		if (name != NULL)
			wt = strlen(name) * me_mfont_w;

		if (ent->beh != MB_NONE)
		{
			if (wt > col2_offs)
				col2_offs = wt + me_mfont_w;
			wt = col2_offs;

			switch (ent->beh) {
			case MB_NONE:
				break;
			case MB_OPT_ONOFF:
			case MB_OPT_RANGE:
				wt += me_mfont_w * 3;
				break;
			case MB_OPT_CUSTOM:
			case MB_OPT_CUSTONOFF:
			case MB_OPT_CUSTRANGE:
				name = NULL;
				offs = 0;
				if (ent->generate_name != NULL)
					name = ent->generate_name(ent->id, &offs);
				if (name != NULL)
					wt += (strlen(name) + offs) * me_mfont_w;
				break;
			case MB_OPT_ENUM:
				wt += 10 * me_mfont_w;
				break;
			}
		}

		if (wt > w)
			w = wt;
		n++;
	}
	h = n * me_mfont_h;
	w += me_mfont_w * 2; /* selector */

	if (w > g_menuscreen_w) {
		lprintf("width %d > %d\n", w, g_menuscreen_w);
		w = g_menuscreen_w;
	}
	if (h > g_menuscreen_h) {
		lprintf("height %d > %d\n", w, g_menuscreen_h);
		h = g_menuscreen_h;
	}

	x = g_menuscreen_w / 2 - w / 2;
	y = g_menuscreen_h / 2 - h / 2;
#ifdef MENU_ALIGN_LEFT
	if (x > 12) x = 12;
#endif

	/* draw */
	menu_draw_begin(1, 0);
	menu_draw_selection(x, y + vi_sel_ln * me_mfont_h, w);
	x += me_mfont_w * 2;

	for (ent = entries; ent->name; ent++)
	{
		const char **names;
		int len, leftname_end = 0;

		if (!ent->enabled)
			continue;

		name = ent->name;
		if (strlen(name) == 0) {
			if (ent->generate_name)
				name = ent->generate_name(ent->id, &offs);
		}
		if (name != NULL) {
			text_out16(x, y, "%s", name);
			leftname_end = x + (strlen(name) + 1) * me_mfont_w;
		}

		switch (ent->beh) {
		case MB_NONE:
			break;
		case MB_OPT_ONOFF:
			text_out16(x + col2_offs, y, "%s", me_read_onoff(ent) ? "ON" : "OFF");
			break;
		case MB_OPT_RANGE:
			text_out16(x + col2_offs, y, "%i", *(int *)ent->var);
			break;
		case MB_OPT_CUSTOM:
		case MB_OPT_CUSTONOFF:
		case MB_OPT_CUSTRANGE:
			name = NULL;
			offs = 0;
			if (ent->generate_name)
				name = ent->generate_name(ent->id, &offs);
			if (name != NULL)
				text_out16(x + col2_offs + offs * me_mfont_w, y, "%s", name);
			break;
		case MB_OPT_ENUM:
			names = (const char **)ent->data;
			for (i = 0; names[i] != NULL; i++) {
				offs = x + col2_offs;
				len = strlen(names[i]);
				if (len > 10)
					offs += (10 - len) * me_mfont_w;
				if (offs < leftname_end)
					offs = leftname_end;
				if (i == *(int *)ent->var) {
					text_out16(offs, y, "%s", names[i]);
					break;
				}
			}
			break;
		}

		y += me_mfont_h;
	}

	menu_separation();

	/* display help or message if we have one */
	h = (g_menuscreen_h - h) / 2; // bottom area height
	if (menu_error_msg[0] != 0) {
		if (h >= me_mfont_h + 4)
			text_out16(5, g_menuscreen_h - me_mfont_h - 4, "%s", menu_error_msg);
		else
			lprintf("menu msg doesn't fit!\n");

		if (plat_get_ticks_ms() - menu_error_time > 2048)
			menu_error_msg[0] = 0;
	}
	else if (ent_sel->help != NULL) {
		const char *tmp = ent_sel->help;
		int l;
		for (l = 0; tmp != NULL && *tmp != 0; l++)
			tmp = strchr(tmp + 1, '\n');
		if (h >= l * me_sfont_h + 4)
			for (tmp = ent_sel->help; l > 0; l--, tmp = strchr(tmp, '\n') + 1)
				smalltext_out16(5, g_menuscreen_h - (l * me_sfont_h + 4), tmp, PXMAKE(0xff, 0xff, 0xff));
	}

	menu_separation();

	if (draw_more != NULL)
		draw_more();

	menu_draw_end();
}

static int me_process(menu_entry *entry, int is_next, int is_lr)
{
	const char **names;
	int c;
	switch (entry->beh)
	{
		case MB_OPT_ONOFF:
		case MB_OPT_CUSTONOFF:
			me_toggle_onoff(entry);
			return 1;
		case MB_OPT_RANGE:
		case MB_OPT_CUSTRANGE:
			c = is_lr ? 10 : 1;
			*(int *)entry->var += is_next ? c : -c;
			if (*(int *)entry->var < (int)entry->min)
				*(int *)entry->var = (int)entry->max;
			if (*(int *)entry->var > (int)entry->max)
				*(int *)entry->var = (int)entry->min;
			return 1;
		case MB_OPT_ENUM:
			names = (const char **)entry->data;
			for (c = 0; names[c] != NULL; c++)
				;
			*(int *)entry->var += is_next ? 1 : -1;
			if (*(int *)entry->var < 0)
				*(int *)entry->var = 0;
			if (*(int *)entry->var >= c)
				*(int *)entry->var = c - 1;
			return 1;
		default:
			return 0;
	}
}

static void debug_menu_loop(void);

static int me_loop_d(menu_entry *menu, int *menu_sel, void (*draw_prep)(void), void (*draw_more)(void))
{
	int ret = 0, inp, sel = *menu_sel, menu_sel_max;

	menu_sel_max = me_count(menu) - 1;
	if (menu_sel_max < 0) {
		lprintf("no enabled menu entries\n");
		return 0;
	}

	while ((!menu[sel].enabled || !menu[sel].selectable) && sel < menu_sel_max)
		sel++;

	/* make sure action buttons are not pressed on entering menu */
	me_draw(menu, sel, NULL);
	while (in_menu_wait_any(NULL, 50) & (PBTN_MOK|PBTN_MBACK|PBTN_MENU));

	for (;;)
	{
		if (draw_prep != NULL)
			draw_prep();

		me_draw(menu, sel, draw_more);
		inp = in_menu_wait(PBTN_UP|PBTN_DOWN|PBTN_LEFT|PBTN_RIGHT|
			PBTN_MOK|PBTN_MBACK|PBTN_MENU|PBTN_L|PBTN_R, NULL, 70);
		if (inp & (PBTN_MENU|PBTN_MBACK))
			break;

		if (inp & PBTN_UP  ) {
			do {
				sel--;
				if (sel < 0)
					sel = menu_sel_max;
			}
			while (!menu[sel].enabled || !menu[sel].selectable);
		}
		if (inp & PBTN_DOWN) {
			do {
				sel++;
				if (sel > menu_sel_max)
					sel = 0;
			}
			while (!menu[sel].enabled || !menu[sel].selectable);
		}

		/* a bit hacky but oh well */
		if ((inp & (PBTN_L|PBTN_R)) == (PBTN_L|PBTN_R))
			debug_menu_loop();

		if (inp & (PBTN_LEFT|PBTN_RIGHT|PBTN_L|PBTN_R)) { /* multi choice */
			if (me_process(&menu[sel], (inp & (PBTN_RIGHT|PBTN_R)) ? 1 : 0,
						inp & (PBTN_L|PBTN_R)))
				continue;
		}

		if (inp & (PBTN_MOK|PBTN_LEFT|PBTN_RIGHT|PBTN_L|PBTN_R))
		{
			/* require PBTN_MOK for MB_NONE */
			if (menu[sel].handler != NULL && (menu[sel].beh != MB_NONE || (inp & PBTN_MOK))) {
				ret = menu[sel].handler(menu[sel].id, inp);
				if (ret) break;
				menu_sel_max = me_count(menu) - 1; /* might change, so update */
			}
		}
	}
	*menu_sel = sel;

	return ret;
}

static int me_loop(menu_entry *menu, int *menu_sel)
{
	return me_loop_d(menu, menu_sel, NULL, NULL);
}

/* ***************************************** */

static void draw_menu_message(const char *msg, void (*draw_more)(void))
{
	int x, y, h, w, wt;
	const char *p;

	p = msg;
	for (h = 1, w = 0; *p != 0; h++) {
		for (wt = 0; *p != 0 && *p != '\n'; p++)
			wt++;

		if (wt > w)
			w = wt;
		if (*p == 0)
			break;
		p++;
	}

	x = g_menuscreen_w / 2 - w * me_mfont_w / 2;
	y = g_menuscreen_h / 2 - h * me_mfont_h / 2;
	if (x < 0) x = 0;
	if (y < 0) y = 0;

	menu_draw_begin(1, 0);

	for (p = msg; *p != 0 && y <= g_menuscreen_h - me_mfont_h; y += me_mfont_h) {
		text_out16(x, y, "%s", p);

		for (; *p != 0 && *p != '\n'; p++)
			;
		if (*p != 0)
			p++;
	}

	menu_separation();

	if (draw_more != NULL)
		draw_more();

	menu_draw_end();
}

// -------------- del confirm ---------------

static void do_delete(const char *fpath, const char *fname)
{
	int len, mid, inp;
	const char *nm;
	char tmp[64];

	menu_draw_begin(1, 0);

	len = strlen(fname);
	if (len > g_menuscreen_w / me_sfont_w)
		len = g_menuscreen_w / me_sfont_w;

	mid = g_menuscreen_w / 2;
	text_out16(mid - me_mfont_w * 15 / 2,  8 * me_mfont_h, "About to delete");
	smalltext_out16(mid - len * me_sfont_w / 2, 9 * me_mfont_h + 5, fname, PXMAKE(0xbf, 0xbf, 0xff));
	text_out16(mid - me_mfont_w * 13 / 2, 11 * me_mfont_h, "Are you sure?");

	nm = in_get_key_name(-1, -PBTN_MA3);
	snprintf(tmp, sizeof(tmp), "(%s - confirm, ", nm);
	len = strlen(tmp);
	nm = in_get_key_name(-1, -PBTN_MBACK);
	snprintf(tmp + len, sizeof(tmp) - len, "%s - cancel)", nm);
	len = strlen(tmp);

	text_out16(mid - me_mfont_w * len / 2, 12 * me_mfont_h, "%s", tmp);
	menu_draw_end();

	while (in_menu_wait_any(NULL, 50) & (PBTN_MENU|PBTN_MA2));
	inp = in_menu_wait(PBTN_MA3|PBTN_MBACK, NULL, 100);
	if (inp & PBTN_MA3)
		remove(fpath);
}

// -------------- ROM selector --------------

static const char **filter_exts_internal;
static const char *romsel_sort_dir;

enum romsel_sort_mode {
	ROMSEL_SORT_ALPHABETICAL = 0,
	ROMSEL_SORT_YEAR,
	ROMSEL_SORT_GENRE,
	ROMSEL_SORT_RATING,
	ROMSEL_SORT_COUNT
};

static int romsel_sort_mode;

static const char * const romsel_sort_labels[ROMSEL_SORT_COUNT] = {
	"Alphabetical", "Release Year", "Genre", "Rating"
};

#ifdef __PSP__
#define ROMSEL_ART_WIDTH 122
#define ROMSEL_ART_HEIGHT 84
static unsigned short romsel_artwork[ROMSEL_ART_WIDTH * ROMSEL_ART_HEIGHT];
static char romsel_artwork_path[GAME_METADATA_ART_MAX];
static int romsel_artwork_state;

static int romsel_load_artwork(const game_metadata *metadata)
{
	const char *path = metadata != NULL ? metadata->thumbnail : "";

	if (strcmp(path, romsel_artwork_path) == 0)
		return romsel_artwork_state;
	snprintf(romsel_artwork_path, sizeof(romsel_artwork_path), "%s", path);
	romsel_artwork_state = 0;
	if (*path == 0)
		return 0;
	if (readpng_rgb565_exact(romsel_artwork, ROMSEL_ART_WIDTH, path,
			ROMSEL_ART_WIDTH, ROMSEL_ART_HEIGHT) == 0)
		romsel_artwork_state = 1;
	else
		romsel_artwork_state = -1;
	return romsel_artwork_state;
}
#endif

static int romsel_has_extension(const char *name, const char **extensions)
{
	const char *ext = strrchr(name, '.');
	int i;

	if (ext == NULL || ext[1] == 0 || extensions == NULL)
		return 0;
	ext++;
	for (i = 0; extensions[i] != NULL; i++)
		if (strcasecmp(ext, extensions[i]) == 0)
			return 1;
	return 0;
}

static void romsel_display_name(char *dst, int dst_size, const char *name)
{
	char *ext;

	snprintf(dst, dst_size, "%s", name);
	ext = strrchr(dst, '.');
	if (ext != NULL && romsel_has_extension(name, filter_exts_internal))
		*ext = 0;
}

static void romsel_entry_title(char *dst, int dst_size, const char *curdir,
	const struct dirent *entry)
{
	const game_metadata *metadata = NULL;

	if (entry->d_type == DT_REG)
		metadata = game_metadata_find_file(curdir, entry->d_name);
	if (metadata != NULL && metadata->title[0] != 0)
		snprintf(dst, dst_size, "%s", metadata->title);
	else
		romsel_display_name(dst, dst_size, entry->d_name);
}
static void romsel_truncate(char *dst, int dst_size, const char *text,
	int max_chars)
{
	int length;

	if (dst_size <= 0)
		return;
	if (max_chars >= dst_size)
		max_chars = dst_size - 1;
	if (text == NULL)
		dst[0] = 0;
	else if (dst != text)
		snprintf(dst, dst_size, "%s", text);
	length = strlen(dst);
	if (length <= max_chars)
		return;
	dst[max_chars] = 0;
	if (max_chars >= 3)
		memcpy(dst + max_chars - 3, "...", 3);
}

#ifdef __PSP__
#define ROMSEL_TITLE_CHARS 24
#define ROMSEL_MARQUEE_DELAY 750
#define ROMSEL_MARQUEE_STEP 120
#define ROMSEL_MARQUEE_END_DELAY 750

static void romsel_marquee(char *dst, int dst_size, const char *title,
	unsigned int elapsed)
{
	char looped[GAME_METADATA_TITLE_MAX * 2 + 4];
	int length = strlen(title);
	int max_offset = length - ROMSEL_TITLE_CHARS;
	int offset = 0;
	unsigned int scroll_time;
	unsigned int cycle_time;

	if (length <= ROMSEL_TITLE_CHARS) {
		snprintf(dst, dst_size, "%s", title);
		return;
	}

	scroll_time = max_offset * ROMSEL_MARQUEE_STEP;
	cycle_time = ROMSEL_MARQUEE_DELAY + scroll_time +
		ROMSEL_MARQUEE_END_DELAY +
		(ROMSEL_TITLE_CHARS + 3) * ROMSEL_MARQUEE_STEP;
	elapsed %= cycle_time;
	if (elapsed >= ROMSEL_MARQUEE_DELAY) {
		elapsed -= ROMSEL_MARQUEE_DELAY;
		if (elapsed < scroll_time)
			offset = elapsed / ROMSEL_MARQUEE_STEP + 1;
		else {
			elapsed -= scroll_time;
			offset = max_offset;
			if (elapsed >= ROMSEL_MARQUEE_END_DELAY) {
				elapsed -= ROMSEL_MARQUEE_END_DELAY;
				offset += elapsed / ROMSEL_MARQUEE_STEP + 1;
			}
		}
	}

	snprintf(looped, sizeof(looped), "%s   %s", title, title);
	snprintf(dst, dst_size, "%.*s", ROMSEL_TITLE_CHARS, looped + offset);
}
#endif

#ifdef __PSP__
#define ROMSEL_INFO_LINES 9
#define ROMSEL_INFO_CHARS 64
#define ROMSEL_INFO_PAGES 16

static int romsel_metadata_has_error(void)
{
	switch (game_metadata_get_status()) {
	case GAME_METADATA_INVALID:
	case GAME_METADATA_UNSUPPORTED:
	case GAME_METADATA_IO_ERROR:
	case GAME_METADATA_OUT_OF_MEMORY:
		return 1;
	default:
		return 0;
	}
}

static int draw_rom_information(const char *curdir, const char *filename,
	int information_offset, int page)
{
	const game_metadata *metadata = game_metadata_find_file(curdir, filename);
	const char *information = "No information available.";
	const char *information_heading = "INFORMATION";
	const char *system_name;
	unsigned short heading_color = PXMAKE(0xb8, 0xc0, 0xc8);
	char title[64];
	char system[40];
	char genre[40];
	char line[ROMSEL_INFO_CHARS + 1];
	char value[32];
	int next_offset = information_offset;
	int i;

	if (metadata != NULL && metadata->title[0] != 0)
		romsel_truncate(title, sizeof(title), metadata->title, 46);
	else {
		romsel_display_name(title, sizeof(title), filename);
		romsel_truncate(title, sizeof(title), title, 46);
	}
	system_name = game_metadata_system_label(metadata, filename);
	romsel_truncate(system, sizeof(system), system_name, 28);
	romsel_truncate(genre, sizeof(genre),
		metadata != NULL && metadata->genre[0] != 0 ? metadata->genre : "--",
		28);
	if (metadata != NULL && metadata->information[0] != 0)
		information = metadata->information;
	else if (romsel_metadata_has_error()) {
		information = game_metadata_get_error();
		information_heading = "METADATA ERROR";
		heading_color = PXMAKE(0xff, 0x70, 0x70);
	}

	menu_draw_begin(1, 1);
	menu_draw_rect(28, 30, 424, 232, PXMAKE(0x07, 0x09, 0x0c));
	menu_draw_frame(28, 30, 424, 232, PXMAKE(0x58, 0x60, 0x68));
	smalltext_out16(44, 40, "GAME INFORMATION", PXMAKE(0xa8, 0xb0, 0xb8));
	text_out16(44, 55, "%s", title);
	menu_draw_rect(44, 72, 392, 1, PXMAKE(0x48, 0x50, 0x58));

	smalltext_out16(44, 82, "SYSTEM:", PXMAKE(0xff, 0xff, 0xff));
	smalltext_out16(96, 82, system, PXMAKE(0xc0, 0xc4, 0xc8));
	if (metadata != NULL && metadata->release_year > 0)
		snprintf(value, sizeof(value), "YEAR: %d", metadata->release_year);
	else
		snprintf(value, sizeof(value), "YEAR: ----");
	smalltext_out16(306, 82, value, PXMAKE(0xc0, 0xc4, 0xc8));
	smalltext_out16(44, 97, "GENRE:", PXMAKE(0xff, 0xff, 0xff));
	smalltext_out16(96, 97, genre, PXMAKE(0xc0, 0xc4, 0xc8));
	if (metadata != NULL && metadata->players > 0)
		snprintf(value, sizeof(value), "PLAYERS: %d", metadata->players);
	else
		snprintf(value, sizeof(value), "PLAYERS: --");
	smalltext_out16(306, 97, value, PXMAKE(0xc0, 0xc4, 0xc8));
	if (metadata != NULL && metadata->rating >= 0)
		snprintf(value, sizeof(value), "RATING: %d/100", metadata->rating);
	else
		snprintf(value, sizeof(value), "RATING: --");
	smalltext_out16(44, 112, value, PXMAKE(0xc0, 0xc4, 0xc8));

	smalltext_out16(44, 129, information_heading, heading_color);
	for (i = 0; i < ROMSEL_INFO_LINES && information[next_offset] != 0; i++) {
		next_offset = game_metadata_wrap_information_line(information,
			next_offset, line, sizeof(line), ROMSEL_INFO_CHARS);
		smalltext_out16(44, 143 + i * me_sfont_h, line,
			PXMAKE(0xe0, 0xe4, 0xe8));
	}
	if (information[next_offset] == 0)
		next_offset = -1;

	smalltext_out16(44, 246, "CROSS Back", PXMAKE(0xff, 0xff, 0xff));
	if (page > 0 || next_offset >= 0) {
		snprintf(value, sizeof(value), "L/R Page %d", page + 1);
		smalltext_out16(334, 246, value, PXMAKE(0xb8, 0xc0, 0xc8));
	}
	menu_draw_end();
	return next_offset;
}

static void romsel_information_loop(const char *curdir, const char *filename)
{
	int page_offsets[ROMSEL_INFO_PAGES] = { 0 };
	int next_offset;
	int page = 0;
	int input;

	while (in_menu_wait_any(NULL, 50) &
		(PBTN_MENU|PBTN_MBACK|PBTN_L|PBTN_R));
	for (;;) {
		next_offset = draw_rom_information(curdir, filename,
			page_offsets[page], page);
		input = in_menu_wait(PBTN_MBACK|PBTN_LEFT|PBTN_RIGHT|PBTN_L|PBTN_R,
			NULL, 33);
		if (input & PBTN_MBACK)
			break;
		if ((input & (PBTN_RIGHT|PBTN_R)) && next_offset >= 0 &&
			page + 1 < ROMSEL_INFO_PAGES) {
			page++;
			page_offsets[page] = next_offset;
		}
		else if ((input & (PBTN_LEFT|PBTN_L)) && page > 0)
			page--;
	}
	while (in_menu_wait_any(NULL, 50) & PBTN_MBACK);
}
#endif

static void draw_dirlist(char *curdir, struct dirent **namelist,
	int n, int sel, int show_help, unsigned int title_scroll_elapsed)
{
	int max_cnt, start, i, x, pos;
	void *darken_ptr;
	char buff[64];

#ifdef __PSP__
	const int visible = 7;
	const int list_x = 70;
	const int list_y = 119;
	const int line_h = 12;
	const char *heading = romsel_extra_mode ? "EXTRA GAMES" : "MAIN MENU";
	const game_metadata *selected_metadata = NULL;
	int artwork_state;
	char display[GAME_METADATA_TITLE_MAX];
	char full_title[GAME_METADATA_TITLE_MAX];
	char genre[GAME_METADATA_GENRE_MAX];
	char system[24];
	char year[24];
	const char *sort_label = romsel_sort_labels[romsel_sort_mode];

	(void)show_help;
	start = sel - visible / 2;
	if (start < 0)
		start = 0;
	if (start > n - visible)
		start = n - visible;
	if (start < 0)
		start = 0;

	menu_draw_begin(1, 1);

	text_out16(58 + (170 - strlen(heading) * me_mfont_w) / 2, 91,
		"%s", heading);
	menu_draw_rect(82, 103, 18, 12, PXMAKE(0x30, 0x32, 0x36));
	menu_draw_frame(82, 103, 18, 12, PXMAKE(0x98, 0x9c, 0xa0));
	smalltext_out16(88, 104, "L", PXMAKE(0xff, 0xff, 0xff));
	smalltext_out16(143 - strlen(sort_label) * me_sfont_w / 2, 104,
		sort_label, PXMAKE(0xff, 0xff, 0xff));
	menu_draw_rect(187, 103, 18, 12, PXMAKE(0x30, 0x32, 0x36));
	menu_draw_frame(187, 103, 18, 12, PXMAKE(0x98, 0x9c, 0xa0));
	smalltext_out16(193, 104, "R", PXMAKE(0xff, 0xff, 0xff));

	if (n == 0)
		smalltext_out16(list_x, list_y + visible / 2 * line_h,
			"No games found", PXMAKE(0xa8, 0xb0, 0xb8));
	for (i = start; i < n && i < start + visible; i++) {
		pos = list_y + (i - start) * line_h;
		romsel_entry_title(full_title, sizeof(full_title), curdir, namelist[i]);
		if (i == sel && namelist[i]->d_type == DT_REG)
			romsel_marquee(display, sizeof(display), full_title,
				title_scroll_elapsed);
		else
			romsel_truncate(display, sizeof(display), full_title,
				namelist[i]->d_type == DT_DIR ? 22 : ROMSEL_TITLE_CHARS);
		if (i == sel)
			menu_draw_rect(68, pos - 1, 148, 11, PXMAKE(0x70, 0x74, 0x72));
		if (namelist[i]->d_type == DT_DIR) {
			snprintf(buff, sizeof(buff), "[%s]", display);
			smalltext_out16(list_x, pos, buff, PXMAKE(0xc8, 0xd8, 0xff));
		}
		else
			smalltext_out16(list_x, pos, display,
				i == sel ? PXMAKE(0xff, 0xff, 0xff) : PXMAKE(0xa0, 0xa4, 0xa8));
	}

	if (n > 0 && namelist[sel]->d_type == DT_REG)
		selected_metadata = game_metadata_find_file(curdir,
			namelist[sel]->d_name);
	romsel_truncate(genre, sizeof(genre),
		selected_metadata != NULL && selected_metadata->genre[0] != 0 ?
		selected_metadata->genre : "--", 19);
	smalltext_out16(87, 208, "Genre: ", PXMAKE(0xff, 0xff, 0xff));
	smalltext_out16(123, 208, genre, PXMAKE(0xc0, 0xc4, 0xc8));
	if (romsel_metadata_has_error()) {
		smalltext_out16(70, 229, "METADATA ERROR", PXMAKE(0xff, 0x70, 0x70));
		if (game_metadata_get_error_line() > 0)
			snprintf(buff, sizeof(buff), "%s, line %d",
				game_metadata_status_name(game_metadata_get_status()),
				game_metadata_get_error_line());
		else
			snprintf(buff, sizeof(buff), "%s",
				game_metadata_status_name(game_metadata_get_status()));
		smalltext_out16(70, 244, buff, PXMAKE(0xd0, 0x80, 0x80));
	}

	/* Console-shaped preview card. */
	menu_draw_rect(244, 80, 166, 128, PXMAKE(0x06, 0x08, 0x0b));
	menu_draw_rect(239, 88, 176, 108, PXMAKE(0x06, 0x08, 0x0b));
	menu_draw_frame(244, 80, 166, 128, PXMAKE(0x50, 0x56, 0x5c));
	menu_draw_rect(261, 83, 132, 92, PXMAKE(0x02, 0x03, 0x05));
	menu_draw_frame(261, 83, 132, 92, PXMAKE(0xa0, 0xa6, 0xaa));
	menu_draw_rect(266, 87, 122, 84, PXMAKE(0x18, 0x32, 0x78));
	artwork_state = romsel_load_artwork(selected_metadata);
	if (artwork_state == 1)
		menu_draw_image(266, 87, ROMSEL_ART_WIDTH, ROMSEL_ART_HEIGHT,
			romsel_artwork, ROMSEL_ART_WIDTH);
	else if (n > 0) {
		const char *system_name = namelist[sel]->d_type == DT_DIR ?
			"GAME FOLDER" : game_metadata_system_label(selected_metadata,
				namelist[sel]->d_name);
		romsel_truncate(system, sizeof(system), system_name, 20);
		smalltext_out16(266 + (122 - strlen(system) * me_sfont_w) / 2, 123,
			system,
			PXMAKE(0xff, 0xff, 0xff));
	}
	if (selected_metadata != NULL && selected_metadata->release_year > 0)
		snprintf(year, sizeof(year), "RELEASE YEAR: %d",
			selected_metadata->release_year);
	else
		snprintf(year, sizeof(year), "RELEASE YEAR: ----");
	smalltext_out16(249, 178, year, PXMAKE(0xff, 0xff, 0xff));
	menu_draw_rect(247, 190, 160, 16, PXMAKE(0x12, 0x14, 0x17));
	menu_draw_frame(247, 190, 160, 16, PXMAKE(0x48, 0x4c, 0x50));

	menu_draw_rect(219, 214, 222, 58, PXMAKE(0x07, 0x09, 0x0c));
	menu_draw_frame(219, 214, 222, 58, PXMAKE(0x48, 0x50, 0x58));

	if (romsel_extra_mode) {
		smalltext_out16(237, 221, "TRIANGLE Credits",
			PXMAKE(0xff, 0xff, 0xff));
	}
	else {
		smalltext_out16(233, 221, "SQUARE Options  TRIANGLE Extras",
			PXMAKE(0xff, 0xff, 0xff));
	}
	smalltext_out16(233, 237, "CIRCLE Start   D-PAD Select",
		PXMAKE(0xff, 0xff, 0xff));
	smalltext_out16(233, 253, "CROSS Back  SELECT Info  L/R Sort",
		PXMAKE(0xb8, 0xc0, 0xc8));
	menu_draw_end();
	return;
#endif
	(void)title_scroll_elapsed;

	max_cnt = g_menuscreen_h / me_sfont_h;
	start = max_cnt / 2 - sel;

	menu_draw_begin(1, 1);

//	if (!rom_loaded)
//		menu_darken_bg(gp2x_screen, 320*240, 0);

	darken_ptr = (short *)g_menuscreen_ptr + g_menuscreen_pp * max_cnt/2 * me_sfont_h;
	menu_darken_bg(darken_ptr, darken_ptr, g_menuscreen_pp * me_sfont_h * 8 / 10, 0);

	x = 5 + me_mfont_w + 1;
	if (start - 2 >= 0)
		smalltext_out16(14, (start - 2) * me_sfont_h, curdir, PXMAKE(0xff, 0xff, 0xff));
	for (i = 0; i < n; i++) {
		pos = start + i;
		if (pos < 0)  continue;
		if (pos >= max_cnt) break;
		if (namelist[i]->d_type == DT_DIR) {
			smalltext_out16(x, pos * me_sfont_h, "/", PXMAKE(0xff, 0xff, 0xb0));
			smalltext_out16(x + me_sfont_w, pos * me_sfont_h, namelist[i]->d_name, PXMAKE(0xff, 0xff, 0xb0));
		} else {
			unsigned short color = fname2color(namelist[i]->d_name);
			smalltext_out16(x, pos * me_sfont_h, namelist[i]->d_name, color);
		}
	}
	smalltext_out16(5, max_cnt/2 * me_sfont_h, ">", PXMAKE(0xff, 0xff, 0xff));

	if (show_help) {
		darken_ptr = (short *)g_menuscreen_ptr
			+ g_menuscreen_pp * (g_menuscreen_h - me_sfont_h * 5 / 2);
		menu_darken_bg(darken_ptr, darken_ptr,
			g_menuscreen_pp * (me_sfont_h * 5 / 2), 1);

		snprintf(buff, sizeof(buff), "%s - select, %s - back",
			in_get_key_name(-1, -PBTN_MOK), in_get_key_name(-1, -PBTN_MBACK));
		smalltext_out16(x, g_menuscreen_h - me_sfont_h * 3 - 2, buff, PXMAKE(0xe0, 0xf0, 0x60));

		snprintf(buff, sizeof(buff), g_menu_filter_off ?
			 "%s - hide unknown files" : "%s - show all files",
			in_get_key_name(-1, -PBTN_MA3));
		smalltext_out16(x, g_menuscreen_h - me_sfont_h * 2 - 2, buff, PXMAKE(0xe0, 0xf0, 0x60));

		snprintf(buff, sizeof(buff), g_autostateld_opt ?
			 "%s - autoload save is ON" : "%s - autoload save is OFF",
			in_get_key_name(-1, -PBTN_MA2));
		smalltext_out16(x, g_menuscreen_h - me_sfont_h * 1 - 2, buff, PXMAKE(0xe0, 0xf0, 0x60));
	}

	menu_draw_end();
}

static int scandir_cmp(const void *p1, const void *p2)
{
	const struct dirent **d1 = (const struct dirent **)p1;
	const struct dirent **d2 = (const struct dirent **)p2;
	const game_metadata *metadata1 = NULL;
	const game_metadata *metadata2 = NULL;
	const char *name1 = (*d1)->d_name;
	const char *name2 = (*d2)->d_name;
	char title1[GAME_METADATA_TITLE_MAX];
	char title2[GAME_METADATA_TITLE_MAX];
	int has1, has2;
	int ret;
	if (strcmp(name1, "..") == 0)
		return strcmp(name2, "..") == 0 ? 0 : -1;
	if (strcmp(name2, "..") == 0)
		return 1;
	if ((*d1)->d_type == DT_DIR && (*d2)->d_type != DT_DIR)
		return -1;	// directories before files/links
	if ((*d2)->d_type == DT_DIR && (*d1)->d_type != DT_DIR)
		return  1;
	if ((*d1)->d_type != DT_DIR && romsel_sort_dir != NULL) {
		metadata1 = game_metadata_find_file(romsel_sort_dir, (*d1)->d_name);
		metadata2 = game_metadata_find_file(romsel_sort_dir, (*d2)->d_name);
		if (romsel_sort_mode == ROMSEL_SORT_YEAR) {
			has1 = metadata1 != NULL && metadata1->release_year > 0;
			has2 = metadata2 != NULL && metadata2->release_year > 0;
			if (has1 != has2)
				return has1 ? -1 : 1;
			if (has1 && metadata1->release_year != metadata2->release_year)
				return metadata1->release_year > metadata2->release_year ? -1 : 1;
		}
		else if (romsel_sort_mode == ROMSEL_SORT_GENRE) {
			has1 = metadata1 != NULL && metadata1->genre[0] != 0;
			has2 = metadata2 != NULL && metadata2->genre[0] != 0;
			if (has1 != has2)
				return has1 ? -1 : 1;
			if (has1) {
				ret = strcasecmp(metadata1->genre, metadata2->genre);
				if (ret == 0)
					ret = strcmp(metadata1->genre, metadata2->genre);
				if (ret != 0)
					return ret;
			}
		}
		else if (romsel_sort_mode == ROMSEL_SORT_RATING) {
			has1 = metadata1 != NULL && metadata1->rating >= 0;
			has2 = metadata2 != NULL && metadata2->rating >= 0;
			if (has1 != has2)
				return has1 ? -1 : 1;
			if (has1 && metadata1->rating != metadata2->rating)
				return metadata1->rating > metadata2->rating ? -1 : 1;
		}

		romsel_entry_title(title1, sizeof(title1), romsel_sort_dir, *d1);
		romsel_entry_title(title2, sizeof(title2), romsel_sort_dir, *d2);
		name1 = title1;
		name2 = title2;
	}

	ret = strcasecmp(name1, name2);
	if (ret == 0)
		ret = strcmp(name1, name2);
	if (ret == 0)
		ret = strcasecmp((*d1)->d_name, (*d2)->d_name);
	return ret != 0 ? ret : strcmp((*d1)->d_name, (*d2)->d_name);
}

static int scandir_filter(const struct dirent *ent)
{
	const char **filter = filter_exts_internal;

	if (ent == NULL)
		return 0;

	switch (ent->d_type) {
	case DT_DIR:
		return strcmp(ent->d_name, ".") != 0 && strcmp(ent->d_name, "..") != 0;
	case DT_LNK:
	case DT_UNKNOWN:
		// could be a dir, deal with it later..
		return 1;
	}

	return g_menu_filter_off || romsel_has_extension(ent->d_name, filter);
}

static int dirent_seek_char(const char *basedir, struct dirent **namelist,
	int len, int sel, char c)
{
	int i;

	for (i = sel + 1; ; i++) {
		const game_metadata *metadata;
		const char *name;

		if (i >= len)
			i = 0;
		if (i == sel)
			break;

		name = namelist[i]->d_name;
		metadata = namelist[i]->d_type == DT_REG ?
			game_metadata_find_file(basedir, namelist[i]->d_name) : NULL;
		if (metadata != NULL && metadata->title[0] != 0)
			name = metadata->title;
		if (tolower_simple(name[0]) == c)
			break;
	}

	return i;
}

static const char *menu_loop_romsel_d(char *curr_path, int len,
	const char **filter_exts,
	int (*extra_filter)(struct dirent **namelist, int count,
			    const char *basedir),
	void (*draw_prep)(void), int (*menu_action)(int action))
{
	static char rom_fname_reload[512]; // used for scratch and return
	char sel_fname[512];
	int (*filter)(const struct dirent *);
	struct dirent **namelist = NULL;
	int n = 0, inp = 0, sel = 0, show_help = 0;
	char *curr_path_restore = NULL;
	const char *ret = NULL;
	char cinp;
	int r, i, old_sel;
#ifdef __PSP__
	unsigned int marquee_start, now, repeat_at = 0;
	int raw_inp, held_inp = 0;
#endif

	filter_exts_internal = filter_exts;
	sel_fname[0] = 0;

	// is this a dir or a full path?
	if (!plat_is_dir(curr_path)) {
		char *p = strrchr(curr_path, '/');
		if (p != NULL) {
			*p = 0;
			curr_path_restore = p;
			snprintf(sel_fname, sizeof(sel_fname), "%s", p + 1);
		}
	}
	show_help = 2;

rescan:
	if (namelist != NULL) {
		while (n-- > 0)
			free(namelist[n]);
		free(namelist);
		namelist = NULL;
	}

	filter = scandir_filter;
	romsel_sort_dir = curr_path;

	n = scandir(curr_path, &namelist, filter, (void *)scandir_cmp);
	if (n < 0 || !namelist) {
		lprintf("menu_loop_romsel failed, dir: %s\n", curr_path);

		// try data root
		plat_get_data_dir(curr_path, len);
		n = scandir(curr_path, &namelist, filter, (void *)scandir_cmp);
		if (n < 0 || !namelist) {
			// oops, we failed
			lprintf("menu_loop_romsel failed, dir: %s\n", curr_path);
			n = 0;
			namelist = NULL;
		}
	}

	// try to resolve DT_UNKNOWN and symlinks
	for (i = 0; i < n; i++) {
		struct stat st;
		char *slash;

		if (namelist[i]->d_type == DT_REG || namelist[i]->d_type == DT_DIR)
			continue;

		r = strlen(curr_path);
		slash = (r && curr_path[r-1] == '/') ? "" : "/";
		snprintf(rom_fname_reload, sizeof(rom_fname_reload),
			"%s%s%s", curr_path, slash, namelist[i]->d_name);
		r = stat(rom_fname_reload, &st);
		if (r == 0)
		{
			if (S_ISREG(st.st_mode))
				namelist[i]->d_type = DT_REG;
			else if (S_ISDIR(st.st_mode))
				namelist[i]->d_type = DT_DIR;
		}
	}
	if (!g_menu_filter_off) {
		for (i = 0; i < n; ) {
			if (namelist[i]->d_type == DT_DIR ||
				romsel_has_extension(namelist[i]->d_name, filter_exts)) {
				i++;
				continue;
			}
			free(namelist[i]);
			memmove(&namelist[i], &namelist[i + 1],
				(n - i - 1) * sizeof(namelist[0]));
			n--;
		}
	}

	if (!g_menu_filter_off && extra_filter != NULL)
		n = extra_filter(namelist, n, curr_path);

	if (n > 1)
		qsort(namelist, n, sizeof(namelist[0]), scandir_cmp);

	// try to find selected file
	sel = 0;
	if (sel_fname[0] != 0) {
		for (i = 0; i < n; i++) {
			char *dname = namelist[i]->d_name;
			if (dname[0] == sel_fname[0] && strcmp(dname, sel_fname) == 0) {
				sel = i;
				break;
			}
		}
	}

#ifdef __PSP__
	marquee_start = plat_get_ticks_ms();
#endif

	/* make sure action buttons are not pressed on entering menu */
	if (draw_prep != NULL)
		draw_prep();
	draw_dirlist(curr_path, namelist, n, sel, show_help, 0);
	while (in_menu_wait_any(NULL, 50) &
		(PBTN_MOK|PBTN_MBACK|PBTN_MENU|PBTN_MA2|PBTN_MA3))
		;

	for (;;)
	{
		if (draw_prep != NULL)
			draw_prep();
		old_sel = sel;
#ifdef __PSP__
		now = plat_get_ticks_ms();
		draw_dirlist(curr_path, namelist, n, sel, show_help,
			now - marquee_start);
		raw_inp = in_menu_wait_any(&cinp, 50);
		inp = 0;
		now = plat_get_ticks_ms();
		if (raw_inp != held_inp) {
			inp = raw_inp & ~held_inp;
			held_inp = raw_inp;
			repeat_at = now + 450;
		}
		else if (raw_inp != 0 && (int)(now - repeat_at) >= 0) {
			inp = raw_inp & (PBTN_UP|PBTN_DOWN|PBTN_LEFT|PBTN_RIGHT);
			repeat_at = now + 33;
		}
#else
		draw_dirlist(curr_path, namelist, n, sel, show_help, 0);
		inp = in_menu_wait(PBTN_UP|PBTN_DOWN|PBTN_LEFT|PBTN_RIGHT
			| PBTN_L|PBTN_R|PBTN_MA2|PBTN_MA3|PBTN_MOK|PBTN_MBACK
			| PBTN_MENU|PBTN_CHAR, &cinp, 33);
#endif
#ifdef __PSP__
		if (inp == PBTN_MENU && n > 0 && namelist[sel]->d_type == DT_REG) {
			romsel_information_loop(curr_path, namelist[sel]->d_name);
			marquee_start = plat_get_ticks_ms();
			continue;
		}
#endif
		if ((inp & (PBTN_MA2|PBTN_MA3)) && menu_action != NULL) {
			if (menu_action(inp & (PBTN_MA2|PBTN_MA3)))
				break;
			if (draw_prep != NULL)
				draw_prep();
		}
		else if (inp & PBTN_MA3) {
			g_menu_filter_off = !g_menu_filter_off;
			if (n > 0)
				snprintf(sel_fname, sizeof(sel_fname), "%s",
					namelist[sel]->d_name);
			show_help = 2;
			goto rescan;
		}
#ifdef __PSP__
		if (inp & (PBTN_L|PBTN_R)) {
			if (n > 0)
				snprintf(sel_fname, sizeof(sel_fname), "%s",
					namelist[sel]->d_name);
			if (inp & PBTN_L)
				romsel_sort_mode = (romsel_sort_mode + ROMSEL_SORT_COUNT - 1) %
					ROMSEL_SORT_COUNT;
			else
				romsel_sort_mode = (romsel_sort_mode + 1) % ROMSEL_SORT_COUNT;
			if (n > 1)
				qsort(namelist, n, sizeof(namelist[0]), scandir_cmp);
			for (i = 0; i < n; i++) {
				if (strcmp(namelist[i]->d_name, sel_fname) == 0) {
					sel = i;
					break;
				}
			}
			marquee_start = now;
			continue;
		}
#endif
		int last = n ? n-1 : 0;
		if      (inp & PBTN_UP  )  { sel--;   if (sel < 0)   sel = last; }
		else if (inp & PBTN_DOWN)  { sel++;   if (sel > n-1) sel = 0; }
		else if (inp & PBTN_LEFT)  { sel-=10; if (sel < 0)   sel = 0; }
		else if (inp & PBTN_RIGHT) { sel+=10; if (sel > n-1) sel = last; }
#ifndef __PSP__
		else if (inp & PBTN_L)     { sel-=24; if (sel < 0)   sel = 0; }
		else if (inp & PBTN_R)     { sel+=24; if (sel > n-1) sel = last; }
#endif

		else if (n > 0 && ((inp & PBTN_MOK) || (inp & (PBTN_MENU|PBTN_MA2)) == (PBTN_MENU|PBTN_MA2)))
		{
			if (namelist[sel]->d_type == DT_REG)
			{
				int l = strlen(curr_path);
				char *slash = l && curr_path[l-1] == '/' ? "" : "/";
				snprintf(rom_fname_reload, sizeof(rom_fname_reload),
					"%s%s%s", curr_path, slash, namelist[sel]->d_name);
				if (inp & PBTN_MOK) { // return sel
					ret = rom_fname_reload;
					break;
				}
				do_delete(rom_fname_reload, namelist[sel]->d_name);
				goto rescan;
			}
			else if (namelist[sel]->d_type == DT_DIR)
			{
				int newlen;
				char *p, *newdir;
				if (!(inp & PBTN_MOK))
					continue;
				newlen = strlen(curr_path) + strlen(namelist[sel]->d_name) + 2;
				newdir = malloc(newlen);
				if (newdir == NULL)
					break;
				if (strcmp(namelist[sel]->d_name, "..") == 0) {
					char *start = curr_path;
					p = start + strlen(start) - 1;
					while (*p == '/' && p > start) p--;
					while (*p != '/' && p > start) p--;
					if (p <= start) plat_get_data_dir(newdir, newlen);
					else { strncpy(newdir, start, p-start); newdir[p-start] = 0; }
				} else {
					strcpy(newdir, curr_path);
					p = newdir + strlen(newdir) - 1;
					while (*p == '/' && p >= newdir) *p-- = 0;
					strcat(newdir, "/");
					strcat(newdir, namelist[sel]->d_name);
				}
				ret = menu_loop_romsel_d(newdir, newlen, filter_exts, extra_filter,
					draw_prep, menu_action);
				free(newdir);
				if (ret != NULL)
					break;
			}
		}
		else if (inp & PBTN_MA2) {
			g_autostateld_opt = !g_autostateld_opt;
			show_help = 3;
		}
		else if (inp & PBTN_CHAR) {
			// must be last
			sel = dirent_seek_char(curr_path, namelist, n, sel, cinp);
		}

#ifdef __PSP__
		if (sel != old_sel)
			marquee_start = now;
#endif

		if (inp & PBTN_MBACK)
			break;

		if (show_help > 0)
			show_help--;
	}

	if (n > 0) {
		while (n-- > 0)
			free(namelist[n]);
		free(namelist);
	}

	// restore curr_path
	if (curr_path_restore != NULL)
		*curr_path_restore = '/';

	return ret;
}

static const char *menu_loop_romsel(char *curr_path, int len,
	const char **filter_exts,
	int (*extra_filter)(struct dirent **namelist, int count,
			    const char *basedir))
{
	return menu_loop_romsel_d(curr_path, len, filter_exts, extra_filter, NULL, NULL);
}

// ------------ savestate loader ------------

#define STATE_SLOT_COUNT 10

static int state_slot_flags = 0;
static int state_slot_times[STATE_SLOT_COUNT];

static void state_check_slots(void)
{
	int slot;

	state_slot_flags = 0;

	for (slot = 0; slot < STATE_SLOT_COUNT; slot++) {
		state_slot_times[slot] = 0;
		if (emu_check_save_file(slot, &state_slot_times[slot]))
			state_slot_flags |= 1 << slot;
	}
}

static void draw_savestate_bg(int slot);

static void draw_savestate_menu(int menu_sel, int is_loading)
{
	int i, x, y, w, h;
	char time_buf[32];

	if (state_slot_flags & (1 << menu_sel))
		draw_savestate_bg(menu_sel);

	w = (13 + 2) * me_mfont_w;
	h = (1+2+STATE_SLOT_COUNT+1) * me_mfont_h;
	x = g_menuscreen_w / 2 - w / 2;
	if (x < 0) x = 0;
	y = g_menuscreen_h / 2 - h / 2;
	if (y < 0) y = 0;
#ifdef MENU_ALIGN_LEFT
	if (x > 12 + me_mfont_w * 2)
		x = 12 + me_mfont_w * 2;
#endif

	menu_draw_begin(1, 1);

	text_out16(x, y, is_loading ? "Load state" : "Save state");
	y += 3 * me_mfont_h;

	menu_draw_selection(x - me_mfont_w * 2, y + menu_sel * me_mfont_h, (23 + 2) * me_mfont_w + 4);

	/* draw all slots */
	for (i = 0; i < STATE_SLOT_COUNT; i++, y += me_mfont_h)
	{
		if (!(state_slot_flags & (1 << i)))
			strcpy(time_buf, "free");
		else {
			strcpy(time_buf, "USED");
			if (state_slot_times[i] != 0) {
				time_t time = state_slot_times[i];
				struct tm *t = localtime(&time);
				strftime(time_buf, sizeof(time_buf), "%x %R", t);
			}
		}

		text_out16(x, y, "SLOT %i (%s)", i, time_buf);
	}
	text_out16(x, y, "back");

	menu_draw_end();
}

static int menu_loop_savestate(int is_loading)
{
	static int menu_sel = STATE_SLOT_COUNT;
	int menu_sel_max = STATE_SLOT_COUNT;
	unsigned long inp = 0;
	int ret = 0;

	state_check_slots();

	if (!(state_slot_flags & (1 << menu_sel)) && is_loading)
		menu_sel = menu_sel_max;

	for (;;)
	{
		draw_savestate_menu(menu_sel, is_loading);
		inp = in_menu_wait(PBTN_UP|PBTN_DOWN|PBTN_MOK|PBTN_MBACK, NULL, 100);
		if (inp & PBTN_UP) {
			do {
				menu_sel--;
				if (menu_sel < 0)
					menu_sel = menu_sel_max;
			} while (!(state_slot_flags & (1 << menu_sel)) && menu_sel != menu_sel_max && is_loading);
		}
		if (inp & PBTN_DOWN) {
			do {
				menu_sel++;
				if (menu_sel > menu_sel_max)
					menu_sel = 0;
			} while (!(state_slot_flags & (1 << menu_sel)) && menu_sel != menu_sel_max && is_loading);
		}
		if (inp & PBTN_MOK) { // save/load
			if (menu_sel < STATE_SLOT_COUNT) {
				state_slot = menu_sel;
				if (emu_save_load_game(is_loading, 0)) {
					menu_update_msg(is_loading ? "Load failed" : "Save failed");
					break;
				}
				ret = 1;
				break;
			}
			break;
		}
		if (inp & PBTN_MBACK)
			break;
	}

	return ret;
}

// -------------- key config --------------

static char *action_binds(int player_idx, int action_mask, int dev_id)
{
	int dev = 0, dev_last = IN_MAX_DEVS - 1;
	int can_combo = 1, type;

	static_buff[0] = 0;

	type = IN_BINDTYPE_EMU;
	if (player_idx >= 0) {
		can_combo = 0;
		type = IN_BINDTYPE_PLAYER12 + (player_idx >> 1);
		if (player_idx & 1)
			action_mask <<= 16;
	}

	if (dev_id >= 0)
		dev = dev_last = dev_id;

	for (; dev <= dev_last; dev++) {
		int k, count = 0, combo = 0;
		const int *binds;

		binds = in_get_dev_binds(dev);
		if (binds == NULL)
			continue;

		in_get_config(dev, IN_CFG_BIND_COUNT, &count);
		in_get_config(dev, IN_CFG_DOES_COMBOS, &combo);
		combo = combo && can_combo;

		for (k = 0; k < count; k++) {
			const char *xname;
			int len;

			if (!(binds[IN_BIND_OFFS(k, type)] & action_mask))
				continue;

			xname = in_get_key_name(dev, k);
			len = strlen(static_buff);
			if (len) {
				strncat(static_buff, combo ? " + " : ", ",
					sizeof(static_buff) - len - 1);
				len += combo ? 3 : 2;
			}
			strncat(static_buff, xname, sizeof(static_buff) - len - 1);
		}
	}

	return static_buff;
}

static int count_bound_keys(int dev_id, int action_mask, int bindtype)
{
	const int *binds;
	int k, keys = 0;
	int count = 0;

	binds = in_get_dev_binds(dev_id);
	if (binds == NULL)
		return 0;

	in_get_config(dev_id, IN_CFG_BIND_COUNT, &count);
	for (k = 0; k < count; k++)
	{
		if (binds[IN_BIND_OFFS(k, bindtype)] & action_mask)
			keys++;
	}

	return keys;
}

static void draw_key_config(const me_bind_action *opts, int opt_cnt, int player_idx,
		int sel, int dev_id, int dev_count, int is_bind)
{
	char buff[64], buff2[32];
	const char *dev_name;
	int x, y, w, i;

	w = ((player_idx >= 0) ? 20 : 30) * me_mfont_w;
	x = g_menuscreen_w / 2 - w / 2;
	y = (g_menuscreen_h - 4 * me_mfont_h) / 2 - (2 + opt_cnt) * me_mfont_h / 2;
	if (x < me_mfont_w * 2)
		x = me_mfont_w * 2;
	if (y < 0)
		y = 0;
	menu_draw_begin(1, 0);
	if (player_idx >= 0)
		text_out16(x, y, "Player %i controls", player_idx + 1);
	else
		text_out16(x, y, "Emulator controls");

	y += 2 * me_mfont_h;
	menu_draw_selection(x - me_mfont_w * 2, y + sel * me_mfont_h, w + 2 * me_mfont_w);

	for (i = 0; i < opt_cnt; i++, y += me_mfont_h)
		text_out16(x, y, "%s : %s", opts[i].name,
			action_binds(player_idx, opts[i].mask, dev_id));

	menu_separation();

	if (dev_id < 0)
		dev_name = "(all devices)";
	else
		dev_name = in_get_dev_name(dev_id, 0, 1);
	w = strlen(dev_name) * me_mfont_w;
	if (w < 30 * me_mfont_w)
		w = 30 * me_mfont_w;
	if (w > g_menuscreen_w)
		w = g_menuscreen_w;

	x = g_menuscreen_w / 2 - w / 2;

	if (!is_bind) {
		snprintf(buff2, sizeof(buff2), "%s", in_get_key_name(-1, -PBTN_MOK));
		snprintf(buff, sizeof(buff), "%s - bind, %s - clear", buff2,
				in_get_key_name(-1, -PBTN_MA2));
		text_out16(x, g_menuscreen_h - 4 * me_mfont_h, "%s", buff);
	}
	else
		text_out16(x, g_menuscreen_h - 4 * me_mfont_h, "Press a button to bind/unbind");

	if (dev_count > 1) {
		text_out16(x, g_menuscreen_h - 3 * me_mfont_h, "%s", dev_name);
		text_out16(x, g_menuscreen_h - 2 * me_mfont_h, "Press left/right for other devs");
	}

	menu_draw_end();
}

static void key_config_loop(const me_bind_action *opts, int opt_cnt, int player_idx)
{
	int i, sel = 0, menu_sel_max = opt_cnt - 1, does_combos = 0;
	int dev_id, bind_dev_id, dev_count, kc, is_down, mkey;
	int unbind, bindtype, mask_shift;

	for (i = 0, dev_id = -1, dev_count = 0; i < IN_MAX_DEVS; i++) {
		if (in_get_dev_name(i, 1, 0) != NULL) {
			dev_count++;
			if (dev_id < 0)
				dev_id = i;
		}
	}

	if (dev_id == -1) {
		lprintf("no devs, can't do config\n");
		return;
	}

	dev_id = -1; // show all
	mask_shift = 0;
	if (player_idx >= 0) {
		if (player_idx & 1)
			mask_shift = 16;
		bindtype = IN_BINDTYPE_PLAYER12 + (player_idx >> 1);
	} else
		bindtype = IN_BINDTYPE_EMU;

	for (;;)
	{
		draw_key_config(opts, opt_cnt, player_idx, sel, dev_id, dev_count, 0);
		mkey = in_menu_wait(PBTN_UP|PBTN_DOWN|PBTN_LEFT|PBTN_RIGHT
				|PBTN_MBACK|PBTN_MOK|PBTN_MA2, NULL, 100);
		switch (mkey) {
			case PBTN_UP:   sel--; if (sel < 0) sel = menu_sel_max; continue;
			case PBTN_DOWN: sel++; if (sel > menu_sel_max) sel = 0; continue;
			case PBTN_LEFT:
				for (i = 0, dev_id--; i < IN_MAX_DEVS + 1; i++, dev_id--) {
					if (dev_id < -1)
						dev_id = IN_MAX_DEVS - 1;
					if (dev_id == -1 || in_get_dev_name(dev_id, 0, 0) != NULL)
						break;
				}
				continue;
			case PBTN_RIGHT:
				for (i = 0, dev_id++; i < IN_MAX_DEVS; i++, dev_id++) {
					if (dev_id >= IN_MAX_DEVS)
						dev_id = -1;
					if (dev_id == -1 || in_get_dev_name(dev_id, 0, 0) != NULL)
						break;
				}
				continue;
			case PBTN_MBACK:
				return;
			case PBTN_MOK:
				if (sel >= opt_cnt)
					return;
				while (in_menu_wait_any(NULL, 30) & PBTN_MOK)
					;
				break;
			case PBTN_MA2:
				in_unbind_all(dev_id, opts[sel].mask << mask_shift, bindtype);
				continue;
			default:continue;
		}

		draw_key_config(opts, opt_cnt, player_idx, sel, dev_id, dev_count, 1);

		/* wait for some up event */
		for (is_down = 1; is_down; )
			kc = in_update_keycode(&bind_dev_id, &is_down, NULL, -1);

		i = count_bound_keys(bind_dev_id, opts[sel].mask << mask_shift, bindtype);
		unbind = (i > 0);

		/* allow combos if device supports them */
		in_get_config(bind_dev_id, IN_CFG_DOES_COMBOS, &does_combos);
		if (i == 1 && bindtype == IN_BINDTYPE_EMU && does_combos)
			unbind = 0;

		if (unbind)
			in_unbind_all(bind_dev_id, opts[sel].mask << mask_shift, bindtype);

		in_bind_key(bind_dev_id, kc, opts[sel].mask << mask_shift, bindtype, 0);

		// make sure bind change is displayed
		if (dev_id != -1)
			dev_id = bind_dev_id;
	}
}

