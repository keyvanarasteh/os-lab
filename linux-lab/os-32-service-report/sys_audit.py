import subprocess
import sys

def run_systemctl(args):
    """systemctl komutlarını güvenli bir şekilde çalıştırıp çıktısını döndürür."""
    try:
        result = subprocess.run(
            ['systemctl'] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[HATA] systemctl {' '.join(args)} çalıştırılamadı: {e}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("[HATA] systemctl bu sistemde bulunamadı.", file=sys.stderr)
        return None

def main():
    print("=== OS-32 System Audit & Service Health Report ===")

    # 1. Tüm servislerin listesi ve durumu
    print("\n[1] Servis Envanteri (systemctl list-units --type=service --all):")
    units_output = run_systemctl(['list-units', '--type=service', '--all', '--no-pager'])
    if units_output:
        lines = units_output.splitlines()
        for line in lines[:25]:
            print(line)
        if len(lines) > 25:
            print(f"... ve {len(lines) - 25} satır daha ...")

    # 2. Servis dosya durumları (enabled/disabled)
    print("\n[2] Servis Dosya Durumları (systemctl list-unit-files):")
    files_output = run_systemctl(['list-unit-files', '--type=service', '--no-pager'])
    if files_output:
        lines = files_output.splitlines()
        for line in lines[:15]:
            print(line)

    # 3. Hatalı (failed) servisler
    print("\n[3] Hatalı Servisler (systemctl --failed):")
    failed_output = run_systemctl(['--failed', '--no-pager'])
    if failed_output:
        print(failed_output)
    else:
        print("Hatalı servis sorgulanamadı veya başarısız komut.")

    print("\n[BAŞARILI] OS-32 Denetim Raporu başarıyla tamamlandı.")

if __name__ == '__main__':
    main()
