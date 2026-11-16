
#!/usr/bin/env python3
"""OS-17: SSH Connection Troubleshooter."""

import argparse
import ipaddress


def diagnose(message):
    text = message.lower()

    if "timed out" in text or "timeout" in text:
        return (
            "TIMEOUT",
            "SSH sunucusuna baglanti kurulamadi.",
            "IP adresini, port 22'yi, ag baglantisini ve firewall'u kontrol et.",
        )

    if "permission denied" in text or "authentication failed" in text:
        return (
            "AUTHENTICATION",
            "SSH kimlik dogrulamasi basarisiz.",
            "Kullanici adini, parolayi ve SSH anahtarini kontrol et.",
        )

    if "127.0.1.1" in text:
        return (
            "LOOPBACK",
            "127.0.1.1 yerel bir loopback adresidir.",
            "Uzak baglanti icin Ubuntu'nun gercek ag IP adresini kullan.",
        )

    if "firewall" in text or "blocked" in text:
        return (
            "FIREWALL",
            "Baglanti guvenlik duvari tarafindan engelleniyor olabilir.",
            "UFW kurallarini ve okul aginin SSH kisitlamalarini kontrol et.",
        )

    if "adapter" in text or "network interface" in text:
        return (
            "ADAPTER",
            "Yanlis ag adaptoru kullaniliyor olabilir.",
            "VirtualBox NAT/Bridged ayarlarini ve IP adresini kontrol et.",
        )

    return (
        "UNKNOWN",
        "Sorun otomatik olarak tanimlanamadi.",
        "ssh -vvv komutuyla baglanti gunlugunu incele.",
    )


def main():
    parser = argparse.ArgumentParser(
        description="OS-17 SSH Connection Troubleshooter"
    )
    parser.add_argument(
        "error",
        nargs="?",
        help="SSH hata mesaji",
    )
    parser.add_argument(
        "--host",
        help="Kontrol edilecek IP adresi",
    )
    args = parser.parse_args()

    if args.host:
        try:
            address = ipaddress.ip_address(args.host)
            if address.is_loopback:
                print("UYARI: Loopback adresi uzak SSH icin uygun degil.")
            else:
                print(f"Hedef IP: {address}")
        except ValueError:
            print("UYARI: Gecersiz IP adresi.")

    message = args.error or input("SSH hata mesajini girin: ")
    category, explanation, solution = diagnose(message)

    print("\n--- SSH Teshis Raporu ---")
    print(f"Kategori : {category}")
    print(f"Aciklama : {explanation}")
    print(f"Cozum    : {solution}")


if __name__ == "__main__":
    main()
