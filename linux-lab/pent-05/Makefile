CC ?= cc
SCRIPTS := ../scripts

.PHONY: all audit fuzz clean

all: hedef-weak hedef-hardened

# Tum mitigationlar kapali: NX yok, PIE yok, canary yok, RELRO yok
hedef-weak: hedef.c
	$(CC) -O0 -g -fno-stack-protector -fno-pie -no-pie -z execstack -Wl,-z,norelro -o $@ $<

# Tum mitigationlar acik: NX, PIE, canary, full RELRO, FORTIFY
hedef-hardened: hedef.c
	$(CC) -O2 -g -fstack-protector-strong -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now -Wl,-z,noexecstack -o $@ $<

# hedef-hardened 0 ile gecmeli; hedef-weak tam olarak 1 (ZAYIF) donmeli.
# Arac hatasi (2) ya da beklenmeyen sonuc make'i basarisiz yapar.
audit: all
	$(SCRIPTS)/pent-05-hardening-audit.sh hedef-hardened
	$(SCRIPTS)/pent-05-hardening-audit.sh --no-aslr-check hedef-weak; rc=$$?; \
	  if [ $$rc -ne 1 ]; then echo "beklenmeyen cikis kodu: $$rc (beklenen 1)" >&2; exit 1; fi

fuzz:
	$(SCRIPTS)/pent-05-afl-triage.sh fuzz --seconds 60

clean:
	rm -f hedef-weak hedef-hardened
