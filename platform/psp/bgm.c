/*
 * VectorDrive Menu BGM Player for PSP
 *
 * Robust background music player using PSPSDK hardware MP3 decoding (sceMp3)
 */

#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <pspkernel.h>
#include <pspsdk.h>
#include <pspaudio.h>
#include <pspmp3.h>
#include <psputility.h>

#include "../common/bgm.h"
#include "../libpicofe/lprintf.h"

enum {
	BGM_CMD_IDLE = 0,
	BGM_CMD_PLAY,
	BGM_CMD_STOP,
	BGM_CMD_PAUSE,
	BGM_CMD_RESUME,
	BGM_CMD_EXIT
};

static int bgm_initialized = 0;
static volatile int bgm_cmd = BGM_CMD_IDLE;
static volatile int bgm_active = 0;

static SceUID bgm_thid = -1;
static SceUID bgm_sem = -1;
static SceUID bgm_fd = -1;
static int bgm_handle = -1;
static int bgm_channel = -1;
static int bgm_is_src_channel = 0;

static char bgm_file_path[256] = { 0 };
static int bgm_volume = PSP_AUDIO_VOLUME_MAX;

// Buffers must be 64-byte aligned for ME/hardware MP3 decoder
static unsigned char mp3Buf[16 * 1024] __attribute__((aligned(64)));
static unsigned char pcmBuf[16 * (1152 / 2)] __attribute__((aligned(64)));

static SceUID load_module(const char *prxname)
{
	SceUID mod = pspSdkLoadStartModule(prxname, PSP_MEMORY_PARTITION_KERNEL);
	if (mod < 0) {
		lprintf("bgm: pspSdkLoadStartModule(%s) failed: 0x%08X\n", prxname, mod);
	}
	return mod;
}

static void init_av_modules(void)
{
	int ret;

	lprintf("bgm: devkit version = 0x%08X\n", (unsigned int)sceKernelDevkitVersion());

	// Load AVCODEC
	ret = sceUtilityLoadAvModule(PSP_AV_MODULE_AVCODEC);
	lprintf("bgm: sceUtilityLoadAvModule(AVCODEC) = 0x%08X\n", ret);
	ret = sceUtilityLoadModule(PSP_MODULE_AV_AVCODEC);
	lprintf("bgm: sceUtilityLoadModule(AVCODEC 0x%04X) = 0x%08X\n", PSP_MODULE_AV_AVCODEC, ret);
	if (ret < 0) {
		lprintf("bgm: trying flash0 for avcodec...\n");
		load_module("flash0:/kd/me_for_vsh.prx");
		if (sceKernelDevkitVersion() < 0x02070010)
			load_module("flash0:/kd/audiocodec.prx");
		else
			load_module("flash0:/kd/avcodec.prx");
	}

	// Load MP3
	ret = sceUtilityLoadAvModule(PSP_AV_MODULE_MP3);
	lprintf("bgm: sceUtilityLoadAvModule(MP3) = 0x%08X\n", ret);
	ret = sceUtilityLoadModule(PSP_MODULE_AV_MP3);
	lprintf("bgm: sceUtilityLoadModule(MP3 0x%04X) = 0x%08X\n", PSP_MODULE_AV_MP3, ret);
}

static int fill_stream_buffer(int fd, int handle)
{
	unsigned char *dst = NULL;
	SceInt32 write = 0;
	SceInt32 pos = 0;
	int status, bytes_read;

	status = sceMp3GetInfoToAddStreamData(handle, &dst, &write, &pos);
	if (status < 0) {
		lprintf("bgm: sceMp3GetInfoToAddStreamData failed: 0x%08X\n", status);
		return 0;
	}

	if (write <= 0)
		return 1;

	status = sceIoLseek32(fd, pos, PSP_SEEK_SET);
	if (status < 0) {
		lprintf("bgm: sceIoLseek32(pos=%d) failed: 0x%08X\n", (int)pos, status);
		return 0;
	}

	bytes_read = sceIoRead(fd, dst, write);
	if (bytes_read <= 0) {
		return 0; // EOF or read failure
	}

	status = sceMp3NotifyAddStreamData(handle, bytes_read);
	if (status < 0) {
		lprintf("bgm: sceMp3NotifyAddStreamData(read=%d) failed: 0x%08X\n", bytes_read, status);
		return 0;
	}

	return (pos > 0);
}

static void release_audio_channel(void)
{
	if (bgm_channel >= 0) {
		if (bgm_is_src_channel) {
			sceAudioSRCChRelease();
		} else {
			sceAudioChRelease(bgm_channel);
		}
		bgm_channel = -1;
		bgm_is_src_channel = 0;
	}
}

