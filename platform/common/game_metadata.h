#ifndef PICO_GAME_METADATA_H
#define PICO_GAME_METADATA_H

#define GAME_METADATA_MAX_ENTRIES 512
#define GAME_METADATA_ROM_MAX 256
#define GAME_METADATA_ID_MAX 64
#define GAME_METADATA_TITLE_MAX 96
#define GAME_METADATA_SYSTEM_MAX 32
#define GAME_METADATA_GENRE_MAX 32
#define GAME_METADATA_INFO_MAX 512
#define GAME_METADATA_ART_MAX 128
#define GAME_METADATA_REGION_MAX 24
#define GAME_METADATA_COMPANY_MAX 64
#define GAME_METADATA_PROVIDER_MAX 32
#define GAME_METADATA_PROVIDER_ID_MAX 64

typedef struct game_metadata
{
	char rom[GAME_METADATA_ROM_MAX];
	char id[GAME_METADATA_ID_MAX];
	char title[GAME_METADATA_TITLE_MAX];
	char system[GAME_METADATA_SYSTEM_MAX];
	char genre[GAME_METADATA_GENRE_MAX];
	char information[GAME_METADATA_INFO_MAX];
	char thumbnail[GAME_METADATA_ART_MAX];
	char region[GAME_METADATA_REGION_MAX];
	char publisher[GAME_METADATA_COMPANY_MAX];
	char developer[GAME_METADATA_COMPANY_MAX];
	char provider[GAME_METADATA_PROVIDER_MAX];
	char provider_id[GAME_METADATA_PROVIDER_ID_MAX];
	int release_year;
	int players;
	int rating;
} game_metadata;

typedef enum game_metadata_status
{
	GAME_METADATA_UNINITIALIZED = 0,
	GAME_METADATA_MISSING,
	GAME_METADATA_LOADED,
	GAME_METADATA_INVALID,
	GAME_METADATA_UNSUPPORTED,
	GAME_METADATA_IO_ERROR,
	GAME_METADATA_OUT_OF_MEMORY
} game_metadata_status;

/* Returns the loaded entry count, zero for a missing/empty catalog, or -1. */
int game_metadata_load(const char *filename);
void game_metadata_unload(void);

const game_metadata *game_metadata_find(const char *rom_path);
const game_metadata *game_metadata_find_file(const char *directory,
	const char *filename);
const char *game_metadata_system_label(const game_metadata *metadata,
	const char *filename);
int game_metadata_wrap_information_line(const char *text, int offset,
	char *line, int line_size, int max_chars);
int game_metadata_count(void);
game_metadata_status game_metadata_get_status(void);
const char *game_metadata_get_error(void);
int game_metadata_get_error_line(void);
const char *game_metadata_status_name(game_metadata_status status);

#endif /* PICO_GAME_METADATA_H */
