#!/usr/bin/env bash
# PENT-05 — AFL++ crash triage smoke runner
#
# Kullanım:
#   pent-05-afl-triage.sh fuzz   [--seconds N] [--out DİZİN] [--src HEDEF.c] [--json]
#   pent-05-afl-triage.sh triage [--timeout S] [--json] <crash-dizini> -- <komut> [arg|@@ ...]
#   pent-05-afl-triage.sh -h|--help
#
# fuzz:   hedefi afl-cc + ASAN ile derler, afl-fuzz'u N saniye (varsayılan 60, -m none) çalıştırır
#         ve bulunan crash'leri triage eder. afl-fuzz/afl-cc yoksa [skip] yazar, 0 döner.
# triage: crash dizinindeki her girdiyi hedefe yeniden verir (@@ varsa dosya yolu olarak,
#         yoksa stdin'den) ve sonucu sınıflandırır: ASAN hata türü + üst iki çerçeve, sinyal
#         (SIGSEGV, SIGABRT, SIGFPE...), zaman aşımı (hang), exit:N ya da no-crash. Aynı
#         sınıftaki girdiler tek bucket'ta toplanır. İlerleme mesajları stderr'e yazılır.
#
# Çıkış kodu: 0 = çalıştı (crash bulunsa da), 1 = afl-fuzz başarısız, 2 = kullanım/araç hatası
# Ortam: PENT05_AFL_FUZZ, PENT05_AFL_CC (araç yolları), ASAN_OPTIONS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_DIR="$SCRIPT_DIR/../pent-05"
MAX_OUTPUT=1048576   # sınıflandırma için okunan en fazla hedef çıktısı (bayt)
KILL_AFTER=2         # SIGTERM'e uymayan hedef bu kadar saniye sonra SIGKILL alır

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "hata: $*" >&2; exit 2; }
log() { echo "$*" >&2; }

export ASAN_OPTIONS="${ASAN_OPTIONS:-abort_on_error=1:symbolize=1:detect_leaks=0}"

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