static void close_mp3(void)
{
	release_audio_channel();

	if (bgm_handle >= 0) {
		sceMp3ReleaseMp3Handle(bgm_handle);
		bgm_handle = -1;
	}
	if (bgm_fd >= 0) {
		sceIoClose(bgm_fd);
		bgm_fd = -1;
	}
}

static char bgm_app_dir[256] = { 0 };

static int open_mp3(const char *filename)
{
	SceMp3InitArg mp3Init;
	char abs_path[512];
	int status;

	close_mp3();

	abs_path[0] = 0;
	if (filename[0] == '/' || strchr(filename, ':')) {
		strncpy(abs_path, filename, sizeof(abs_path) - 1);
		abs_path[sizeof(abs_path) - 1] = 0;
	} else {
		if (bgm_app_dir[0] != 0) {
			int len = strlen(bgm_app_dir);
			if (len > 0 && bgm_app_dir[len - 1] == '/') {
				snprintf(abs_path, sizeof(abs_path), "%s%s", bgm_app_dir, filename);
			} else {
				snprintf(abs_path, sizeof(abs_path), "%s/%s", bgm_app_dir, filename);
			}
		} else {
			char cwd[256];
			if (getcwd(cwd, sizeof(cwd))) {
				snprintf(abs_path, sizeof(abs_path), "%s/%s", cwd, filename);
			} else {
				strncpy(abs_path, filename, sizeof(abs_path) - 1);
			}
		}
	}

	lprintf("bgm: opening '%s' (resolved '%s')...\n", filename, abs_path);
	bgm_fd = sceIoOpen(abs_path, PSP_O_RDONLY, 0777);
	if (bgm_fd < 0) {
		lprintf("bgm: sceIoOpen failed for '%s': 0x%08X, trying relative '%s'...\n",
			abs_path, bgm_fd, filename);
		bgm_fd = sceIoOpen(filename, PSP_O_RDONLY, 0777);
	}
	if (bgm_fd < 0) {
		lprintf("bgm: sceIoOpen failed for all paths: 0x%08X\n", bgm_fd);
		return -1;
	}
	lprintf("bgm: file opened successfully, fd=0x%08X\n", bgm_fd);

	memset(&mp3Init, 0, sizeof(mp3Init));
	mp3Init.mp3StreamStart = 0;
	mp3Init.mp3StreamEnd = sceIoLseek32(bgm_fd, 0, PSP_SEEK_END);
	mp3Init.mp3Buf = mp3Buf;
	mp3Init.mp3BufSize = sizeof(mp3Buf);
	mp3Init.pcmBuf = pcmBuf;
	mp3Init.pcmBufSize = sizeof(pcmBuf);

	lprintf("bgm: stream size %d bytes, mp3Buf=%p (size=%d), pcmBuf=%p (size=%d)\n",
		(int)mp3Init.mp3StreamEnd, mp3Buf, (int)sizeof(mp3Buf), pcmBuf, (int)sizeof(pcmBuf));

	status = sceMp3InitResource();
	lprintf("bgm: sceMp3InitResource returned 0x%08X\n", status);

	bgm_handle = sceMp3ReserveMp3Handle(&mp3Init);
	lprintf("bgm: sceMp3ReserveMp3Handle returned 0x%08X\n", bgm_handle);
	if (bgm_handle < 0) {
		sceIoClose(bgm_fd);
		bgm_fd = -1;
		return -1;
	}

	int fill_res = fill_stream_buffer(bgm_fd, bgm_handle);
	lprintf("bgm: initial fill_stream_buffer returned %d\n", fill_res);

	status = sceMp3Init(bgm_handle);
	lprintf("bgm: sceMp3Init returned 0x%08X\n", status);
	if (status < 0) {
		close_mp3();
		return -1;
	}

	// Seamless loop forever
	status = sceMp3SetLoopNum(bgm_handle, -1);
	lprintf("bgm: sceMp3SetLoopNum returned 0x%08X\n", status);
	lprintf("bgm: mp3 initialized successfully (rate=%d, channels=%d, bitrate=%d)\n",
		(int)sceMp3GetSamplingRate(bgm_handle), (int)sceMp3GetMp3ChannelNum(bgm_handle), (int)sceMp3GetBitRate(bgm_handle));

	return 0;
}

