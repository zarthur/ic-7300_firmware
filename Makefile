CC = cc
BUILD ?= build
CPPFLAGS = -Iprototype -Ithird_party/ft8_lib
CFLAGS = -std=c11 -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE -O2 -g -Wall -Wextra
LDLIBS = -lm
DEP = third_party/ft8_lib
LIBSRC = $(wildcard $(DEP)/ft8/*.c) $(DEP)/common/monitor.c $(DEP)/fft/kiss_fft.c $(DEP)/fft/kiss_fftr.c
LIBOBJ = $(patsubst $(DEP)/%.c,$(BUILD)/lib/%.o,$(LIBSRC))
OBJ = $(BUILD)/codec.o $(BUILD)/qso.o $(BUILD)/alloc.o $(BUILD)/station.o
.PHONY: all test bootstrap development-check test-synthetic
all: $(BUILD)/ft8_proto $(BUILD)/test_qso $(BUILD)/test_codec $(BUILD)/test_station
development-check:
	.venv/bin/python tools/development_check.py
test-synthetic:
	.venv/bin/python tools/development_check.py --profile synthetic
bootstrap:
	python3 tools/bootstrap.py
$(BUILD)/lib/%.o: $(DEP)/%.c prototype/alloc.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -include prototype/alloc.h -Dmalloc=tracked_malloc -Dcalloc=tracked_calloc -Dfree=tracked_free -c $< -o $@
$(BUILD)/%.o: prototype/%.c prototype/codec.h prototype/qso.h prototype/alloc.h prototype/station.h
	@mkdir -p $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
$(BUILD)/ft8_proto: $(BUILD)/main.o $(OBJ) $(LIBOBJ)
	$(CC) $(CFLAGS) $^ $(LDLIBS) -o $@
$(BUILD)/test_qso: tests/test_qso.c $(BUILD)/qso.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o $@
$(BUILD)/test_codec: tests/test_codec.c $(OBJ) $(LIBOBJ)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@
$(BUILD)/test_station: tests/test_station.c $(OBJ) $(LIBOBJ)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@
test: all
	FT8_PROTO=$(BUILD)/ft8_proto python3 -m unittest discover -s tests -v
	$(BUILD)/test_qso
	$(BUILD)/test_codec
	$(BUILD)/test_station
	$(BUILD)/ft8_proto simulate
