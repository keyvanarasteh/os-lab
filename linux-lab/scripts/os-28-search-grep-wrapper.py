#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="OS-28: File Search & Text-Grep Teaching Wrapper")
    parser.add_argument("path", nargs="?", default=".", help="Aranacak dizin yolu")
    parser.add_argument("file_pattern", nargs="?", default="*.py", help="Wildcard içeren dosya kalıbı (örn: *.py, test*)")
    parser.add_argument("search_term", nargs="?", default="def", help="Dosyalarda aranacak metin (grep için)")
    parser.add_argument("--execute", action="store_true", help="Oluşturulan komutları terminalde gerçekten çalıştırır")

    args = parser.parse_args()

    print("=" * 70)
    print(" OS-28: File Search & Text-Grep Teaching Wrapper")
    print("=" * 70)

    # 1. find komutunu wildcard ile inşa etme
    find_command = f"find {args.path} -name '{args.file_pattern}'"
    
    # 2. find ve grep komutlarını birleştirerek tam komut zinciri oluşturma
    grep_command = f"find {args.path} -name '{args.file_pattern}' -type f | xargs grep -n '{args.search_term}'"

    print("\n[EĞİTSEL AÇIKLAMA] Girdilerinizden üretilen Linux Komutları:")
    print("-" * 70)
    print(f"1. Dosya Arama Komutu (Find):")
    print(f"   -> {find_command}")
    print("   Açıklama:")
    print(f"      * find: Belirtilen dizin altında dosya ve klasör arar.")
    print(f"      * {args.path}: Aramanın başlatılacağı konum.")
    print(f"      * -name '{args.file_pattern}': Wildcard (*) kullanarak dosya adını filtreler.")

    print(f"\n2. Metin Tarama Komutu (Grep ile Birleştirilmiş):")
    print(f"   -> {grep_command}")
    print("   Açıklama:")
    print(f"      * -type f: Sadece normal dosyaları filtreler.")
    print(f"      * | xargs: Bulunan dosya listesini sıradaki komuta girdi olarak verir.")
    print(f"      * grep -n: Bulunan dosyaların içinde metni arar ve eşleşen satır numaralarını (-n) gösterir.")
    print(f"      * '{args.search_term}': Aranan hedef kelime/metin.")
    print("-" * 70)

    # İsteğe bağlı olarak komutu saf Python ile güvenli ve hatasız çalıştırma
    if args.execute:
        print("\n[ÇALIŞTIRMA] Oluşturulan komut simüle edilerek çalıştırılıyor...\n")
        try:
            base_path = Path(args.path)
            pattern = args.file_pattern
            term = args.search_term
            
            matched_files = sorted([p for p in base_path.glob(f"**/{pattern}") if p.is_file()])
            
            found_any = False
            for file_path in matched_files:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if term in line:
                                print(f"{file_path}:{line_num}:{line.strip()}")
                                found_any = True
                except Exception:
                    pass
            
            if not found_any:
                print("Eşleşen sonuç bulunamadı.")
        except Exception as e:
            print(f"Çalıştırma hatası: {e}")
    else:
        print("\n[İpucu]: Komutları sistem üzerinde gerçekten çalıştırmak için sonuna '--execute' ekleyebilirsiniz.")
        print("Örnek: python3 os-28-search-grep-wrapper.py . '*.py' 'def' --execute")

if __name__ == "__main__":
    main()
