#include <ctype.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "game_metadata.h"
#include "../libpicofe/lprintf.h"

#define GAME_METADATA_FILE_MAX (256 * 1024)
#define GAME_METADATA_LINE_MAX 768
#define GAME_METADATA_UNKNOWN_MAX 16
#define GAME_METADATA_KEY_MAX 32

enum metadata_field
{
	MF_ROM = 1 << 0,
	MF_ID = 1 << 1,
	MF_TITLE = 1 << 2,
	MF_SYSTEM = 1 << 3,
	MF_RELEASE_YEAR = 1 << 4,
	MF_GENRE = 1 << 5,
	MF_INFORMATION = 1 << 6,
	MF_THUMBNAIL = 1 << 7,
	MF_PLAYERS = 1 << 8,
	MF_REGION = 1 << 9,
	MF_RATING = 1 << 10,
	MF_PUBLISHER = 1 << 11,
	MF_DEVELOPER = 1 << 12,
	MF_PROVIDER = 1 << 13,
	MF_PROVIDER_ID = 1 << 14
};

static game_metadata *metadata_entries;
static int metadata_count;
static int metadata_capacity;
static game_metadata_status metadata_status = GAME_METADATA_UNINITIALIZED;
static char metadata_error[160];
static int metadata_error_line;

static void metadata_set_error(game_metadata_status status, int line,
	const char *format, ...)
{
	va_list args;

	metadata_status = status;
	metadata_error_line = line;
	va_start(args, format);
	vsnprintf(metadata_error, sizeof(metadata_error), format, args);
	va_end(args);
	metadata_error[sizeof(metadata_error) - 1] = 0;
}

void game_metadata_unload(void)
{
	free(metadata_entries);
	metadata_entries = NULL;
	metadata_count = 0;
	metadata_capacity = 0;
	metadata_status = GAME_METADATA_UNINITIALIZED;
	metadata_error[0] = 0;
	metadata_error_line = 0;
}

static char *trim_left(char *text)
{
	while (*text == ' ')
		text++;
	return text;
}

static void trim_right(char *text)
{
	int length = strlen(text);

	while (length > 0 && text[length - 1] == ' ')
		text[--length] = 0;
}

static int strip_comment(char *line)
{
	int escaped = 0;
	char quote = 0;
	char *quoted_scalar = NULL;
	char *p;
	char *colon;

	for (p = line; *p != 0; p++) {
		unsigned char c = (unsigned char)*p;

		if (c == '\t' || c < 0x20 || c >= 0x7f)
			return -1;
	}
	colon = strchr(line, ':');
	if (colon != NULL) {
		quoted_scalar = trim_left(colon + 1);
		if (*quoted_scalar != '"' && *quoted_scalar != '\'')
			quoted_scalar = NULL;
	}

	for (p = line; *p != 0; p++) {
		unsigned char c = (unsigned char)*p;

		if (quote != 0) {
			if (quote == '"' && !escaped && c == '\\') {
				escaped = 1;
				continue;
			}
			if (quote == '\'' && c == '\'' && p[1] == '\'') {
				p++;
				continue;
			}
			if (!escaped && c == (unsigned char)quote)
				quote = 0;
			escaped = 0;
			continue;
		}
		if (p == quoted_scalar)
			quote = c;
		else if (c == '#') {
			*p = 0;
			break;
		}
	}
	return quote == 0 ? 0 : -1;
}

static int parse_key_value(char *text, char **key, char **value)
{
	char *colon;
	char *p;

	colon = strchr(text, ':');
	if (colon == NULL)
		return -1;
	*colon = 0;
	trim_right(text);
	text = trim_left(text);
	if (*text == 0)
		return -1;
	for (p = text; *p != 0; p++) {
		if (!(islower((unsigned char)*p) || isdigit((unsigned char)*p) ||
			*p == '_'))
			return -1;
	}
	*key = text;
	*value = trim_left(colon + 1);
	trim_right(*value);
	return 0;
}

