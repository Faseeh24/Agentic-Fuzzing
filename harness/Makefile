#
# Makefile for mxml harness driver.
# Builds with ASan+UBSan for memory-safety/UB detection.
#
# Build (Docker — recommended on Windows):
#   docker build -t mxml-harness ..
#   docker run --rm -v "$(pwd)":/src/harness mxml-harness make -C harness
#
# Build (native Linux / WSL / MSYS2 with sanitizer packages):
#   make
#
# Run sample tests:
#   make test
#
# Clean build artifacts:
#   make clean
#

CC      = gcc
CFLAGS  = -fsanitize=address,undefined -g -O1 -Wall -I../target/mxml
MXML_SRC = ../target/mxml
MXML_OBJS = $(MXML_SRC)/mxml-file.o $(MXML_SRC)/mxml-node.o $(MXML_SRC)/mxml-attr.o \
            $(MXML_SRC)/mxml-get.o $(MXML_SRC)/mxml-search.o $(MXML_SRC)/mxml-set.o \
            $(MXML_SRC)/mxml-index.o $(MXML_SRC)/mxml-options.o $(MXML_SRC)/mxml-private.o

# Use .exe on Windows, no extension on Linux
ifeq ($(OS),Windows_NT)
BINARY = mxml_harness.exe
else
BINARY = mxml_harness
endif

all: $(BINARY)

$(BINARY): mxml_harness.o $(MXML_OBJS)
	$(CC) $(CFLAGS) -o $@ mxml_harness.o $(MXML_OBJS)

mxml_harness.o: mxml_harness.c
	$(CC) $(CFLAGS) -c -o $@ $<

$(MXML_SRC)/%.o: $(MXML_SRC)/%.c
	$(CC) $(CFLAGS) -c -o $@ $<

test: $(BINARY)
	@echo "Running sample tests..."
	@PASS=0; FAIL=0; \
	for t in sample_tests/*.xml; do \
	    name=$$(basename $$t .xml); \
	    case "$$name" in \
		valid_parse|valid_simple|valid_with_decl) expect=0 ;; \
		reject_*) expect=1 ;; \
		empty_input) expect=1 ;; \
		*) expect=-1 ;; \
	    esac; \
	    if [ $$expect -eq -1 ]; then continue; fi; \
	    ./$(BINARY) "$$t" > /dev/null 2>&1; ret=$$?; \
	    if [ $$ret -eq $$expect ]; then \
		echo "  PASS: $$name (exit=$$ret)"; \
		PASS=$$((PASS+1)); \
	    else \
		echo "  FAIL: $$name (expected $$expect, got $$ret)"; \
		FAIL=$$((FAIL+1)); \
	    fi; \
	done; \
	echo ""; \
	echo "Results: $$PASS passed, $$FAIL failed"; \
	exit $$FAIL

test-missing-file: $(BINARY)
	@echo "Testing harness error path (missing file)..."
	./$(BINARY) nonexistent.xml > /dev/null 2>&1; \
	if [ $$? -eq 2 ]; then \
	    echo "  PASS: missing file (exit=2)"; \
	else \
	    echo "  FAIL: missing file — expected exit=2"; \
	    exit 1; \
	fi

clean:
	rm -f $(BINARY) *.o $(MXML_OBJS)

.PHONY: all test test-missing-file clean