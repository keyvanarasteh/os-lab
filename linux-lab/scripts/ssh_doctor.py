#!/usr/bin/env python3
"""OS-17: SSH Connection Troubleshooter (classifies an SSH error message)."""

import argparse
import ipaddress
import re

# 127.0.0.0/8, ::1 and the name localhost; digits/dots around the match must not continue it.
LOOPBACK = re.compile(r"(?<![\d.])127(?:\.\d{1,3}){3}(?![\d.])|(?<![\w:])::1(?![\w:])|\blocalhost\b")
AUTH_PHRASES = (
    "permission denied",
    "authentication failed",
    "wrong password",
    "incorrect password",
    "access denied",
)


def diagnose(message):
    text = message.lower()

    # A loopback address explains the failure better than the timeout it usually causes.
    if LOOPBACK.search(text):
        return (
            "LOOPBACK",
            "Loopback adresi (127.x.x.x, ::1 ya da localhost) yerel makineyi gosterir.",
            "Uzak baglanti icin Ubuntu'nun gercek ag IP adresini kullan.",
        )

    if "timed out" in text or "timeout" in text:
        return (
            "TIMEOUT",
            "SSH sunucusuna baglanti kurulamadi.",
            "IP adresini, port 22'yi, ag baglantisini ve firewall'u kontrol et.",
        )

    if any(phrase in text for phrase in AUTH_PHRASES):
        return (
            "AUTHENTICATION",
            "SSH kimlik dogrulamasi basarisiz.",
            "Kullanici adini, parolayi ve SSH anahtarini kontrol et.",
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


def check_host(host):
    """Return a printable one-line note about --host; the raw text is never echoed back."""
    # ip_address() accepts IPv6 scope ids ("fe80::1%eth0"), whose text may carry control
    # bytes, so scoped and non-printable input is rejected before anything is printed.
    if "%" in host or not host.isprintable():
        return "UYARI: Gecersiz IP adresi."
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "UYARI: Gecersiz IP adresi."
    if address.is_loopback:
        return "UYARI: Loopback adresi uzak SSH icin uygun degil."
    return f"Hedef IP: {address}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="OS-17 SSH Connection Troubleshooter")
    parser.add_argument("error", nargs="?", help="SSH hata mesaji")
    parser.add_argument("--host", help="Kontrol edilecek IP adresi")
    args = parser.parse_args(argv)

    if args.host:
        print(check_host(args.host))

    try:
        message = args.error or input("SSH hata mesajini girin: ")
    except EOFError:
        message = ""
    category, explanation, solution = diagnose(message)

    print("\n--- SSH Teshis Raporu ---")
    print(f"Kategori : {category}")
    print(f"Aciklama : {explanation}")
    print(f"Cozum    : {solution}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