show_name() { local n; n="$(basename -- "$1")"; printf '%s' "${n//[[:cntrl:]]/?}"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# classify <girdi> <timeout> <komut...> — C_KIND ve C_FRAMES değişkenlerini doldurur
classify() {
  local input="$1" tmo="$2"; shift 2
  local -a cmd=()
  local a used=0 rc pid watcher sig
  local out="$WORK/out" mark="$WORK/timed-out"
  for a in "$@"; do
    if [ "$a" = "@@" ]; then cmd+=("$input"); used=1; else cmd+=("$a"); fi
  done
  rm -f "$out" "$mark"

  # Hedef arka planda; ayrı bir bekçi süre dolunca işaret dosyası bırakıp önce TERM,
  # KILL_AFTER saniye sonra KILL gönderir. Böylece hedefin kendi exit 124'ü ile gerçek
  # zaman aşımı karışmaz ve TERM'i yok sayan hedef de takılıp kalmaz.
  set +e
  if [ "$used" = 1 ]; then
    "${cmd[@]}" >"$out" 2>&1 </dev/null &
  else
    "${cmd[@]}" >"$out" 2>&1 <"$input" &
  fi
  pid=$!
  ( nap() { sleep "$1" & sp=$!; wait "$sp"; }
    trap 'kill "$sp" 2>/dev/null; exit 0' TERM
    nap "$tmo"
    if kill -0 "$pid" 2>/dev/null; then
      : >"$mark"; kill -TERM "$pid" 2>/dev/null
      nap "$KILL_AFTER"; kill -KILL "$pid" 2>/dev/null
    fi ) >/dev/null 2>&1 &
  watcher=$!
  wait "$pid" 2>/dev/null; rc=$?
  kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null
  set -e

  # Bellek sınırı: yalnız ilk MAX_OUTPUT bayt incelenir.
  local text
  text="$(head -c "$MAX_OUTPUT" "$out" 2>/dev/null | tr -d '\0' || true)"

  C_FRAMES="-"
  if [ -e "$mark" ]; then
    C_KIND="hang"
  elif grep -q 'ERROR: AddressSanitizer' <<<"$text"; then
    C_KIND="asan:$(awk '/ERROR: AddressSanitizer:/ {for (i = 1; i <= NF; i++) if ($i == "AddressSanitizer:") {print $(i+1); exit}}' <<<"$text")"
    # Yığın imzası: ilk iki uygulama çerçevesinin tam fonksiyon adı (C++ adları boşluk
    # içerebilir: "operator new(unsigned long)"); konum kısmı " (/..." ya da " /..." atılır.
    C_FRAMES="$(awk '/^ *#[0-9]+ 0x[0-9a-fA-F]+ in / {
        f = $0
        sub(/^ *#[0-9]+ 0x[0-9a-fA-F]+ in /, "", f)
        sub(/ (\(|\/).*$/, "", f)
        gsub(/[\t\r]/, " ", f)
        if (f ~ /^(__interceptor_|___interceptor_|__asan|__sanitizer|__libc_start)/) next
        s = (n ? s "<" : "") f; if (++n == 2) exit
      } END { print (n ? s : "-") }' <<<"$text")"
  elif [ "$rc" -gt 128 ]; then
    # Kabuk, sinyalle ölen süreci 128+N ile bildirir (AFL/ASAN crash'leri sinyaldir).
    # Sınırlama: kabuk, hedefin kendi döndürdüğü 129+ çıkış kodunu sinyalden ayıramaz; böyle
    # bir kod da signal:* olarak görünür. Zaman aşımı ise işaret dosyasıyla ayrıldığı için
    # hedefin kendi exit 124'ü hang sayılmaz.
    sig="$(kill -l $((rc - 128)) 2>/dev/null || echo $((rc - 128)))"
    C_KIND="signal:SIG${sig#SIG}"
  elif [ "$rc" -ne 0 ]; then
    C_KIND="exit:$rc"
  else
    C_KIND="no-crash"
  fi
}

# triage <crash-dizini> <timeout> <json 0|1> <komut...>
triage() {
  local dir="$1" tmo="$2" json="$3"; shift 3
  [ -d "$dir" ] || die "crash dizini yok: $dir"
  local -a files=() kinds=() frames=()
  local f
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    case "$(basename -- "$f")" in README.txt|.*) continue ;; esac
    classify "$f" "$tmo" "$@"
    files+=("$f"); kinds+=("$C_KIND"); frames+=("$C_FRAMES")
  done
  local total="${#files[@]}"

  # Gruplama yalnız tür + çerçeve + sıra numarasıyla yapılır; dosya yolları (tab, satır
  # sonu içerebilir) awk'a hiç verilmez, sonra sıra numarasıyla diziden alınır.
  local grouped="" i
  if [ "$total" -gt 0 ]; then
    grouped="$(for i in "${!files[@]}"; do printf '%s\t%s\t%s\n' "${kinds[$i]}" "${frames[$i]}" "$i"; done |
      awk -F'\t' '{k = $1 "\t" $2; if (!(k in c)) {o[++n] = k; ex[k] = $3}; c[k]++}
        END {for (j = 1; j <= n; j++) print c[o[j]] "\t" o[j] "\t" ex[o[j]]}' |
      sort -t"$(printf '\t')" -k1,1nr -s)"
  fi
  local buckets=0 crashes=0
  if [ -n "$grouped" ]; then
    buckets="$(wc -l <<<"$grouped" | tr -d ' ')"
    crashes="$(awk -F'\t' '$2 != "no-crash" && $2 !~ /^exit:/ {n++} END {print n + 0}' <<<"$grouped")"
  fi

  local count kind fr idx
  if [ "$json" = 1 ]; then
    printf '{"tool":"pent-05-afl-triage","inputs":%d,"buckets":%d,"unique_crashes":%d,"groups":[' "$total" "$buckets" "$crashes"
    local sep=""
    while IFS=$'\t' read -r count kind fr idx; do
      [ -n "$count" ] || continue
      printf '%s{"count":%d,"kind":%s,"frames":%s,"example":%s}' "$sep" "$count" \
        "$(json_str "$kind")" "$(json_str "$fr")" "$(json_str "${files[$idx]}")"
      sep=","
    done <<<"$grouped"
    printf ']}\n'
  else
    echo "PENT-05 AFL++ Crash Triage"
    echo "Hedef : $*"
    echo "Girdi : $total dosya -> $buckets bucket ($crashes benzersiz crash)"
    echo
    printf '%-3s %-5s %-30s %-24s %s\n' "#" ADET TUR CERCEVE ORNEK
    i=0
    while IFS=$'\t' read -r count kind fr idx; do
      [ -n "$count" ] || continue
      i=$((i + 1))
      printf '%-3s %-5s %-30s %-24s %s\n' "$i" "$count" "$kind" "$fr" "$(show_name "${files[$idx]}")"
    done <<<"$grouped"
  fi
}

