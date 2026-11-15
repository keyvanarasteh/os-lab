#!/usr/bin/env bash
# PENT-05 — Binary hardening verification (readelf tabanlı mitigation denetimi)
#
# Kullanım:
#   pent-05-hardening-audit.sh [--json] [--no-aslr-check] <ELF dosyası>...
#   pent-05-hardening-audit.sh -h|--help
#
# İkili başına kontroller:
#   NX       GNU_STACK segmenti çalıştırılabilir değil (RW, RWE değil)
#   PIE      ELF tipi DYN + (INTERP ya da FLAGS_1 PIE); paylaşımlı kütüphane = dso
#   CANARY   __stack_chk_fail sembolü var (-fstack-protector*)
#   RELRO    GNU_RELRO + BIND_NOW = full, yalnız GNU_RELRO = partial, hiçbiri = none
#   FORTIFY  __*_chk sembolleri var (-D_FORTIFY_SOURCE) [bilgi amaçlı, sonucu etkilemez]
# Sistem kontrolü (--no-aslr-check ile atlanır):
#   ASLR     /proc/sys/kernel/randomize_va_space; yalnız 2 (full) geçer
#
# Çıkış kodu: 0 = hepsi sağlam, 1 = zayıflık ya da ASLR tam değil, 2 = kullanım/dosya/araç hatası
# Ortam: PENT05_READELF (varsayılan: readelf), PENT05_ASLR_FILE (testler için)
set -euo pipefail

READELF="${PENT05_READELF:-readelf}"
ASLR_FILE="${PENT05_ASLR_FILE:-/proc/sys/kernel/randomize_va_space}"

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

JSON=0
ASLR_CHECK=1
FILES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON=1 ;;
    --no-aslr-check) ASLR_CHECK=0 ;;
    -h|--help) usage; exit 0 ;;
    --) shift; FILES+=("$@"); break ;;
    -*) echo "bilinmeyen seçenek: $1" >&2; usage >&2; exit 2 ;;
    *) FILES+=("$1") ;;
  esac
  shift
done

if [ "${#FILES[@]}" -eq 0 ]; then usage >&2; exit 2; fi
if ! command -v "$READELF" >/dev/null 2>&1; then
  echo "hata: '$READELF' bulunamadı (Debian/Ubuntu: sudo apt install binutils)" >&2
  exit 2
fi

# Dört readelf çağrısı aynı içeriği görsün diye her ikili önce buraya kopyalanır.
SNAPDIR="$(mktemp -d)"
trap 'rm -rf "$SNAPDIR"' EXIT

aslr_state() {
  local v
  if [ -r "$ASLR_FILE" ]; then
    v="$(tr -d '[:space:]' < "$ASLR_FILE")"
    case "$v" in
      2) echo full ;; 1) echo partial ;; 0) echo off ;; *) echo unknown ;;
    esac
  else
    echo unknown
  fi
}

# JSON string: ters bölü, tırnak ve tüm kontrol karakterleri kaçışlanır.
json_str() {
  local s="$1" out="" c i code
  for ((i = 0; i < ${#s}; i++)); do
    c="${s:i:1}"
    case "$c" in
      '\') out+='\\' ;;
      '"') out+='\"' ;;
      $'\n') out+='\n' ;;
      $'\r') out+='\r' ;;
      $'\t') out+='\t' ;;
      *)
        printf -v code '%d' "'$c" 2>/dev/null || code=32
        if [ "$code" -ge 0 ] && [ "$code" -lt 32 ]; then printf -v c '\\u%04x' "$code"; fi
        out+="$c" ;;
    esac
  done
  printf '"%s"' "$out"
}

# Ekranda kontrol karakterlerini görünür kıl (satır kaydırmasın).
show_name() { local n; n="$(basename -- "$1")"; printf '%s' "${n//[[:cntrl:]]/?}"; }

# Sonuçlar ayraçla birleştirilmeden paralel dizilerde tutulur.
A_FILE=(); A_ERR=(); A_TYPE=(); A_NX=(); A_PIE=(); A_CANARY=(); A_RELRO=(); A_FORTIFY=(); A_VERDICT=(); A_MISSING=()

