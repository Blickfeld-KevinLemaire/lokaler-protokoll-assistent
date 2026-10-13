# Tests fuer den reinen C-Teil (vermerk_protokoll.c, vermerk_einrichtung.c) auf dem PC, ohne ESP-IDF:
#   make test
# Ohne eigenen gcc, mit Docker (Pfad zum Repository anpassen):
#   docker run --rm -v "<Repository>:/src" -w /src/firmware/components/vermerk_upload/test/host gcc:14 make test

CC      = gcc
CFLAGS  ?= -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion \
           -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer
KOMPONENTE := ../..
BUILD   := build
PROTOKOLL := $(KOMPONENTE)/vermerk_protokoll.c $(KOMPONENTE)/include/vermerk_protokoll.h
EINRICHTUNG := $(KOMPONENTE)/vermerk_einrichtung.c $(KOMPONENTE)/include/vermerk_einrichtung.h
RING := $(KOMPONENTE)/vermerk_ring.c $(KOMPONENTE)/include/vermerk_ring.h

.PHONY: test clean

test: $(BUILD)/test_vermerk_protokoll $(BUILD)/test_vermerk_einrichtung $(BUILD)/test_vermerk_ring
	./$(BUILD)/test_vermerk_protokoll
	./$(BUILD)/test_vermerk_einrichtung
	./$(BUILD)/test_vermerk_ring

$(BUILD)/test_vermerk_protokoll: test_vermerk_protokoll.c antworten_software.h $(PROTOKOLL)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(KOMPONENTE)/include -o $@ test_vermerk_protokoll.c $(KOMPONENTE)/vermerk_protokoll.c

$(BUILD)/test_vermerk_einrichtung: test_vermerk_einrichtung.c $(EINRICHTUNG) $(PROTOKOLL)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(KOMPONENTE)/include -o $@ test_vermerk_einrichtung.c $(KOMPONENTE)/vermerk_einrichtung.c \
		$(KOMPONENTE)/vermerk_protokoll.c

$(BUILD)/test_vermerk_ring: test_vermerk_ring.c $(RING)
	mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -I$(KOMPONENTE)/include -o $@ test_vermerk_ring.c $(KOMPONENTE)/vermerk_ring.c

clean:
	rm -rf $(BUILD)
