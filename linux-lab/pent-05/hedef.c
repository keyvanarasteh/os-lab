/*
 * PENT-05 lab hedefi — BİLİNÇLİ OLARAK ZAFİYETLİ. Yalnızca lab içinde kullanın.
 *
 * Aynı kaynak iki şekilde derlenir (bkz. Makefile):
 *   hedef-weak      tüm mitigation'lar kapalı  -> denetimde ZAYIF
 *   hedef-hardened  tüm mitigation'lar açık    -> denetimde SAGLAM
 * ve AFL++ ile fuzz edilir (pent-05-afl-triage.sh fuzz).
 *
 * Girdi: argv[1] dosyası ya da stdin. Üç farklı crash yolu vardır:
 *   "PENT" + 16 bayttan uzun veri  -> stack buffer overflow (strcpy)
 *   "NULL!"                         -> NULL işaretçi yazımı (SIGSEGV)
 *   "DIV0" + tam 4 karakter         -> sıfıra bölme (SIGFPE)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void kopyala(const char *veri) {
    char kutu[16];
    strcpy(kutu, veri); /* uzunluk kontrolü yok: kasıtlı overflow */
    printf("kutu: %s\n", kutu);
}

static int bol(int a, const char *veri) {
    int b = (int)strlen(veri) - 4; /* "DIV0abcd" -> b == 0 */
    return a / b;
}

int main(int argc, char **argv) {
    char buf[256];
    FILE *fp = argc > 1 ? fopen(argv[1], "rb") : stdin;
    if (!fp) {
        perror("fopen");
        return 2;
    }
    size_t n = fread(buf, 1, sizeof(buf) - 1, fp);
    if (fp != stdin)
        fclose(fp);
    buf[n] = '\0';
    buf[strcspn(buf, "\n")] = '\0';

    if (strncmp(buf, "PENT", 4) == 0) {
        kopyala(buf + 4);
    } else if (strncmp(buf, "NULL", 4) == 0) {
        volatile int *p = NULL;
        if (buf[4] == '!')
            *p = 1;
    } else if (strncmp(buf, "DIV0", 4) == 0) {
        printf("%d\n", bol(100, buf + 4));
    } else {
        puts("normal girdi");
    }
    return 0;
}
