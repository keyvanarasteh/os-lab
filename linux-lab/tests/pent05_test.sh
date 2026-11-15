#!/usr/bin/env bash
# PENT-05 çevrimdışı testleri: sahte readelf ve sahte crash hedefiyle çalışır,
# gerçek derleyici, binutils ya da AFL++ gerektirmez.
#   bash linux-lab/tests/pent05_test.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/../scripts"
FIX="$HERE/fixtures/pent05"
AUDIT="$SCRIPTS/pent-05-hardening-audit.sh"
TRIAGE="$SCRIPTS/pent-05-afl-triage.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for n in weak hardened partial lib notelf; do : >"$TMP/$n"; done
printf '2\n' >"$TMP/aslr2"; printf '0\n' >"$TMP/aslr0"

export PENT05_READELF="$FIX/fake-readelf.sh"
export PENT05_ASLR_FILE="$TMP/aslr2"

PASS=0; FAIL=0
check() { # check <ad> <beklenen-çıkış> <beklenen-metin|-> <komut...>
  local name="$1" want_rc="$2" want_txt="$3"; shift 3
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" != "$want_rc" ]; then
    echo "FAIL $name: çıkış $rc, beklenen $want_rc"; echo "$out" | sed 's/^/    /'; FAIL=$((FAIL + 1)); return
  fi
  if [ "$want_txt" != "-" ] && ! grep -qF -- "$want_txt" <<<"$out"; then
    echo "FAIL $name: '$want_txt' çıktıda yok"; echo "$out" | sed 's/^/    /'; FAIL=$((FAIL + 1)); return
  fi
  echo "ok   $name"; PASS=$((PASS + 1))
}

# --- Hardening denetimi -----------------------------------------------------
check "hardened ikili SAGLAM"            0 "SAGLAM"            bash "$AUDIT" "$TMP/hardened"
check "weak ikili ZAYIF"                 1 "ZAYIF"             bash "$AUDIT" "$TMP/weak"
check "weak: NX önerisi"                 1 "noexecstack"       bash "$AUDIT" "$TMP/weak"
check "weak: canary önerisi"             1 "stack-protector"   bash "$AUDIT" "$TMP/weak"
check "weak JSON alanları"               1 '"nx":false,"pie":"no","canary":false,"relro":"none","fortify_functions":0,"verdict":"weak","missing":["nx","pie","canary","relro"]' \
                                                               bash "$AUDIT" --json "$TMP/weak"
check "hardened JSON alanları"           0 '"nx":true,"pie":"yes","canary":true,"relro":"full","fortify_functions":3,"verdict":"hardened","missing":[]' \
                                                               bash "$AUDIT" --json "$TMP/hardened"
check "partial RELRO zayıf sayılır"      1 '"relro":"partial"' bash "$AUDIT" --json "$TMP/partial"
check "paylaşımlı kütüphane = dso"       0 '"pie":"dso"'       bash "$AUDIT" --json "$TMP/lib"
check "karışık liste: weak sayısı"       1 '"weak":2,"errors":0' bash "$AUDIT" --json "$TMP/hardened" "$TMP/weak" "$TMP/partial"
check "ELF olmayan dosya hata"           2 "ELF dosyası değil" bash "$AUDIT" "$TMP/notelf"
check "olmayan dosya hata"               2 "dosya bulunamadı"  bash "$AUDIT" "$TMP/yok"
check "argümansız kullanım hatası"       2 "Kullanım"          bash "$AUDIT"
check "bilinmeyen seçenek"               2 "bilinmeyen"        bash "$AUDIT" --xyz "$TMP/weak"
check "readelf yoksa hata"               2 "bulunamadı"        env PENT05_READELF=/yok/readelf bash "$AUDIT" "$TMP/weak"
check "ASLR kapalı -> çıkış 1"           1 "ASLR kapalı"       env PENT05_ASLR_FILE="$TMP/aslr0" bash "$AUDIT" "$TMP/hardened"
check "ASLR okunamazsa unknown"          0 '"aslr":"unknown"'  env PENT05_ASLR_FILE="$TMP/yok" bash "$AUDIT" --json "$TMP/hardened"

# --- Crash triage -----------------------------------------------------------
C="$TMP/crashes"; mkdir -p "$C"
printf 'SEGV-1' >"$C/id:000000"; printf 'SEGV-2' >"$C/id:000001"
printf 'ABRT'   >"$C/id:000002"; printf 'ASAN'   >"$C/id:000003"
printf 'ASAN-b' >"$C/id:000004"; printf 'tamam'  >"$C/id:000005"
printf 'HANG'   >"$C/id:000006"; printf 'AFL notu' >"$C/README.txt"
TGT="$FIX/fake-target.sh"

check "triage: girdi/bucket sayısı"      0 '"inputs":7,"buckets":5,"unique_crashes":4' \
                                                               bash "$TRIAGE" triage --json --timeout 2 "$C" -- bash "$TGT" @@
check "triage: SEGV gruplanır"           0 '{"count":2,"kind":"signal:SIGSEGV"' \
                                                               bash "$TRIAGE" triage --json --timeout 2 "$C" -- bash "$TGT" @@
check "triage: ASAN türü + çerçeve"      0 '"kind":"asan:stack-buffer-overflow","frames":"kopyala<main"' \
                                                               bash "$TRIAGE" triage --json --timeout 2 "$C" -- bash "$TGT" @@
check "triage: hang tespiti"             0 '"kind":"hang"'     bash "$TRIAGE" triage --json --timeout 2 "$C" -- bash "$TGT" @@
check "triage: SIGABRT"                  0 '"kind":"signal:SIGABRT"' bash "$TRIAGE" triage --json --timeout 2 "$C" -- bash "$TGT" @@
check "triage: stdin modu (@@ yok)"      0 "signal:SIGSEGV"    bash "$TRIAGE" triage --timeout 2 "$C" -- bash "$TGT"
check "triage: metin tablo"              0 "7 dosya -> 5 bucket (4 benzersiz crash)" \
                                                               bash "$TRIAGE" triage --timeout 2 "$C" -- bash "$TGT" @@
check "triage: dizin yoksa hata"         2 "crash dizini yok"  bash "$TRIAGE" triage "$TMP/yok" -- bash "$TGT" @@
check "triage: komut yoksa hata"         2 "hedef komut"       bash "$TRIAGE" triage "$C"
check "fuzz: AFL++ yoksa skip"           0 "[skip]"            env PENT05_AFL_FUZZ=/yok/afl-fuzz bash "$TRIAGE" fuzz --seconds 1
check "fuzz: geçersiz süre"              2 "pozitif"           bash "$TRIAGE" fuzz --seconds abc
check "alt komutsuz kullanım"            2 "Kullanım"          bash "$TRIAGE"

echo
echo "PENT-05: $PASS geçti, $FAIL başarısız"
[ "$FAIL" -eq 0 ]