static int parse_scalar(const char *input, char *output, int output_size)
{
	const char *p = input;
	char *out = output;
	char quote = 0;
	int remaining = output_size - 1;

	if (*p == 0)
		return -1;
	if (*p == '"' || *p == '\'')
		quote = *p++;

	while (*p != 0) {
		unsigned char c = (unsigned char)*p++;

		if (quote != 0 && c == (unsigned char)quote) {
			if (quote == '\'' && *p == '\'') {
				p++;
				c = '\'';
			}
			else {
				if (*p != 0)
					return -1;
				quote = 0;
				break;
			}
		}
		else if (quote == '"' && c == '\\') {
			c = (unsigned char)*p++;
			if (c != '"' && c != '\\' && c != '/')
				return -1;
		}
		else if (quote == 0 && (c == '[' || c == ']' || c == '{' ||
			c == '}' || c == '&' || c == '*' || c == '!' || c == '|' ||
			c == '>' || c == '`' || (c == ':' && *p == ' ')))
			return -1;

		if (remaining <= 0)
			return -2;
		*out++ = c;
		remaining--;
	}
	if (quote != 0 || out == output)
		return -1;
	*out = 0;
	return 0;
}

static int parse_integer(const char *value, int minimum, int maximum, int *result)
{
	char *end;
	long parsed;

	errno = 0;
	parsed = strtol(value, &end, 10);
	if (errno != 0 || end == value || *end != 0 ||
		parsed < minimum || parsed > maximum)
		return -1;
	*result = (int)parsed;
	return 0;
}

static int normalize_relative_path(const char *input, char *output,
	int output_size)
{
	const char *p = input;
	char *out = output;
	int remaining = output_size - 1;
	int segment_length = 0;
	int segment_is_dot = 1;

	while (p[0] == '.' && p[1] == '/')
		p += 2;
	if (*p == 0 || *p == '/' || strchr(p, ':') != NULL ||
		strchr(p, '\\') != NULL)
		return -1;

	while (*p != 0) {
		unsigned char c = (unsigned char)*p++;

		if (c == '/') {
			if (segment_length == 0)
				continue;
			if ((segment_length == 1 && segment_is_dot) ||
				(segment_length == 2 && out[-1] == '.' && out[-2] == '.'))
				return -1;
			if (remaining <= 0)
				return -1;
			*out++ = '/';
			remaining--;
			segment_length = 0;
			segment_is_dot = 1;
			continue;
		}
		if (c < 0x20 || c >= 0x7f)
			return -1;
		if (remaining <= 0)
			return -1;
		*out++ = c;
		remaining--;
		segment_length++;
		if (c != '.')
			segment_is_dot = 0;
	}
	if (segment_length == 0 || (segment_length == 1 && segment_is_dot) ||
		(segment_length == 2 && out[-1] == '.' && out[-2] == '.'))
		return -1;
	*out = 0;
	return 0;
}

static int metadata_field_id(const char *key)
{
	if (strcmp(key, "rom") == 0) return MF_ROM;
	if (strcmp(key, "id") == 0) return MF_ID;
	if (strcmp(key, "title") == 0) return MF_TITLE;
	if (strcmp(key, "system") == 0) return MF_SYSTEM;
	if (strcmp(key, "release_year") == 0) return MF_RELEASE_YEAR;
	if (strcmp(key, "genre") == 0) return MF_GENRE;
	if (strcmp(key, "information") == 0) return MF_INFORMATION;
	if (strcmp(key, "thumbnail") == 0) return MF_THUMBNAIL;
	if (strcmp(key, "players") == 0) return MF_PLAYERS;
	if (strcmp(key, "region") == 0) return MF_REGION;
	if (strcmp(key, "rating") == 0) return MF_RATING;
	if (strcmp(key, "publisher") == 0) return MF_PUBLISHER;
	if (strcmp(key, "developer") == 0) return MF_DEVELOPER;
	if (strcmp(key, "provider") == 0) return MF_PROVIDER;
	if (strcmp(key, "provider_id") == 0) return MF_PROVIDER_ID;
	return 0;
}

