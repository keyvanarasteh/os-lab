#!/usr/bin/env bash
# PENT-05 çevrimdışı testleri: sahte readelf ve sahte crash hedefiyle çalışır,
# gerçek derleyici, binutils ya da AFL++ gerektirmez.
#   bash linux-lab/tests/pent05_test.sh
# python3 ya da jq varsa --json çıktılarının geçerli JSON olduğu da doğrulanır.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/../scripts"
FIX="$HERE/fixtures/pent05"
AUDIT="$SCRIPTS/pent-05-hardening-audit.sh"
TRIAGE="$SCRIPTS/pent-05-afl-triage.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for n in weak hardened partial lib staticpie notelf; do : >"$TMP/$n"; done
printf '2\n' >"$TMP/aslr2"; printf '1\n' >"$TMP/aslr1"; printf '0\n' >"$TMP/aslr0"

export PENT05_READELF="$FIX/fake-readelf.sh"
export PENT05_ASLR_FILE="$TMP/aslr2"

JSON_CHECK=""
if command -v python3 >/dev/null 2>&1 && python3 -c 'import json' >/dev/null 2>&1; then
  JSON_CHECK="python3 -c 'import json,sys; json.load(sys.stdin)'"
elif command -v jq >/dev/null 2>&1; then
  JSON_CHECK="jq -e . >/dev/null"
fi

