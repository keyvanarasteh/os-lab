#!/usr/bin/env bash
# Sahte fuzz hedefi: girdi içeriğine göre farklı şekilde çöker.
if [ $# -gt 0 ]; then data="$(cat "$1")"; else data="$(cat)"; fi
case "$data" in
  SEGV*) kill -SEGV $$ ;;
  ABRT*) kill -ABRT $$ ;;
  HANG*) sleep 10 ;;
  INATCI*) trap '' TERM; sleep 10 ;;
  E124*) exit 124 ;;
  ASANCPP*)
    cat >&2 <<'R'
==7==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x6020 at pc 0x4f3 bp 0x7ff sp 0x7fe
    #0 0x4f3c1a in __asan_memcpy (/lib/libasan.so.8+0x4f3c1a)
    #1 0x5a1b22 in operator new(unsigned long) (/lib/libstdc++.so.6+0x1b22)
    #2 0x5a1c90 in Kutu::doldur(char const*, int) /lab/kutu.cc:12:3
    #3 0x5a1d00 in main /lab/kutu.cc:30:5
R
    exit 1 ;;
  ASAN*)
    cat >&2 <<'R'
==4242==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x7ffd1 at pc 0x4f3 bp 0x7ff sp 0x7fe
WRITE of size 40 at 0x7ffd1 thread T0
    #0 0x4f3c1a in __interceptor_strcpy (/lab/hedef-afl+0x4f3c1a)
    #1 0x5a1b22 in kopyala /lab/hedef.c:21:5
    #2 0x5a1c90 in main /lab/hedef.c:44:9
    #3 0x7f00aa in __libc_start_main (/lib/libc.so.6+0x2d0)
SUMMARY: AddressSanitizer: stack-buffer-overflow /lab/hedef.c:21:5 in kopyala
R
    exit 1 ;;
  *) echo "normal girdi" ;;
esac