static int set_string_field(char *destination, int destination_size,
	const char *value)
{
	return parse_scalar(value, destination, destination_size);
}

static int parse_game_field(game_metadata *entry, unsigned int *fields,
	char unknown_keys[][GAME_METADATA_KEY_MAX], int *unknown_count,
	const char *key, const char *value)
{
	int field = metadata_field_id(key);
	int result = 0;

	if (field == 0) {
		char ignored[GAME_METADATA_LINE_MAX + 1];
		int i;

		for (i = 0; i < *unknown_count; i++)
			if (strcmp(unknown_keys[i], key) == 0)
				return -3;
		if (*unknown_count >= GAME_METADATA_UNKNOWN_MAX ||
			strlen(key) >= GAME_METADATA_KEY_MAX)
			return -4;
		strcpy(unknown_keys[(*unknown_count)++], key);
		return parse_scalar(value, ignored, sizeof(ignored)) < 0 ? -1 : 1;
	}
	if ((*fields & field) != 0)
		return -3;
	*fields |= field;

	switch (field) {
	case MF_ROM:
		result = set_string_field(entry->rom, sizeof(entry->rom), value);
		break;
	case MF_ID:
		result = set_string_field(entry->id, sizeof(entry->id), value);
		break;
	case MF_TITLE:
		result = set_string_field(entry->title, sizeof(entry->title), value);
		break;
	case MF_SYSTEM:
		result = set_string_field(entry->system, sizeof(entry->system), value);
		break;
	case MF_RELEASE_YEAR:
		result = parse_integer(value, 1000, 9999, &entry->release_year);
		break;
	case MF_GENRE:
		result = set_string_field(entry->genre, sizeof(entry->genre), value);
		break;
	case MF_INFORMATION:
		result = set_string_field(entry->information, sizeof(entry->information), value);
		break;
	case MF_THUMBNAIL:
		result = set_string_field(entry->thumbnail, sizeof(entry->thumbnail), value);
		break;
	case MF_PLAYERS:
		result = parse_integer(value, 1, 8, &entry->players);
		break;
	case MF_REGION:
		result = set_string_field(entry->region, sizeof(entry->region), value);
		break;
	case MF_RATING:
		result = parse_integer(value, 0, 100, &entry->rating);
		break;
	case MF_PUBLISHER:
		result = set_string_field(entry->publisher, sizeof(entry->publisher), value);
		break;
	case MF_DEVELOPER:
		result = set_string_field(entry->developer, sizeof(entry->developer), value);
		break;
	case MF_PROVIDER:
		result = set_string_field(entry->provider, sizeof(entry->provider), value);
		break;
	case MF_PROVIDER_ID:
		result = set_string_field(entry->provider_id, sizeof(entry->provider_id), value);
		break;
	}
	return result;
}

static int append_entry(game_metadata *entry, unsigned int fields, int line)
{
	game_metadata *resized;
	char normalized[GAME_METADATA_ROM_MAX];

	if ((fields & MF_ROM) == 0) {
		metadata_set_error(GAME_METADATA_INVALID, line,
			"game entry is missing rom");
		return -1;
	}
	if (normalize_relative_path(entry->rom, normalized, sizeof(normalized)) < 0) {
		metadata_set_error(GAME_METADATA_INVALID, line,
			"unsafe or invalid ROM path");
		return -1;
	}
	strcpy(entry->rom, normalized);
	if (entry->thumbnail[0] != 0) {
		if (normalize_relative_path(entry->thumbnail, normalized,
				sizeof(normalized)) < 0 ||
			strncasecmp(normalized, "metadata/art/", 13) != 0) {
			lprintf("metadata: line %d: skipping game with unsafe thumbnail path\n",
				line);
			return 1;
		}
		strcpy(entry->thumbnail, normalized);
	}
	if (metadata_count >= GAME_METADATA_MAX_ENTRIES) {
		metadata_set_error(GAME_METADATA_INVALID, line,
			"catalog exceeds %d entries", GAME_METADATA_MAX_ENTRIES);
		return -1;
	}
	if (metadata_count >= metadata_capacity) {
		int capacity = metadata_capacity == 0 ? 16 : metadata_capacity * 2;
		if (capacity > GAME_METADATA_MAX_ENTRIES)
			capacity = GAME_METADATA_MAX_ENTRIES;
		resized = realloc(metadata_entries, capacity * sizeof(*metadata_entries));
		if (resized == NULL) {
			metadata_set_error(GAME_METADATA_OUT_OF_MEMORY, line,
				"not enough memory for metadata catalog");
			return -1;
		}
		metadata_entries = resized;
		metadata_capacity = capacity;
	}
	metadata_entries[metadata_count++] = *entry;
	return 0;
}