PASS=0; FAIL=0; SKIPPED=0
# check <ad> <beklenen-çıkış> <beklenen-metin|-> <komut...>   (stdout+stderr birlikte)
check() {
  local name="$1" want_rc="$2" want_txt="$3"; shift 3
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  verdict "$name" "$want_rc" "$want_txt" "$rc" "$out"
}
# check_stdout: yalnız stdout incelenir (JSON'un temiz olduğunu doğrulamak için)
check_stdout() {
  local name="$1" want_rc="$2" want_txt="$3"; shift 3
  local out rc
  out="$("$@" 2>/dev/null)"; rc=$?
  verdict "$name" "$want_rc" "$want_txt" "$rc" "$out"
}
verdict() {
  local name="$1" want_rc="$2" want_txt="$3" rc="$4" out="$5"
  if [ "$rc" != "$want_rc" ]; then
    echo "FAIL $name: çıkış $rc, beklenen $want_rc"; echo "$out" | sed 's/^/    /'; FAIL=$((FAIL + 1)); return
  fi
  if [ "$want_txt" = "<empty>" ]; then
    if [ -n "$out" ]; then echo "FAIL $name: stdout boş olmalıydı"; echo "$out" | sed 's/^/    /'; FAIL=$((FAIL + 1)); return; fi
  elif [ "$want_txt" != "-" ] && ! grep -qF -- "$want_txt" <<<"$out"; then
    echo "FAIL $name: '$want_txt' çıktıda yok"; echo "$out" | sed 's/^/    /'; FAIL=$((FAIL + 1)); return
  fi
  echo "ok   $name"; PASS=$((PASS + 1))
}
# check_json <ad> <komut...> — stdout tek ve geçerli bir JSON belgesi olmalı
check_json() {
  local name="$1"; shift
  if [ -z "$JSON_CHECK" ]; then echo "skip $name (python3/jq yok)"; SKIPPED=$((SKIPPED + 1)); return; fi
  # The tool may exit non-zero on purpose (missing file -> 2); only the JSON is judged here,
  # so pipefail must not turn that exit code into a failure.
  if { "$@" 2>/dev/null || true; } | eval "$JSON_CHECK"; then echo "ok   $name"; PASS=$((PASS + 1))
  else echo "FAIL $name: geçersiz JSON"; FAIL=$((FAIL + 1)); fi
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
check "static PIE = pie yes (dso değil)" 0 '"pie":"yes"'       bash "$AUDIT" --json "$TMP/staticpie"
check "karışık liste: weak sayısı"       1 '"weak":2,"errors":0' bash "$AUDIT" --json "$TMP/hardened" "$TMP/weak" "$TMP/partial"
check "ELF olmayan dosya hata"           2 "ELF dosyası değil" bash "$AUDIT" "$TMP/notelf"
check "olmayan dosya hata"               2 "dosya bulunamadı"  bash "$AUDIT" "$TMP/yok"
check "argümansız kullanım hatası"       2 "Kullanım"          bash "$AUDIT"
check "bilinmeyen seçenek"               2 "bilinmeyen"        bash "$AUDIT" --xyz "$TMP/weak"
check "readelf yoksa hata"               2 "bulunamadı"        env PENT05_READELF=/yok/readelf bash "$AUDIT" "$TMP/weak"
check "ASLR kapalı -> çıkış 1"           1 "ASLR kapalı"       env PENT05_ASLR_FILE="$TMP/aslr0" bash "$AUDIT" "$TMP/hardened"
check "ASLR kısmi -> çıkış 1"            1 "ASLR kısmi"        env PENT05_ASLR_FILE="$TMP/aslr1" bash "$AUDIT" "$TMP/hardened"
check "ASLR okunamazsa çıkış 1"          1 '"aslr":"unknown"'  env PENT05_ASLR_FILE="$TMP/yok" bash "$AUDIT" --json "$TMP/hardened"
check "--no-aslr-check ile ASLR atlanır" 0 '"aslr_checked":false' env PENT05_ASLR_FILE="$TMP/yok" bash "$AUDIT" --json --no-aslr-check "$TMP/hardened"
check "özel karakterli ad JSON'da kaçışlanır" 2 '"file":"'"$TMP"'/a|b\tc\nd\"e"' bash "$AUDIT" --json "$TMP/a|b"$'\t'"c"$'\n'"d\"e"
check_json "audit JSON geçerli (karışık)"      bash "$AUDIT" --json "$TMP/hardened" "$TMP/weak" "$TMP/lib" "$TMP/yok"
check_json "audit JSON geçerli (özel ad)"      bash "$AUDIT" --json "$TMP/a|b"$'\t'"c"$'\n'"d\"e"

# --- Crash triage -----------------------------------------------------------
C="$TMP/crashes"; mkdir -p "$C"
printf 'SEGV-1' >"$C/id-000"; printf 'SEGV-2' >"$C/id-001"
printf 'ABRT'   >"$C/id-002"; printf 'ASAN'   >"$C/id-003"
printf 'ASAN-b' >"$C/id-004"; printf 'tamam'  >"$C/id-005"
printf 'HANG'   >"$C/id-006"; printf 'E124'   >"$C/id-007"
printf 'ASANCPP' >"$C/id-008"; printf 'AFL notu' >"$C/README.txt"
TGT="$FIX/fake-target.sh"
T=(bash "$TRIAGE" triage --json --timeout 1 "$C" -- bash "$TGT" @@)

TRIAGE_JSON="$("${T[@]}" 2>/dev/null)"
check "triage: girdi/bucket sayısı"      0 '"inputs":9,"buckets":7,"unique_crashes":5' printf '%s' "$TRIAGE_JSON"
check "triage: SEGV gruplanır"           0 '{"count":2,"kind":"signal:SIGSEGV"' printf '%s' "$TRIAGE_JSON"
check "triage: ASAN türü + çerçeve"      0 '"kind":"asan:stack-buffer-overflow","frames":"kopyala<main"' printf '%s' "$TRIAGE_JSON"
check "triage: C++ çerçeve adı tam"      0 '"frames":"operator new(unsigned long)<Kutu::doldur(char const*, int)"' printf '%s' "$TRIAGE_JSON"
check "triage: hang tespiti"             0 '"kind":"hang"'     printf '%s' "$TRIAGE_JSON"
check "triage: SIGABRT"                  0 '"kind":"signal:SIGABRT"' printf '%s' "$TRIAGE_JSON"
check "triage: normal girdi no-crash"    0 '"kind":"no-crash","frames":"-","example":"'"$C"'/id-005"' printf '%s' "$TRIAGE_JSON"
check "triage: exit 124 hang sayılmaz"   0 '"kind":"exit:124"' printf '%s' "$TRIAGE_JSON"
check_json "triage JSON geçerli"         "${T[@]}"

S="$TMP/inatci"; mkdir -p "$S"; printf 'INATCI' >"$S/id-000"
START=$SECONDS
check "triage: TERM'i yok sayan hedef öldürülür" 0 '"kind":"hang"' bash "$TRIAGE" triage --json --timeout 1 "$S" -- bash "$TGT" @@
if [ $((SECONDS - START)) -le 8 ]; then echo "ok   triage: inatçı hedef süre sınırında bitti"; PASS=$((PASS + 1))
else echo "FAIL triage: inatçı hedef $((SECONDS - START)) sn sürdü"; FAIL=$((FAIL + 1)); fi

W="$TMP/garip"; mkdir -p "$W"; printf 'SEGV' >"$W/a|b"$'\t'"c"
check "triage: tab içeren dosya adı"     0 '"inputs":1,"buckets":1' bash "$TRIAGE" triage --json --timeout 1 "$W" -- bash "$TGT" @@
check_json "triage JSON geçerli (özel ad)"     bash "$TRIAGE" triage --json --timeout 1 "$W" -- bash "$TGT" @@

check "triage: stdin modu (@@ yok)"      0 "signal:SIGSEGV"    bash "$TRIAGE" triage --timeout 1 "$C" -- bash "$TGT"
check "triage: metin tablo"              0 "9 dosya -> 7 bucket (5 benzersiz crash)" \
                                                               bash "$TRIAGE" triage --timeout 1 "$C" -- bash "$TGT" @@
check "triage: dizin yoksa hata"         2 "crash dizini yok"  bash "$TRIAGE" triage "$TMP/yok" -- bash "$TGT" @@
check "triage: komut yoksa hata"         2 "hedef komut"       bash "$TRIAGE" triage "$C"
check "triage: çalışmayan hedef hata"    2 "çalıştırılamıyor"  bash "$TRIAGE" triage "$C" -- /yok/hedef @@
check "triage: --timeout 0 reddedilir"   2 "pozitif"           bash "$TRIAGE" triage --timeout 0 "$C" -- bash "$TGT" @@
check "fuzz: AFL++ yoksa skip"           0 "[skip]"            env PENT05_AFL_FUZZ=/yok/afl-fuzz bash "$TRIAGE" fuzz --seconds 1
check_stdout "fuzz --json: stdout'a metin yazılmaz" 0 "<empty>" env PENT05_AFL_FUZZ=/yok/afl-fuzz bash "$TRIAGE" fuzz --json --seconds 1
check "fuzz: geçersiz süre"              2 "pozitif"           bash "$TRIAGE" fuzz --seconds abc
check "alt komutsuz kullanım"            2 "Kullanım"          bash "$TRIAGE"

echo
echo "PENT-05: $PASS geçti, $FAIL başarısız, $SKIPPED atlandı"
[ "$FAIL" -eq 0 ]
