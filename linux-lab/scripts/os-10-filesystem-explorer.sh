#!/bin/bash
echo "---OS-10 Linux Filesystem Hierarchy Explorer & Teaching Map---"

echo "/:"
echo "Kök dizin. Tüm Linux dosya sisteminin başıdır, diğer klasörler bunun altında yer alır."
ls /

echo "/home:"
echo "Kullanıcıların kişisel dosyaları, belgeleri ve özel ayarları burada tutulur."
ls /home

echo "/etc:"
echo "Ağ, kullanıcı hesapları ve servis ayarlarını tutan metin tabanlı konfigürasyonlar buradadır."
ls /etc

echo "/opt:"
echo "Paket yöneticisi dışında elle kurulan üçüncü parti uygulamalar buraya yerleşir."
ls /opt

echo "/root:"
echo "Sistem yöneticisinin özel ev dizinidir. Güvenlik için her kullanıcının erişimine açılmaz."
ls /root


echo "---Gizli Dosyalar---"

echo "Linux'ta adı nokta (.) ile başlayan dosya ve klasörler gizlidir. Amacı kullanıcının .bashrc ve .profile gibi önemli ayar dosyalarını yanlışlıkla silmesini önlemek ve klasör görünümünü sade tutmaktır."
echo "Standart (ls) komutu bunları göstermez görmek için (ls -a) kullanılır."
ls -a $HOME