static int compare_entries(const void *left, const void *right)
{
	const game_metadata *a = left;
	const game_metadata *b = right;
	int result = strcasecmp(a->rom, b->rom);

	return result != 0 ? result : strcmp(a->rom, b->rom);
}

int game_metadata_load(const char *filename)
{
	char line[GAME_METADATA_LINE_MAX + 2];
	game_metadata entry;
	unsigned int fields = 0;
	char unknown_keys[GAME_METADATA_UNKNOWN_MAX][GAME_METADATA_KEY_MAX];
	int unknown_count = 0;
	int entry_line = 0;
	int line_number = 0;
	int version_seen = 0;
	int games_seen = 0;
	int in_games = 0;
	int have_entry = 0;
	long file_size;
	FILE *file;

	game_metadata_unload();
	if (filename == NULL || *filename == 0) {
		metadata_set_error(GAME_METADATA_IO_ERROR, 0,
			"metadata filename is empty");
		return -1;
	}

	file = fopen(filename, "rb");
	if (file == NULL) {
		if (errno == ENOENT) {
			metadata_status = GAME_METADATA_MISSING;
			lprintf("metadata: %s not found, using ROM filenames\n", filename);
			return 0;
		}
		metadata_set_error(GAME_METADATA_IO_ERROR, 0,
			"failed to open metadata file");
		lprintf("metadata: failed to open %s: %s\n", filename, strerror(errno));
		return -1;
	}
	if (fseek(file, 0, SEEK_END) != 0 || (file_size = ftell(file)) < 0 ||
		file_size > GAME_METADATA_FILE_MAX || fseek(file, 0, SEEK_SET) != 0) {
		metadata_set_error(GAME_METADATA_INVALID, 0,
			"metadata file exceeds %d bytes", GAME_METADATA_FILE_MAX);
		goto fail;
	}

	memset(&entry, 0, sizeof(entry));
	entry.rating = -1;
	while (fgets(line, sizeof(line), file) != NULL) {
		char *text;
		char *key;
		char *value;
		int indent = 0;
		int result;
		int length;

		line_number++;
		length = strlen(line);
		if (length > 0 && line[length - 1] != '\n' && !feof(file)) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"line exceeds %d bytes", GAME_METADATA_LINE_MAX);
			goto fail;
		}
		while (length > 0 && (line[length - 1] == '\r' ||
			line[length - 1] == '\n'))
			line[--length] = 0;
		if (strip_comment(line) < 0) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"non-ASCII/control character or unterminated quote");
			goto fail;
		}
		trim_right(line);
		if (line[0] == 0)
			continue;
		while (line[indent] == ' ')
			indent++;
		text = line + indent;

		if (indent == 0) {
			if (in_games) {
				result = have_entry ? append_entry(&entry, fields, entry_line) : 0;
				if (result < 0)
					goto fail;
				have_entry = 0;
				in_games = 0;
			}
			if (parse_key_value(text, &key, &value) < 0) {
				metadata_set_error(GAME_METADATA_INVALID, line_number,
					"invalid top-level key");
				goto fail;
			}
			if (strcmp(key, "version") == 0) {
				int version;
				if (version_seen || parse_integer(value, 1, 9999, &version) < 0) {
					metadata_set_error(GAME_METADATA_INVALID, line_number,
						"invalid or duplicate version");
					goto fail;
				}
				version_seen = 1;
				if (version != 1) {
					metadata_set_error(GAME_METADATA_UNSUPPORTED, line_number,
						"unsupported metadata version %d", version);
					goto fail;
				}
			}
			else if (strcmp(key, "games") == 0) {
				if (games_seen || *value != 0) {
					metadata_set_error(GAME_METADATA_INVALID, line_number,
						"games must introduce a list");
					goto fail;
				}
				games_seen = 1;
				in_games = 1;
			}
			else {
				metadata_set_error(GAME_METADATA_INVALID, line_number,
					"unknown top-level key '%s'", key);
				goto fail;
			}
			continue;
		}

		if (!in_games || indent != 2 || text[0] != '-' || text[1] != ' ') {
			if (!in_games || indent != 4 || !have_entry) {
				metadata_set_error(GAME_METADATA_INVALID, line_number,
					"invalid games list indentation");
				goto fail;
			}
		}
		else {
			if (have_entry && append_entry(&entry, fields, entry_line) < 0)
				goto fail;
			memset(&entry, 0, sizeof(entry));
			entry.rating = -1;
			fields = 0;
			unknown_count = 0;
			have_entry = 1;
			entry_line = line_number;
			text = trim_left(text + 2);
			if (*text == 0) {
				metadata_set_error(GAME_METADATA_INVALID, line_number,
					"game list item must start with a field");
				goto fail;
			}
		}

		if (parse_key_value(text, &key, &value) < 0 || *value == 0) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"invalid game field");
			goto fail;
		}
		result = parse_game_field(&entry, &fields, unknown_keys,
			&unknown_count, key, value);
		if (result == 1) {
			lprintf("metadata: line %d: ignoring unknown field '%s'\n",
				line_number, key);
		}
		else if (result == -2) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"value for '%s' is too long", key);
			goto fail;
		}
		else if (result == -3) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"duplicate game field '%s'", key);
			goto fail;
		}
		else if (result == -4) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"too many or oversized unknown fields");
			goto fail;
		}
		else if (result < 0) {
			metadata_set_error(GAME_METADATA_INVALID, line_number,
				"invalid value for '%s'", key);
			goto fail;
		}
	}

	if (ferror(file)) {
		metadata_set_error(GAME_METADATA_IO_ERROR, line_number,
			"failed while reading metadata file");
		goto fail;
	}
	if (!version_seen || !games_seen) {
		metadata_set_error(GAME_METADATA_INVALID, line_number,
			"metadata requires version and games");
		goto fail;
	}
	if (have_entry && append_entry(&entry, fields, entry_line) < 0)
		goto fail;

	if (metadata_count > 1) {
		int i;
		qsort(metadata_entries, metadata_count, sizeof(*metadata_entries),
			compare_entries);
		for (i = 1; i < metadata_count; i++) {
			if (strcasecmp(metadata_entries[i - 1].rom,
					metadata_entries[i].rom) == 0) {
				metadata_set_error(GAME_METADATA_INVALID, 0,
					"duplicate ROM path '%s'", metadata_entries[i].rom);
				goto fail;
			}
		}
	}

	fclose(file);
	metadata_status = GAME_METADATA_LOADED;
	metadata_error[0] = 0;
	metadata_error_line = 0;
	lprintf("metadata: loaded %d game%s from %s\n", metadata_count,
		metadata_count == 1 ? "" : "s", filename);
	return metadata_count;

