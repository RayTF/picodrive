#ifndef __BGM_H__
#define __BGM_H__

#ifdef __cplusplus
extern "C" {
#endif

int  bgm_init(void);
void bgm_exit(void);
int  bgm_play(const char *path);
void bgm_stop(void);
void bgm_pause(void);
void bgm_resume(void);
int  bgm_is_playing(void);
void bgm_set_volume(int vol);
void bgm_on_suspend(void);
void bgm_on_resume(void);

#ifdef __cplusplus
}
#endif

#endif /* __BGM_H__ */
