#!/usr/bin/env bash
# PENT-05 — AFL++ crash triage smoke runner
#
# Kullanım:
#   pent-05-afl-triage.sh fuzz   [--seconds N] [--out DİZİN] [--src HEDEF.c] [--json]
#   pent-05-afl-triage.sh triage [--timeout S] [--json] <crash-dizini> -- <komut> [arg|@@ ...]
#   pent-05-afl-triage.sh -h|--help
#
# fuzz:   hedefi afl-cc + ASAN ile derler, afl-fuzz'u N saniye (varsayılan 60) çalıştırır ve
#         bulunan crash'leri otomatik triage eder. afl-fuzz/afl-cc yoksa [skip] yazar, 0 döner.
# triage: crash dizinindeki her girdiyi hedefe yeniden verir (@@ varsa dosya yolu olarak,
#         yoksa stdin'den) ve sonucu sınıflandırır: ASAN hata türü + üst çerçeveler, sinyal
#         (SIGSEGV, SIGABRT, SIGFPE...), zaman aşımı (hang) ya da no-crash. Aynı sınıftaki
#         girdiler tek bir bucket'ta toplanır; benzersiz crash'ler listelenir.
#
# Çıkış kodu: 0 = çalıştı (crash bulunsa da), 2 = kullanım/araç hatası
# Ortam: PENT05_AFL_FUZZ, PENT05_AFL_CC (araç yolları), ASAN_OPTIONS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$SCRIPT_DIR/../pent-05"

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "hata: $*" >&2; exit 2; }

export ASAN_OPTIONS="${ASAN_OPTIONS:-abort_on_error=1:symbolize=1:detect_leaks=0}"

json_str() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"
  printf '"%s"' "$s"
}

# classify <girdi> <timeout> <komut...> — "tür<TAB>çerçeveler" yazar
classify() {
  local input="$1" tmo="$2"; shift 2
  local -a cmd=()
  local a used=0 out rc kind frames sig
  for a in "$@"; do
    if [ "$a" = "@@" ]; then cmd+=("$input"); used=1; else cmd+=("$a"); fi
  done
  set +e
  if [ "$used" = 1 ]; then
    out="$(timeout "$tmo" "${cmd[@]}" 2>&1 </dev/null)"; rc=$?
  else
    out="$(timeout "$tmo" "${cmd[@]}" 2>&1 <"$input")"; rc=$?
  fi
  set -e

  frames="-"
  if grep -q 'ERROR: AddressSanitizer' <<<"$out"; then
    kind="asan:$(awk '/ERROR: AddressSanitizer:/ {for (i = 1; i <= NF; i++) if ($i == "AddressSanitizer:") {print $(i+1); exit}}' <<<"$out")"
    # İlk iki uygulama çerçevesi (ASAN/interceptor çerçeveleri atlanır) = yığın imzası
    frames="$(awk '/^ *#[0-9]+ 0x[0-9a-fA-F]+ in / {
        f = $4
        if (f ~ /^(__interceptor_|___interceptor_|__asan|__sanitizer|__libc_start)/) next
        s = (n ? s "<" : "") f; if (++n == 2) exit
      } END { print (n ? s : "-") }' <<<"$out")"
  elif [ "$rc" -eq 124 ]; then
    kind="hang"
  elif [ "$rc" -gt 128 ]; then
    sig="$(kill -l $((rc - 128)) 2>/dev/null || echo $((rc - 128)))"
    kind="signal:SIG${sig#SIG}"
  elif [ "$rc" -ne 0 ]; then
    kind="exit:$rc"
  else
    kind="no-crash"
  fi
  printf '%s\t%s\n' "$kind" "$frames"
}

# triage <crash-dizini> <timeout> <json 0|1> <komut...>
triage() {
  local dir="$1" tmo="$2" json="$3"; shift 3
  [ -d "$dir" ] || die "crash dizini yok: $dir"
  local tsv f total=0
  tsv="$(mktemp)"
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in README.txt|.*) continue ;; esac
    printf '%s\t%s\n' "$(classify "$f" "$tmo" "$@")" "$f" >>"$tsv"
    total=$((total + 1))
  done

  # Grupla: tür+çerçeve → adet ve ilk örnek
  local grouped
  grouped="$(awk -F'\t' '{k = $1 "\t" $2; if (!(k in c)) {o[++n] = k; ex[k] = $3}; c[k]++}
    END {for (i = 1; i <= n; i++) print c[o[i]] "\t" o[i] "\t" ex[o[i]]}' "$tsv" | sort -t"$(printf '\t')" -k1,1nr)"
  rm -f "$tsv"
  local buckets=0 crashes=0
  if [ -n "$grouped" ]; then
    buckets="$(wc -l <<<"$grouped" | tr -d ' ')"
    crashes="$(awk -F'\t' '$2 != "no-crash" && $2 !~ /^exit:/ {n++} END {print n + 0}' <<<"$grouped")"
  fi

  if [ "$json" = 1 ]; then
    printf '{"tool":"pent-05-afl-triage","inputs":%d,"buckets":%d,"unique_crashes":%d,"groups":[' "$total" "$buckets" "$crashes"
    local sep="" count kind frames example
    while IFS=$'\t' read -r count kind frames example; do
      [ -n "$count" ] || continue
      printf '%s{"count":%d,"kind":%s,"frames":%s,"example":%s}' "$sep" "$count" \
        "$(json_str "$kind")" "$(json_str "$frames")" "$(json_str "$example")"
      sep=","
    done <<<"$grouped"
    printf ']}\n'
  else
    echo "PENT-05 AFL++ Crash Triage"
    echo "Hedef : $*"
    echo "Girdi : $total dosya -> $buckets bucket ($crashes benzersiz crash)"
    echo
    printf '%-3s %-5s %-30s %-24s %s\n' "#" ADET TUR CERCEVE ORNEK
    local i=0 count kind frames example
    while IFS=$'\t' read -r count kind frames example; do
      [ -n "$count" ] || continue
      i=$((i + 1))
      printf '%-3s %-5s %-30s %-24s %s\n' "$i" "$count" "$kind" "$frames" "$(basename "$example")"
    done <<<"$grouped"
  fi
}

