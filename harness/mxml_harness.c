//
// Harness driver for fuzzing Mini-XML (mxml) library.
// Reads XML from file (argv[1]) or stdin, parses with mxmlLoadString,
// exits 0=valid parse, 1=well-formed rejection, 2=harness error.
//
// Exit code contract (C harness):
//   0  — valid parse          : mxml accepted the XML
//   1  — well-formed rejection: mxml rejected the input (parse error)
//   2  — harness error        : cannot read input file or I/O failure
//
// Exit codes 3-5 are added by the Python wrapper (fuzzer/run_harness.py):
//   3  — sanitizer crash      : ASan or UBSan detected a violation
//   4  — timeout              : input exceeded 5-second limit
//   5  — bug crash            : unexpected crash (segfault, abort, etc.)
//

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mxml.h"

//
// Read entire file or stdin into a dynamically allocated buffer.
// Returns allocated string (caller must free) or NULL on error.
// On error, prints to stderr and sets *err_out to 2 (harness error).
//
static char *read_input(const char *path, int *err_out)
{
    FILE *fp;
    char *buffer = NULL;
    size_t size = 0, capacity = 4096, n;

    if (path) {
        fp = fopen(path, "rb");
        if (!fp) {
            fprintf(stderr, "harness: cannot open '%s'\n", path);
            *err_out = 2;
            return NULL;
        }
    } else {
        fp = stdin;
    }

    buffer = malloc(capacity);
    if (!buffer) {
        fprintf(stderr, "harness: out of memory\n");
        if (path) fclose(fp);
        *err_out = 2;
        return NULL;
    }

    while ((n = fread(buffer + size, 1, capacity - size, fp)) > 0) {
        size += n;
        if (size == capacity) {
            capacity *= 2;
            char *newbuf = realloc(buffer, capacity);
            if (!newbuf) {
                fprintf(stderr, "harness: out of memory\n");
                free(buffer);
                if (path) fclose(fp);
                *err_out = 2;
                return NULL;
            }
            buffer = newbuf;
        }
    }

    int read_error = ferror(fp);

    if (path) fclose(fp);

    if (read_error) {
        fprintf(stderr, "harness: read error\n");
        free(buffer);
        *err_out = 2;
        return NULL;
    }

    buffer[size] = '\0';
    return buffer;
}

//
// Error callback: prints mxml parse errors to stderr for debugging.
// The harness exit code is determined by the return value of mxmlLoadString.
//
static void err_cb(void *cbdata, const char *message)
{
    (void)cbdata;
    fprintf(stderr, "mxml parse error: %s\n", message);
}

int main(int argc, char *argv[])
{
    const char *input_path = (argc > 1) ? argv[1] : NULL;
    int harness_err = 0;
    char *input = read_input(input_path, &harness_err);

    if (!input) {
        return harness_err; // 2 on I/O or OOM
    }

    mxml_options_t *options = mxmlOptionsNew();
    if (!options) {
        fprintf(stderr, "harness: mxmlOptionsNew failed\n");
        free(input);
        return 2;
    }

    mxmlOptionsSetErrorCallback(options, err_cb, NULL);

    mxml_node_t *tree = mxmlLoadString(NULL, options, input);

    free(input);
    mxmlOptionsDelete(options);

    if (tree) {
        mxmlDelete(tree);
        return 0; // valid parse
    } else {
        return 1; // well-formed rejection (parse error)
    }
}