fail:
	lprintf("metadata: %s:%d: %s\n", filename, metadata_error_line,
		metadata_error);
	fclose(file);
	free(metadata_entries);
	metadata_entries = NULL;
	metadata_count = 0;
	metadata_capacity = 0;
	return -1;
}

const game_metadata *game_metadata_find(const char *rom_path)
{
	char normalized[GAME_METADATA_ROM_MAX];
	int low = 0;
	int high = metadata_count - 1;

	if (metadata_status != GAME_METADATA_LOADED || rom_path == NULL ||
		normalize_relative_path(rom_path, normalized, sizeof(normalized)) < 0)
		return NULL;
	while (low <= high) {
		int middle = low + (high - low) / 2;
		int comparison = strcasecmp(normalized, metadata_entries[middle].rom);

		if (comparison == 0)
			return &metadata_entries[middle];
		if (comparison < 0)
			high = middle - 1;
		else
			low = middle + 1;
	}
	return NULL;
}

const game_metadata *game_metadata_find_file(const char *directory,
	const char *filename)
{
	char path[GAME_METADATA_ROM_MAX];
	const char *separator;
	int length;

	if (directory == NULL || filename == NULL || *filename == 0)
		return NULL;
	length = strlen(directory);
	separator = length == 0 || directory[length - 1] == '/' ? "" : "/";
	if (snprintf(path, sizeof(path), "%s%s%s", directory, separator,
			filename) >= (int)sizeof(path))
		return NULL;
	return game_metadata_find(path);
}