cmd_triage() {
  local tmo=5 json=0 dir=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --timeout) [ $# -ge 2 ] || die "--timeout değer ister"; tmo="$2"; shift ;;
      --json) json=1 ;;
      --) shift; break ;;
      -*) die "bilinmeyen seçenek: $1" ;;
      *) [ -z "$dir" ] || die "tek crash dizini verin"; dir="$1" ;;
    esac
    shift
  done
  [ -n "$dir" ] || die "crash dizini gerekli"
  [ $# -gt 0 ] || die "'--' sonrasında hedef komut gerekli"
  command -v timeout >/dev/null 2>&1 || die "timeout komutu yok (coreutils)"
  triage "$dir" "$tmo" "$json" "$@"
}

find_tool() {
  local t
  for t in "$@"; do
    [ -n "$t" ] || continue
    if command -v "$t" >/dev/null 2>&1; then command -v "$t"; return 0; fi
  done
  return 1
}

cmd_fuzz() {
  local dur=60 out="" src="$LAB_DIR/hedef.c" json=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --seconds) [ $# -ge 2 ] || die "--seconds değer ister"; dur="$2"; shift ;;
      --out) [ $# -ge 2 ] || die "--out değer ister"; out="$2"; shift ;;
      --src) [ $# -ge 2 ] || die "--src değer ister"; src="$2"; shift ;;
      --json) json=1 ;;
      *) die "bilinmeyen seçenek: $1" ;;
    esac
    shift
  done
  case "$dur" in ''|*[!0-9]*) die "--seconds pozitif tam sayı olmalı" ;; esac

  local fuzz cc
  if [ -n "${PENT05_AFL_FUZZ:-}" ]; then fuzz="$(find_tool "$PENT05_AFL_FUZZ" || true)"; else fuzz="$(find_tool afl-fuzz || true)"; fi
  if [ -n "${PENT05_AFL_CC:-}" ]; then cc="$(find_tool "$PENT05_AFL_CC" || true)"; else cc="$(find_tool afl-cc afl-clang-fast afl-gcc-fast || true)"; fi
  if [ -z "$fuzz" ] || [ -z "$cc" ]; then
    echo "[skip] AFL++ bulunamadı (afl-fuzz ve afl-cc gerekli). Kurulum: sudo apt install afl++"
    echo "       Mevcut crash dizini için: $0 triage <dizin> -- <hedef> @@"
    return 0
  fi
  [ -f "$src" ] || die "kaynak yok: $src"
  [ -n "$out" ] || out="$(mktemp -d)"
  mkdir -p "$out"

  echo "[1/3] Derleniyor (afl-cc + ASAN): $src"
  AFL_USE_ASAN=1 "$cc" -g -O1 -o "$out/hedef-afl" "$src"

  echo "[2/3] afl-fuzz $dur saniye çalışıyor (çıktı: $out/afl)"
  AFL_NO_UI=1 AFL_SKIP_CPUFREQ=1 AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 \
    "$fuzz" -V "$dur" -i "$LAB_DIR/seeds" -o "$out/afl" -- "$out/hedef-afl" @@ >"$out/afl-fuzz.log" 2>&1 \
    || echo "       afl-fuzz sıfırdan farklı döndü; ayrıntı: $out/afl-fuzz.log"

  local crashes="$out/afl/default/crashes"
  echo "[3/3] Triage: $crashes"
  if [ ! -d "$crashes" ]; then echo "       crash dizini oluşmadı; afl-fuzz.log dosyasına bakın"; return 0; fi
  triage "$crashes" 5 "$json" "$out/hedef-afl" @@
}

case "${1:-}" in
  fuzz) shift; cmd_fuzz "$@" ;;
  triage) shift; cmd_triage "$@" ;;
  -h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