static int bgm_worker_thread(SceSize args, void *argp)
{
	int samplingRate = 44100;
	int numChannels = 2;
	int lastDecoded = 0;
	int frame_count = 0;

	lprintf("bgm: worker thread started with id 0x%08X, priority %i\n",
		sceKernelGetThreadId(), sceKernelGetThreadCurrentPriority());

	while (bgm_cmd != BGM_CMD_EXIT)
	{
		if (bgm_cmd == BGM_CMD_STOP || bgm_cmd == BGM_CMD_PAUSE || bgm_cmd == BGM_CMD_IDLE)
		{
			if (bgm_active) {
				lprintf("bgm: pausing/stopping playback (cmd=%d)\n", bgm_cmd);
			}
			release_audio_channel();
			bgm_active = 0;
			frame_count = 0;
			sceKernelWaitSema(bgm_sem, 1, NULL);
			continue;
		}

		if (bgm_cmd == BGM_CMD_PLAY || bgm_cmd == BGM_CMD_RESUME)
		{
			short *buf = NULL;
			int bytesDecoded = 0;
			int retries = 0;

			if (bgm_handle < 0 || bgm_fd < 0) {
				if (bgm_file_path[0] != '\0') {
					lprintf("bgm: opening track file '%s'...\n", bgm_file_path);
					if (open_mp3(bgm_file_path) < 0) {
						lprintf("bgm: open_mp3 failed for '%s'\n", bgm_file_path);
						bgm_cmd = BGM_CMD_STOP;
						bgm_active = 0;
						continue;
					}
				} else {
					lprintf("bgm: no file path specified\n");
					bgm_cmd = BGM_CMD_STOP;
					bgm_active = 0;
					continue;
				}
			}

			if (!bgm_active) {
				lprintf("bgm: playback starting active loop\n");
			}
			bgm_active = 1;
			samplingRate = sceMp3GetSamplingRate(bgm_handle);
			numChannels = sceMp3GetMp3ChannelNum(bgm_handle);
			if (samplingRate <= 0) samplingRate = 44100;
			if (numChannels <= 0)  numChannels = 2;

			// Stream data if needed
			if (sceMp3CheckStreamDataNeeded(bgm_handle) > 0)
			{
				int fill_ret = fill_stream_buffer(bgm_fd, bgm_handle);
				if (frame_count < 5) {
					lprintf("bgm: fill_stream_buffer returned %d\n", fill_ret);
				}
			}

			// Decode frame
			for (retries = 0; retries < 2; retries++)
			{
				bytesDecoded = sceMp3Decode(bgm_handle, &buf);
				if (bytesDecoded > 0)
					break;

				if (sceMp3CheckStreamDataNeeded(bgm_handle) > 0)
				{
					if (!fill_stream_buffer(bgm_fd, bgm_handle)) {
						lprintf("bgm: decode retry: fill_stream_buffer reached EOF, resetting pos\n");
						sceMp3ResetPlayPosition(bgm_handle);
					}
				}
			}

			if (frame_count < 5) {
				lprintf("bgm: frame %d: bytesDecoded=%d, buf=%p\n", frame_count, bytesDecoded, buf);
			}

			if (bytesDecoded <= 0 || bytesDecoded == 0x80671402)
			{
				lprintf("bgm: end of stream (code 0x%08X), looping...\n", bytesDecoded);
				sceMp3ResetPlayPosition(bgm_handle);
				fill_stream_buffer(bgm_fd, bgm_handle);
				continue;
			}

			if (bgm_cmd != BGM_CMD_PLAY && bgm_cmd != BGM_CMD_RESUME) {
				continue;
			}

			// Reserve audio channel if not already reserved
			if (bgm_channel < 0 || lastDecoded != bytesDecoded)
			{
				release_audio_channel();
				int sample_count = bytesDecoded / (2 * numChannels);

				// Try standard hardware audio channel first
				bgm_channel = sceAudioChReserve(PSP_AUDIO_NEXT_CHANNEL, sample_count, PSP_AUDIO_FORMAT_STEREO);
				lprintf("bgm: sceAudioChReserve(count=%d) returned channel %d\n", sample_count, bgm_channel);
				if (bgm_channel >= 0) {
					bgm_is_src_channel = 0;
				} else {
					// Fallback to SRC channel
					int ret = sceAudioSRCChReserve(sample_count, samplingRate, numChannels);
					lprintf("bgm: sceAudioSRCChReserve(count=%d, rate=%d, ch=%d) returned %d\n",
						sample_count, samplingRate, numChannels, ret);
					if (ret >= 0) {
						bgm_channel = 0;
						bgm_is_src_channel = 1;
					}
				}
				lastDecoded = bytesDecoded;
			}

			// Output audio samples
			if (bgm_channel >= 0 && buf != NULL)
			{
				int out_ret;
				if (bgm_is_src_channel) {
					out_ret = sceAudioSRCOutputBlocking(bgm_volume, buf);
				} else {
					out_ret = sceAudioOutputPannedBlocking(bgm_channel, bgm_volume, bgm_volume, buf);
				}
				if (frame_count < 5) {
					lprintf("bgm: frame %d: audio output returned %d\n", frame_count, out_ret);
				}
				frame_count++;
			} else if (frame_count < 5) {
				lprintf("bgm: frame %d: cannot output audio! channel=%d, buf=%p\n",
					frame_count, bgm_channel, buf);
			}
		}
	}

	close_mp3();
	bgm_active = 0;
	lprintf("bgm: worker thread exiting\n");
	sceKernelExitDeleteThread(0);
	return 0;
}