const char *game_metadata_system_label(const game_metadata *metadata,
	const char *filename)
{
	const char *extension;

	if (metadata != NULL && metadata->system[0] != 0)
		return metadata->system;
	if (filename == NULL || (extension = strrchr(filename, '.')) == NULL ||
			extension[1] == 0)
		return "UNKNOWN SYSTEM";
	extension++;
	if (strcasecmp(extension, "sms") == 0)
		return "MASTER SYSTEM";
	if (strcasecmp(extension, "gg") == 0)
		return "GAME GEAR";
	if (strcasecmp(extension, "32x") == 0)
		return "32X";
	if (strcasecmp(extension, "cue") == 0 ||
		strcasecmp(extension, "chd") == 0 ||
		strcasecmp(extension, "iso") == 0 ||
		strcasecmp(extension, "cso") == 0)
		return "SEGA / MEGA CD";
	if (strcasecmp(extension, "pco") == 0)
		return "SEGA PICO";
	if (strcasecmp(extension, "md") == 0 ||
		strcasecmp(extension, "gen") == 0 ||
		strcasecmp(extension, "smd") == 0 ||
		strcasecmp(extension, "bin") == 0)
		return "MEGA DRIVE / GENESIS";
	return "UNKNOWN SYSTEM";
}

int game_metadata_wrap_information_line(const char *text, int offset,
	char *line, int line_size, int max_chars)
{
	const char *start;
	int length = 0;
	int last_space = -1;
	int text_length;

	if (text == NULL || line == NULL || line_size < 2 || max_chars < 1 ||
		offset < 0)
		return -1;
	text_length = strlen(text);
	if (offset > text_length)
		return -1;
	while (text[offset] == ' ')
		offset++;
	start = text + offset;
	if (max_chars >= line_size)
		max_chars = line_size - 1;
	while (start[length] != 0 && length < max_chars) {
		if (start[length] == ' ')
			last_space = length;
		length++;
	}
	if (start[length] != 0 && start[length] != ' ' && last_space > 0)
		length = last_space;
	memcpy(line, start, length);
	line[length] = 0;
	offset += length;
	while (text[offset] == ' ')
		offset++;
	return offset;
}

int game_metadata_count(void)
{
	return metadata_count;
}

game_metadata_status game_metadata_get_status(void)
{
	return metadata_status;
}

const char *game_metadata_get_error(void)
{
	return metadata_error;
}

int game_metadata_get_error_line(void)
{
	return metadata_error_line;
}

const char *game_metadata_status_name(game_metadata_status status)
{
	switch (status) {
	case GAME_METADATA_UNINITIALIZED: return "uninitialized";
	case GAME_METADATA_MISSING: return "missing";
	case GAME_METADATA_LOADED: return "loaded";
	case GAME_METADATA_INVALID: return "invalid";
	case GAME_METADATA_UNSUPPORTED: return "unsupported";
	case GAME_METADATA_IO_ERROR: return "I/O error";
	case GAME_METADATA_OUT_OF_MEMORY: return "out of memory";
	}
	return "unknown";
}