positive_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -gt 0 ]; }

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
  positive_int "$tmo" || die "--timeout pozitif tam sayı olmalı (saniye)"
  [ -n "$dir" ] || die "crash dizini gerekli"
  [ $# -gt 0 ] || die "'--' sonrasında hedef komut gerekli"
  command -v "$1" >/dev/null 2>&1 || die "hedef çalıştırılamıyor: $1"
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
  positive_int "$dur" || die "--seconds pozitif tam sayı olmalı"

  local fuzz cc
  if [ -n "${PENT05_AFL_FUZZ:-}" ]; then fuzz="$(find_tool "$PENT05_AFL_FUZZ" || true)"; else fuzz="$(find_tool afl-fuzz || true)"; fi
  if [ -n "${PENT05_AFL_CC:-}" ]; then cc="$(find_tool "$PENT05_AFL_CC" || true)"; else cc="$(find_tool afl-cc afl-clang-fast afl-gcc-fast || true)"; fi
  if [ -z "$fuzz" ] || [ -z "$cc" ]; then
    log "[skip] AFL++ bulunamadı (afl-fuzz ve afl-cc gerekli). Kurulum: sudo apt install afl++"
    log "       Mevcut crash dizini için: $0 triage <dizin> -- <hedef> @@"
    return 0
  fi
  [ -f "$src" ] || die "kaynak yok: $src"
  [ -n "$out" ] || out="$(mktemp -d)"
  # Eski bir koşunun crash'leri yeni sonuç gibi raporlanmasın.
  [ ! -e "$out/afl" ] || die "$out/afl zaten var; boş bir --out dizini verin"
  mkdir -p "$out"

  log "[1/3] Derleniyor (afl-cc + ASAN): $src"
  AFL_USE_ASAN=1 "$cc" -g -O1 -o "$out/hedef-afl" "$src" >&2

  log "[2/3] afl-fuzz $dur saniye çalışıyor (çıktı: $out/afl)"
  # ASAN gölge belleği AFL++'ın varsayılan bellek sınırına sığmaz: -m none.
  if ! AFL_NO_UI=1 AFL_SKIP_CPUFREQ=1 AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 \
      "$fuzz" -m none -V "$dur" -i "$LAB_DIR/seeds" -o "$out/afl" -- "$out/hedef-afl" @@ >"$out/afl-fuzz.log" 2>&1; then
    log "hata: afl-fuzz başarısız oldu; ayrıntı: $out/afl-fuzz.log"
    tail -n 20 "$out/afl-fuzz.log" >&2 || true
    return 1
  fi

  local crashes="$out/afl/default/crashes"
  log "[3/3] Triage: $crashes"
  if [ ! -d "$crashes" ]; then log "hata: crash dizini oluşmadı; $out/afl-fuzz.log dosyasına bakın"; return 1; fi
  triage "$crashes" 5 "$json" "$out/hedef-afl" @@
}

case "${1:-}" in
  fuzz) shift; cmd_fuzz "$@" ;;
  triage) shift; cmd_triage "$@" ;;
  -h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