# audit_one <dosya> — sonuçları R_* değişkenlerine yazar
audit_one() {
  local f="$1" snap hdr prog dyn syms stack
  R_ERR=""; R_TYPE=""; R_NX=no; R_PIE=no; R_CANARY=no; R_RELRO=none
  R_FORTIFY=0; R_MISSING=()

  if [ ! -f "$f" ]; then R_ERR="dosya bulunamadı"; return 0; fi
  snap="$SNAPDIR/$(basename -- "$f")"
  if ! cp -- "$f" "$snap" 2>/dev/null; then R_ERR="dosya okunamadı"; return 0; fi
  if ! hdr="$("$READELF" -h -W "$snap" 2>/dev/null)"; then R_ERR="ELF dosyası değil"; rm -f -- "$snap"; return 0; fi
  prog="$("$READELF" -l -W "$snap" 2>/dev/null || true)"
  dyn="$("$READELF" -d -W "$snap" 2>/dev/null || true)"
  syms="$("$READELF" -s -W "$snap" 2>/dev/null || true)"
  rm -f -- "$snap"

  R_TYPE="$(awk -F: '/^ *Type:/{gsub(/^ +/, "", $2); split($2, a, " "); print a[1]; exit}' <<<"$hdr")"

  # NX: GNU_STACK yoksa çoğu mimaride yığın çalıştırılabilir kabul edilir.
  stack="$(awk '$1 == "GNU_STACK" {print; exit}' <<<"$prog")"
  case "$stack" in
    "") R_NX=no ;;
    *RWE*) R_NX=no ;;
    *) R_NX=yes ;;
  esac

  # PIE: DYN + INTERP = dinamik PIE; INTERP yoksa FLAGS_1 içinde PIE varsa static-pie,
  # yoksa paylaşımlı kütüphane (dso).
  case "$R_TYPE" in
    DYN)
      if awk '$1 == "INTERP" {f = 1} END {exit !f}' <<<"$prog"; then R_PIE=yes
      elif grep -qE '\(FLAGS_1\).*Flags:.*\bPIE\b' <<<"$dyn"; then R_PIE=yes
      else R_PIE=dso; fi ;;
    *) R_PIE=no ;;
  esac

  if awk '$1 == "GNU_RELRO" {f = 1} END {exit !f}' <<<"$prog"; then
    if grep -qE '\(BIND_NOW\)|\(FLAGS\).*BIND_NOW|Flags:.*\bNOW\b' <<<"$dyn"; then R_RELRO=full; else R_RELRO=partial; fi
  fi

  if grep -qE '__stack_chk_fail|__stack_chk_guard|__intel_security_cookie' <<<"$syms"; then R_CANARY=yes; fi

  R_FORTIFY="$( (grep -oE '__[a-z0-9_]+_chk\b' <<<"$syms" || true) | sort -u | wc -l | tr -d ' ')"

  [ "$R_NX" = yes ] || R_MISSING+=("nx")
  [ "$R_PIE" = no ] && R_MISSING+=("pie")
  [ "$R_CANARY" = yes ] || R_MISSING+=("canary")
  [ "$R_RELRO" = full ] || R_MISSING+=("relro")
  return 0
}

advice() {
  case "$1" in
    nx)     echo "NX kapalı: yığın çalıştırılabilir. Düzeltme: -Wl,-z,noexecstack (execstack kullanmayın)" ;;
    pie)    echo "PIE yok: kod segmenti sabit adreste, ROP kolaylaşır. Düzeltme: -fPIE -pie" ;;
    canary) echo "Stack canary yok: yığın taşması fark edilmez. Düzeltme: -fstack-protector-strong" ;;
    relro)  echo "RELRO tam değil: GOT üzerine yazılabilir. Düzeltme: -Wl,-z,relro,-z,now" ;;
  esac
}

ASLR="$(aslr_state)"
WEAK=0; ERRORS=0

for f in "${FILES[@]}"; do
  audit_one "$f"
  if [ -n "$R_ERR" ]; then
    ERRORS=$((ERRORS + 1)); verdict=error
  elif [ "${#R_MISSING[@]}" -gt 0 ]; then
    WEAK=$((WEAK + 1)); verdict=weak
  else
    verdict=hardened
  fi
  A_FILE+=("$f"); A_ERR+=("$R_ERR"); A_TYPE+=("$R_TYPE"); A_NX+=("$R_NX"); A_PIE+=("$R_PIE")
  A_CANARY+=("$R_CANARY"); A_RELRO+=("$R_RELRO"); A_FORTIFY+=("$R_FORTIFY"); A_VERDICT+=("$verdict")
  A_MISSING+=("${R_MISSING[*]:-}")