int bgm_init(void)
{
	int status;

	if (bgm_initialized)
		return 0;

	lprintf("bgm_init: initializing modules & thread\n");
	if (getcwd(bgm_app_dir, sizeof(bgm_app_dir)) != NULL) {
		lprintf("bgm_init: detected app dir '%s'\n", bgm_app_dir);
	}
	init_av_modules();

	status = sceMp3InitResource();
	if (status < 0) {
		lprintf("bgm: sceMp3InitResource returned 0x%08X\n", status);
	}

	bgm_sem = sceKernelCreateSema("bgm_sem", 0, 0, 1, NULL);
	if (bgm_sem < 0) {
		lprintf("bgm: sceKernelCreateSema failed: 0x%08X\n", bgm_sem);
	}

	bgm_cmd = BGM_CMD_IDLE;
	bgm_active = 0;

	bgm_thid = sceKernelCreateThread("bgm_thread", bgm_worker_thread, 0x20, 0x4000, 0, NULL);
	if (bgm_thid >= 0) {
		sceKernelStartThread(bgm_thid, 0, NULL);
	} else {
		lprintf("bgm: failed to create bgm_thread: 0x%08X\n", bgm_thid);
		return -1;
	}

	bgm_initialized = 1;
	return 0;
}

void bgm_exit(void)
{
	if (!bgm_initialized)
		return;

	bgm_cmd = BGM_CMD_EXIT;
	if (bgm_sem >= 0) {
		sceKernelSignalSema(bgm_sem, 1);
	}
	if (bgm_thid >= 0) {
		sceKernelWaitThreadEnd(bgm_thid, NULL);
		bgm_thid = -1;
	}
	if (bgm_sem >= 0) {
		sceKernelDeleteSema(bgm_sem);
		bgm_sem = -1;
	}

	close_mp3();
	sceMp3TermResource();

	sceUtilityUnloadModule(PSP_MODULE_AV_MP3);
	sceUtilityUnloadModule(PSP_MODULE_AV_AVCODEC);

	bgm_initialized = 0;
}

int bgm_play(const char *path)
{
	if (!bgm_initialized) {
		if (bgm_init() < 0)
			return -1;
	}

	if (path && path[0] != '\0') {
		if (strcmp(bgm_file_path, path) != 0) {
			strncpy(bgm_file_path, path, sizeof(bgm_file_path) - 1);
			bgm_file_path[sizeof(bgm_file_path) - 1] = 0;
			close_mp3();
		}
	}

	bgm_cmd = BGM_CMD_PLAY;
	if (bgm_sem >= 0) {
		sceKernelSignalSema(bgm_sem, 1);
	}

	// Wait briefly for worker thread to process and flush its logs
	sceKernelDelayThread(200 * 1000); // 200ms
	lprintf("bgm_play: main thread check (active=%d, cmd=%d, handle=%d, fd=%d, channel=%d)\n",
		bgm_active, bgm_cmd, bgm_handle, bgm_fd, bgm_channel);

	return 0;
}

void bgm_stop(void)
{
	bgm_cmd = BGM_CMD_STOP;
	if (bgm_sem >= 0) {
		sceKernelSignalSema(bgm_sem, 1);
	}
	// Wait briefly for channel to be released
	int tries = 0;
	while (bgm_active && tries++ < 10) {
		sceKernelDelayThread(5 * 1000);
	}
	release_audio_channel();
}

void bgm_pause(void)
{
	bgm_cmd = BGM_CMD_PAUSE;
	if (bgm_sem >= 0) {
		sceKernelSignalSema(bgm_sem, 1);
	}
	int tries = 0;
	while (bgm_active && tries++ < 10) {
		sceKernelDelayThread(5 * 1000);
	}
	release_audio_channel();
}

void bgm_resume(void)
{
	if (bgm_file_path[0] != '\0') {
		bgm_cmd = BGM_CMD_RESUME;
		if (bgm_sem >= 0) {
			sceKernelSignalSema(bgm_sem, 1);
		}
	}
}

int bgm_is_playing(void)
{
	return bgm_active;
}

void bgm_set_volume(int vol)
{
	if (vol < 0) vol = 0;
	if (vol > PSP_AUDIO_VOLUME_MAX) vol = PSP_AUDIO_VOLUME_MAX;
	bgm_volume = vol;
}

void bgm_on_suspend(void)
{
	if (bgm_active) {
		bgm_pause();
	}
	release_audio_channel();
}

void bgm_on_resume(void)
{
	if (bgm_file_path[0] != '\0' && bgm_cmd == BGM_CMD_PAUSE) {
		bgm_resume();
	}
}
