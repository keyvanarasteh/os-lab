#!/usr/bin/env bash
# OS-28 otomatik testleri: os-28-search-grep-wrapper.py için
# Kullanım: bash test-os-28-search-grep.sh  (betikle aynı klasörde olmalı)
set -u

SCRIPT="$(cd "$(dirname "$0")" && pwd)/os-28-search-grep-wrapper.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

# Test dosyaları: boşluklu dizin/dosya adı, tire ile başlayan ve tek tırnaklı metin
mkdir -p "$TMP/my dir"
printf 'def a():\n    pass\n' > "$TMP/my dir/a b.py"
printf "def z(): pass\nit's here\n-x test(\n" > "$TMP/z.py"

# check "açıklama" "çıktıda aranacak metin" "komut çıktısı"
check() {
    local name="$1" expected="$2" output="$3"
    if grep -qF -- "$expected" <<< "$output"; then
        echo "PASS: $name"
        pass=$((pass + 1))
    else
        echo "FAIL: $name (beklenen: $expected)"
        fail=$((fail + 1))
    fi
}

out=$(python3 "$SCRIPT" "$TMP" '*.py' 'def' --execute)
check "boşluklu dizin ve dosya adı" "my dir/a b.py:1:def a():" "$out"
check "normal eşleşme" "z.py:1:def z(): pass" "$out"

out=$(python3 "$SCRIPT" "$TMP" '*.py' '-x test(' --execute)
check "tire ile başlayan ve özel karakterli metin" "z.py:3:-x test(" "$out"

out=$(python3 "$SCRIPT" "$TMP" '*.py' "it's" --execute)
check "tek tırnaklı metin" "z.py:2:it's here" "$out"

out=$(python3 "$SCRIPT" /yok/dizin '*.py' 'def' --execute)
check "geçersiz dizin" "Geçerli bir dizin bulunamadı" "$out"

out=$(python3 "$SCRIPT" "$TMP" '*.py' 'olmayan_metin_xyz' --execute)
check "eşleşme yok" "Eşleşen sonuç bulunamadı" "$out"

echo "Sonuç: $pass geçti, $fail kaldı"
[ "$fail" -eq 0 ]
