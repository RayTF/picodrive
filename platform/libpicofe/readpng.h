#ifndef LIBPICOFE_READPNG_H
#define LIBPICOFE_READPNG_H

typedef enum
{
	READPNG_BG = 1,
	READPNG_FONT,
	READPNG_SELECTOR,
	READPNG_24,
	READPNG_SCALE,
}
readpng_what;

#ifdef __cplusplus
extern "C" {
#endif

int readpng(void *dest, const char *fname, readpng_what what, int w, int h);
int readpng_rgb565_exact(unsigned short *dest, int dest_pitch,
	const char *fname, int width, int height);
int writepng(const char *fname, unsigned short *src, int w, int h);

#ifdef __cplusplus
}
#endif

#endif // LIBPICOFE_READPNG_H
