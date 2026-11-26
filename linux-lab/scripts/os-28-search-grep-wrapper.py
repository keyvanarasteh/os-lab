#!/usr/bin/env python3
import argparse
import shlex
import subprocess
from pathlib import Path


def show(args):
    """Argüman listesini terminalde güvenle görünecek şekilde yazar (shlex.quote)."""
    return " ".join(shlex.quote(a) for a in args)


def main():
    parser = argparse.ArgumentParser(description="OS-28: File Search & Text-Grep Teaching Wrapper")
    parser.add_argument("path", nargs="?", default=".", help="Aranacak dizin yolu")
    parser.add_argument("file_pattern", nargs="?", default="*.py", help="Wildcard içeren dosya kalıbı (örn: *.py, test*)")
    parser.add_argument("search_term", nargs="?", default="def", help="Dosyalarda aranacak metin (grep için)")
    parser.add_argument("--execute", action="store_true", help="Oluşturulan komutları terminalde gerçekten çalıştırır")

    args = parser.parse_args()

    # Komutlar f-string yerine argüman listesi olarak tanımlanır.
    # Ekranda gösterilen komutlar ile --execute ile çalışan komutlar aynı listelerdir.
    find_args = ["find", args.path, "-type", "f", "-name", args.file_pattern, "-print0"]
    grep_args = ["grep", "-nHF", "--", args.search_term]  # sonuna bulunan dosyalar eklenir

    print("=" * 70)
    print(" OS-28: File Search & Text-Grep Teaching Wrapper")
    print("=" * 70)

    print("\n[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:")
    print("-" * 70)
    print("1. Dosya Arama Komutu (Find):")
    print(f"   Argüman listesi : {find_args}")
    print(f"   Komut görünümü  : {show(find_args)}")
    print("   Açıklama:")
    print("      * find: Belirtilen dizin altında dosya ve klasör arar.")
    print(f"      * {args.path}: Aramanın başlatılacağı konum.")
    print("      * -type f: Sadece normal dosyaları listeler.")
    print(f"      * -name {args.file_pattern}: Wildcard (*) kullanarak dosya adını filtreler.")
    print("      * -print0: Dosya adlarını boşluk yerine NUL karakteriyle ayırır (boşluklu adlar bozulmaz).")

    print("\n2. Metin Tarama Komutu (Grep):")
    print(f"   Argüman listesi : {grep_args} + bulunan dosyalar")
    print(f"   Komut görünümü  : {show(grep_args)} <bulunan dosyalar>")
    print("   Açıklama:")
    print("      * grep -n: Eşleşen satırların numarasını gösterir.")
    print("      * -H: Her sonuçta dosya adını yazar.")
    print("      * -F: Arama metnini düzenli ifade değil, düz metin olarak arar.")
    print("      * --: Arama ifadesinin tire (-) ile başlaması durumunda seçenek sanılmasını önler.")
    print(f"      * {args.search_term}: Aranan hedef kelime/metin.")
    print("      * <bulunan dosyalar>: 1. komutun bulduğu dosyalar buraya eklenir.")
    print("-" * 70)

    if args.execute:
        print("\n[ÇALIŞTIRMA] Komutlar argüman listesiyle (shell kullanmadan) çalıştırılıyor...\n")

        if not Path(args.path).is_dir():
            print(f"Hata: Geçerli bir dizin bulunamadı -> {args.path}")
            return

        try:
            # 1. adım: eşleşen dosyaları bul (NUL ile ayrılmış çıktı)
            print(f"Çalışan find listesi : {find_args}")
            find_proc = subprocess.run(find_args, capture_output=True, text=True, check=False)
            matched_files = [f for f in find_proc.stdout.split("\0") if f]

            if find_proc.stderr:
                print(f"Uyarı/Hata (find): {find_proc.stderr.rstrip()}")

            if not matched_files:
                print("Eşleşen dosya bulunamadı.")
                return

            # 2. adım: bulunan dosyalarda grep (shell=False)
            grep_cmd = grep_args + matched_files
            print(f"Çalışan grep listesi : {grep_args} + {len(matched_files)} dosya\n")
            grep_proc = subprocess.run(grep_cmd, capture_output=True, text=True, check=False)

            if grep_proc.stdout:
                print(grep_proc.stdout.rstrip())
            else:
                print("Eşleşen sonuç bulunamadı.")

            if grep_proc.stderr:
                print(f"Uyarı/Hata (grep): {grep_proc.stderr.rstrip()}")

        except Exception as e:
            print(f"Çalıştırma hatası: {e}")
    else:
        print("\n[İpucu]: Komutları sistem üzerinde gerçekten çalıştırmak için sonuna '--execute' ekleyebilirsiniz.")
        print("Örnek: python3 os-28-search-grep-wrapper.py . '*.py' 'def' --execute")


if __name__ == "__main__":
    main()