done

ASLR_FAIL=0
if [ "$ASLR_CHECK" = 1 ] && [ "$ASLR" != full ]; then ASLR_FAIL=1; fi

if [ "$JSON" = 1 ]; then
  printf '{"tool":"pent-05-hardening-audit","aslr":"%s","aslr_checked":%s,"binaries":[' \
    "$ASLR" "$([ "$ASLR_CHECK" = 1 ] && echo true || echo false)"
  for i in "${!A_FILE[@]}"; do
    [ "$i" -gt 0 ] && printf ','
    printf '{"file":%s,' "$(json_str "${A_FILE[$i]}")"
    if [ "${A_VERDICT[$i]}" = error ]; then
      printf '"verdict":"error","error":%s}' "$(json_str "${A_ERR[$i]}")"
    else
      printf '"elf_type":%s,"nx":%s,"pie":"%s","canary":%s,"relro":"%s","fortify_functions":%s,"verdict":"%s","missing":[' \
        "$(json_str "${A_TYPE[$i]}")" "$([ "${A_NX[$i]}" = yes ] && echo true || echo false)" "${A_PIE[$i]}" \
        "$([ "${A_CANARY[$i]}" = yes ] && echo true || echo false)" "${A_RELRO[$i]}" "${A_FORTIFY[$i]}" "${A_VERDICT[$i]}"
      msep=""
      for m in ${A_MISSING[$i]}; do printf '%s"%s"' "$msep" "$m"; msep=","; done
      printf ']}'
    fi
  done
  printf '],"weak":%d,"errors":%d}\n' "$WEAK" "$ERRORS"
else
  echo "PENT-05 Binary Hardening Denetimi"
  echo "Sistem ASLR (randomize_va_space): $ASLR$([ "$ASLR_CHECK" = 1 ] || echo ' (kontrol atlandı)')"
  echo
  printf '%-28s %-6s %-6s %-7s %-8s %-8s %s\n' DOSYA NX PIE CANARY RELRO FORTIFY SONUC
  for i in "${!A_FILE[@]}"; do
    name="$(show_name "${A_FILE[$i]}")"
    if [ "${A_VERDICT[$i]}" = error ]; then
      printf '%-28s HATA: %s\n' "$name" "${A_ERR[$i]}"
      continue
    fi
    case "${A_VERDICT[$i]}" in hardened) v=SAGLAM ;; *) v=ZAYIF ;; esac
    printf '%-28s %-6s %-6s %-7s %-8s %-8s %s\n' "$name" "${A_NX[$i]}" "${A_PIE[$i]}" "${A_CANARY[$i]}" "${A_RELRO[$i]}" "${A_FORTIFY[$i]}" "$v"
  done
  for i in "${!A_FILE[@]}"; do
    [ "${A_VERDICT[$i]}" = weak ] || continue
    echo
    echo "[$(show_name "${A_FILE[$i]}")]"
    for m in ${A_MISSING[$i]}; do echo "  - $(advice "$m")"; done
    if [ "${A_FORTIFY[$i]}" = 0 ]; then echo "  - (bilgi) FORTIFY yok: -O2 -D_FORTIFY_SOURCE=2 ile derleyin"; fi
  done
  if [ "$ASLR_CHECK" = 1 ]; then
    case "$ASLR" in
      off) echo; echo "[sistem] ASLR kapalı. Düzeltme: sudo sysctl -w kernel.randomize_va_space=2" ;;
      partial) echo; echo "[sistem] ASLR kısmi (heap rastgele değil). Düzeltme: sudo sysctl -w kernel.randomize_va_space=2" ;;
      unknown) echo; echo "[sistem] ASLR durumu doğrulanamadı (Linux dışı sistem ya da /proc yok). Yalnız ikilileri denetlemek için: --no-aslr-check" ;;
    esac
  fi
fi

if [ "$ERRORS" -gt 0 ]; then exit 2; fi
if [ "$WEAK" -gt 0 ] || [ "$ASLR_FAIL" = 1 ]; then exit 1; fi
exit 0
