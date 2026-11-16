/*
 * Deterministic Lab Authentication Harness for PENT-07 (MYO062)
 *
 * Isolated, authorization-only C target reproducing the 05.10 lecture's
 * 2-second password verification loop for Frida Interceptor observation
 * (onEnter / onLeave) and tampering (argument rewrite / retval.replace).
 *
 * Compile locally (do NOT commit compiled binaries):
 *   Linux/macOS: gcc -O0 -g -fno-inline android-lab/lab/tests/targets/hedef.c -o /tmp/hedef
 *   Windows MinGW: gcc -O0 -g -fno-inline android-lab/lab/tests/targets/hedef.c -o %TEMP%\hedef.exe
 */

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#define NOINLINE __declspec(noinline)
#else
#include <unistd.h>
#if defined(__GNUC__) || defined(__clang__)
#define NOINLINE __attribute__((noinline))
#else
#define NOINLINE
#endif
#endif

#define EXPECTED_PASS "gizli123"
#define DEFAULT_INPUT_PASS "deneme123"
#define DEFAULT_ROLE_LEVEL 1
#define MIN_REQUIRED_LEVEL 1
#define DEFAULT_INTERVAL_MS 2000
#define DEFAULT_ITERATIONS 3

static void sleep_ms(int ms) {
    if (ms <= 0) {
        return;
    }
#ifdef _WIN32
    Sleep((DWORD)ms);
#else
    usleep((useconds_t)ms * 1000U);
#endif
}

static int parse_int_arg(const char *text, int min_val, int max_val, int *out_val) {
    char *end = NULL;
    long parsed = 0;
    if (text == NULL || text[0] == '\0' || out_val == NULL) {
        return 0;
    }
    parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0') {
        return 0;
    }
    if (parsed < (long)min_val || parsed > (long)max_val) {
        return 0;
    }
    *out_val = (int)parsed;
    return 1;
}

NOINLINE int parola_kontrol(const char *girilen_parola, int yetki_seviyesi) {
    if (girilen_parola == NULL) {
        return 0;
    }
    if (strcmp(girilen_parola, EXPECTED_PASS) == 0 && yetki_seviyesi >= MIN_REQUIRED_LEVEL) {
        return 1;
    }
    return 0;
}

NOINLINE int check_password(const char *input, int level) {
    return parola_kontrol(input, level);
}

static void print_usage(const char *prog) {
    fprintf(
        stderr,
        "Usage: %s [--pass <str>] [--level <int>] [--iterations <1..1000>] [--interval-ms <0..60000>]\n",
        prog
    );
}

int main(int argc, char **argv) {
    const char *parola = DEFAULT_INPUT_PASS;
    int seviye = DEFAULT_ROLE_LEVEL;
    int iterations = DEFAULT_ITERATIONS;
    int interval_ms = DEFAULT_INTERVAL_MS;
    int i = 0;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--pass") == 0 && i + 1 < argc) {
            parola = argv[++i];
        } else if (strcmp(argv[i], "--level") == 0 && i + 1 < argc) {
            if (!parse_int_arg(argv[++i], INT_MIN, INT_MAX, &seviye)) {
                fprintf(stderr, "[HEDEF] invalid --level value\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--iterations") == 0 && i + 1 < argc) {
            if (!parse_int_arg(argv[++i], 1, 1000, &iterations)) {
                fprintf(stderr, "[HEDEF] invalid --iterations value (expected 1..1000)\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--interval-ms") == 0 && i + 1 < argc) {
            if (!parse_int_arg(argv[++i], 0, 60000, &interval_ms)) {
                fprintf(stderr, "[HEDEF] invalid --interval-ms value (expected 0..60000)\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "[HEDEF] unknown or incomplete option: %s\n", argv[i]);
            print_usage(argv[0]);
            return 2;
        }
    }

    for (i = 1; i <= iterations; i++) {
        int sonuc = parola_kontrol(parola, seviye);
        const char *durum = sonuc == 1 ? "ONAYLANDI" : "REDDEDILDI";
        printf(
            "[HEDEF] iter=%d/%d | girilen=\"%s\" | seviye=%d | sonuc=%d | durum=%s\n",
            i,
            iterations,
            parola,
            seviye,
            sonuc,
            durum
        );
        fflush(stdout);
        if (i < iterations && interval_ms > 0) {
            sleep_ms(interval_ms);
        }
    }

    return 0;
}
