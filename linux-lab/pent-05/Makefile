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

# hedef-weak ZAYIF cikacagi icin cikis kodu 1 olur; bu beklenen sonuctur.
audit: all
	-$(SCRIPTS)/pent-05-hardening-audit.sh hedef-weak hedef-hardened

fuzz:
	$(SCRIPTS)/pent-05-afl-triage.sh fuzz --seconds 60

clean:
	rm -f hedef-weak hedef-hardened
