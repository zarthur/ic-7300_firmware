CC = cc
CPPFLAGS = -Iprototype -Ithird_party/ft8_lib
CFLAGS = -std=c11 -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE -O2 -g -Wall -Wextra
LDLIBS = -lm
DEP = third_party/ft8_lib
LIBSRC = $(wildcard $(DEP)/ft8/*.c) $(DEP)/common/monitor.c $(DEP)/fft/kiss_fft.c $(DEP)/fft/kiss_fftr.c
LIBOBJ = $(patsubst $(DEP)/%.c,build/lib/%.o,$(LIBSRC))
OBJ = build/codec.o build/qso.o build/alloc.o build/station.o
.PHONY: all test bootstrap
all: build/ft8_proto build/test_qso build/test_codec
bootstrap:
	python3 tools/bootstrap.py
build/lib/%.o: $(DEP)/%.c prototype/alloc.h
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -include prototype/alloc.h -Dmalloc=tracked_malloc -Dcalloc=tracked_calloc -Dfree=tracked_free -c $< -o $@
build/%.o: prototype/%.c prototype/codec.h prototype/qso.h prototype/alloc.h prototype/station.h
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
build/ft8_proto: build/main.o $(OBJ) $(LIBOBJ)
	$(CC) $(CFLAGS) $^ $(LDLIBS) -o $@
build/test_qso: tests/test_qso.c build/qso.o
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ -o $@
build/test_codec: tests/test_codec.c $(OBJ) $(LIBOBJ)
	$(CC) $(CPPFLAGS) $(CFLAGS) $^ $(LDLIBS) -o $@
test: all
	python3 -m unittest discover -s tests -v
	build/test_qso
	build/test_codec
	build/ft8_proto simulate
