# Adres ve servis nesneleri

Bu dosya [nesneler.json](nesneler.json) dosyasından üretilir: `python3 lab/politika.py nesneler-md`. Elle düzenlenmez.

Kural tabloları bu adları kullanır. `company.json` ise aynı kuralların somut adresli hâlini taşır, çünkü dersin aracı tanımadığı adları `any` olarak işler. İkisinin aynı olduğunu `lab/politika.py dogrula` denetler.

**Girdi** türündeki nesnelerin değeri burada yoktur: gerçek WAN adresleri kurulumda operatörden alınır, uydurulmaz. Testlerde belgeleme adresleri kullanılır ([lab/lab-degerleri.txt](lab/lab-degerleri.txt)).

Adresler hayali şirket içindir, gerçek altyapı bilgisi değildir.

## Ortak

| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |
|---|---|---|---|---|
| `ozel-10-8` | Ağ | — | 10.0.0.0/8 | Şirketin bütün özel adres alanı. |
| `sube-fw-tunel` | Grup | `tunel-izmir`, `tunel-amsterdam`, `tunel-ankara` | 172.31.2.2, 172.31.3.2, 172.31.4.2 | FortiManager'a bağlanan şube güvenlik duvarları. |
| `sube-personel` | Grup | `izm-v20-personel`, `ams-v20-personel`, `ank-v20-personel` | 10.2.20.0/23, 10.3.20.0/24, 10.4.20.0/22 | Tünelden ERP'ye gelen şube personeli. |
| `sube-yazilim` | Grup | `izm-v30-yazilim`, `ams-v30-yazilim`, `ank-v30-yazilim` | 10.2.30.0/25, 10.3.30.0/26, 10.4.30.0/27 | Tünelden Git'e gelen şube yazılımcıları. |
| `wan-subeler` | Grup | `wan-izmir`, `wan-amsterdam`, `wan-ankara` | wan-izmir, wan-amsterdam, wan-ankara | IPsec başlatabilen şube WAN adresleri. |
| `yonetim-tum` | Grup | `ist-v10-yonetim`, `izm-v10-yonetim`, `ams-v10-yonetim`, `ank-v10-yonetim` | 10.1.10.0/26, 10.2.10.0/26, 10.3.10.0/26, 10.4.10.0/26 | Bütün şubelerin yönetim ağları. |
| `onayli-git` | FQDN | — | github.com, gitlab.com | Dış Git depoları. Listeyi yazılım ekibinin talebi ve SOC onayıyla BT Operasyon Sorumlusu günceller. |
| `any` | Özel | — | — | Bütün adresler. Yalnızca kural kaynağı ve son ret kuralında kullanılır. |
| `internet` | Özel | — | — | WAN arayüzünden gelen veya çıkan trafik. Cihazda bölge (zone) olarak uygulanır, adres listesi değildir. |

## İstanbul

| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |
|---|---|---|---|---|
| `ist-tum` | Ağ | — | 10.1.0.0/16 | İstanbul adres bloğu, VPN havuzları dahil. |
| `ist-v10-yonetim` | Ağ | — | 10.1.10.0/26 | VLAN 10: ağ cihazı yönetimi. |
| `ist-v20-personel` | Ağ | — | 10.1.20.0/22 | VLAN 20: personel. |
| `ist-v30-yazilim` | Ağ | — | 10.1.30.0/24 | VLAN 30: yazılım. |
| `ist-v40-arge` | Ağ | — | 10.1.40.0/26 | VLAN 40: Ar-Ge. |
| `ist-v50-teknik` | Ağ | — | 10.1.50.0/25 | VLAN 50: teknik ekip ve SOC. |
| `ist-v60-sunucu` | Ağ | — | 10.1.60.0/24 | VLAN 60: altyapı ve uygulama sunucuları. |
| `ist-v61-yonetim-araclari` | Ağ | — | 10.1.61.0/27 | VLAN 61: bastion, izleme ve merkezi yönetim. |
| `ist-v63-veri` | Ağ | — | 10.1.63.0/26 | VLAN 63: veritabanları. |
| `ist-v64-sinir` | Ağ | — | 10.1.64.0/26 | VLAN 64: proxy ve kamera kayıt. |
| `ist-v70-dmz` | Ağ | — | 10.1.70.0/27 | VLAN 70: WAF ve web uygulaması. |
| `ist-v80-iot` | Ağ | — | 10.1.80.0/25 | VLAN 80: kamera, yazıcı, kartlı geçiş. |
| `ist-v85-misafir` | Ağ | — | 10.1.85.0/24 | VLAN 85: misafir. |
| `vpn-gelistirici` | Ağ | — | 10.1.204.0/24 | Geliştirici VPN havuzu. 115 × 1,3 = 150 adres gerekir. |
| `vpn-hoca` | Ağ | — | 10.1.208.0/22 | Hoca VPN havuzu. 400 × 1,3 = 520 adres gerekir. |
| `vpn-personel` | Ağ | — | 10.1.200.0/22 | Personel VPN havuzu. 650 × 1,3 = 845 adres gerekir. |
| `vpn-yonetici` | Ağ | — | 10.1.205.0/25 | Yönetici VPN havuzu. 75 × 1,3 = 98 adres gerekir. |
| `bastion` | Sunucu | — | 10.1.61.5 | Oturum kaydeden yönetim sıçrama sunucusu. |
| `fortimanager` | Sunucu | — | 10.1.61.6 | FortiManager. |
| `glpi` | Sunucu | — | 10.1.61.21 | Olay kayıt sistemi. |
| `grafana` | Sunucu | — | 10.1.61.22 | İzleme panelleri. |
| `ist-ad` | Sunucu | — | 10.1.60.3 | Active Directory ve RADIUS. |
| `ist-dns` | Sunucu | — | 10.1.60.2 | DNS, DHCP ve NTP. |
| `ist-erp` | Sunucu | — | 10.1.60.31 | ERP uygulaması. |
| `ist-erp-db` | Sunucu | — | 10.1.63.31 | ERP veritabanı. |
| `ist-git` | Sunucu | — | 10.1.60.32 | Git ve CI. |
| `ist-kamera-kayit` | Sunucu | — | 10.1.64.50 | Kamera kayıt sunucusu. |
| `ist-proxy` | Sunucu | — | 10.1.64.40 | İnternet çıkış proxy'si. |
| `ist-waf-1` | Sunucu | — | 10.1.70.12 | WAF düğümü 1. |
| `ist-waf-2` | Sunucu | — | 10.1.70.13 | WAF düğümü 2. |
| `ist-waf-vip` | Sunucu | — | 10.1.70.10 | WAF sanal adresi (VRRP). |
| `ist-web-db` | Sunucu | — | 10.1.63.30 | Kurumsal web sitesi veritabanı. |
| `ist-web-uyg` | Sunucu | — | 10.1.70.11 | Kurumsal web uygulaması. |
| `ist-yazici` | Sunucu | — | 10.1.80.20 | Yazıcı. |
| `tunel-ist-ams` | Sunucu | — | 172.31.3.1 | İstanbul'un Amsterdam tüneli adresi. |
| `tunel-ist-ank` | Sunucu | — | 172.31.4.1 | İstanbul'un Ankara tüneli adresi. |
| `tunel-ist-izm` | Sunucu | — | 172.31.2.1 | İstanbul'un İzmir tüneli adresi. |
| `wazuh` | Sunucu | — | 10.1.61.10 | SIEM ve log toplayıcı. |
| `zabbix` | Sunucu | — | 10.1.61.20 | Zabbix sunucusu. |
| `ist-guncelleme-kaynaklari` | Grup | `ist-v60-sunucu`, `ist-v61-yonetim-araclari`, `ist-v63-veri` | 10.1.60.0/24, 10.1.61.0/27, 10.1.63.0/26 | Güncellemeyi proxy'den alan sunucu ağları. |
| `ist-izleme-kaynaklari` | Grup | `ist-v60-sunucu`, `ist-v63-veri`, `ist-v64-sinir`, `ist-waf-dugumleri`, `ist-web-uyg`, `izm-izleme-kaynaklari`, `ank-izleme-kaynaklari` | 10.1.60.0/24, 10.1.63.0/26, 10.1.64.0/26, 10.1.70.12, 10.1.70.13, 10.1.70.11, 10.2.60.0/25, 10.2.64.0/26, 10.4.60.0/24, 10.4.63.0/26, 10.4.64.0/26, 10.4.70.12, 10.4.70.13, 10.4.70.11 | Zabbix aracısı veri gönderen sunucular. Amsterdam GDPR nedeniyle dahil değildir. |
| `ist-kurumsal` | Grup | `ist-v20-personel`, `ist-v30-yazilim`, `ist-v50-teknik` | 10.1.20.0/22, 10.1.30.0/24, 10.1.50.0/25 | İnternete denetimli çıkan kurum ağları. |
| `ist-log-hedefi` | Grup | `wazuh` | 10.1.61.10 | İstanbul'un log hedefi. |
| `ist-log-kaynaklari` | Grup | `ist-v10-yonetim`, `ist-v60-sunucu`, `ist-v63-veri`, `ist-v64-sinir`, `ist-waf-dugumleri`, `ist-web-uyg`, `izm-log-kaynaklari`, `ank-log-kaynaklari` | 10.1.10.0/26, 10.1.60.0/24, 10.1.63.0/26, 10.1.64.0/26, 10.1.70.12, 10.1.70.13, 10.1.70.11, 10.2.10.0/26, 10.2.60.0/25, 10.2.64.0/26, 10.4.10.0/26, 10.4.60.0/24, 10.4.63.0/26, 10.4.64.0/26, 10.4.70.12, 10.4.70.13, 10.4.70.11 | Logları Wazuh'a giden cihaz ve sunucular. Amsterdam GDPR nedeniyle dahil değildir. |
| `ist-panel-sunuculari` | Grup | `wazuh`, `zabbix`, `grafana`, `glpi`, `fortimanager` | 10.1.61.10, 10.1.61.20, 10.1.61.22, 10.1.61.21, 10.1.61.6 | Teknik ekibin HTTPS ile kullandığı paneller. |
| `ist-waf-dugumleri` | Grup | `ist-waf-1`, `ist-waf-2` | 10.1.70.12, 10.1.70.13 | Logları ve izleme verisini gönderen gerçek WAF adresleri. |
| `ist-yazici-istemcileri` | Grup | `ist-v20-personel`, `ist-v30-yazilim`, `ist-v40-arge`, `ist-v50-teknik` | 10.1.20.0/22, 10.1.30.0/24, 10.1.40.0/26, 10.1.50.0/25 | Yazıcı kullanan ağlar. |
| `ist-yonetilen-sunucular` | Grup | `ist-v60-sunucu`, `ist-v64-sinir`, `ist-v70-dmz` | 10.1.60.0/24, 10.1.64.0/26, 10.1.70.0/27 | Teknik ekip ve bastion'un yönettiği sunucu ağları. |
| `ist-yonetim-erisimi` | Grup | `ist-v10-yonetim`, `izm-v10-yonetim`, `ams-v10-yonetim`, `ank-v10-yonetim` | 10.1.10.0/26, 10.2.10.0/26, 10.3.10.0/26, 10.4.10.0/26 | İstanbul'dan geçerek yönetilen ağlar. |
| `wan-istanbul` | Girdi | — | Kurulum girdisi, tanımlı değil | İstanbul güvenlik duvarı WAN adresi. Operatörden alınacak gerçek adres burada tanımlanmaz, kurulum girdisidir. |

## İzmir

| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |
|---|---|---|---|---|
| `izm-tum` | Ağ | — | 10.2.0.0/16 | İzmir adres bloğu. |
| `izm-v10-yonetim` | Ağ | — | 10.2.10.0/26 | VLAN 10: ağ cihazı yönetimi. |
| `izm-v20-personel` | Ağ | — | 10.2.20.0/23 | VLAN 20: personel. |
| `izm-v30-yazilim` | Ağ | — | 10.2.30.0/25 | VLAN 30: yazılım. |
| `izm-v40-arge` | Ağ | — | 10.2.40.0/25 | VLAN 40: Ar-Ge. |
| `izm-v50-teknik` | Ağ | — | 10.2.50.0/26 | VLAN 50: teknik ekip. |
| `izm-v60-sunucu` | Ağ | — | 10.2.60.0/25 | VLAN 60: altyapı ve Ar-Ge verisi. |
| `izm-v64-sinir` | Ağ | — | 10.2.64.0/26 | VLAN 64: proxy ve kamera kayıt. |
| `izm-v80-iot` | Ağ | — | 10.2.80.0/25 | VLAN 80: kamera, yazıcı, kartlı geçiş. |
| `izm-v85-misafir` | Ağ | — | 10.2.85.0/24 | VLAN 85: misafir. |
| `izm-arge-veri` | Sunucu | — | 10.2.60.20 | Ar-Ge veri sunucusu. |
| `izm-dns` | Sunucu | — | 10.2.60.2 | DNS, DHCP ve NTP. |
| `izm-kamera-kayit` | Sunucu | — | 10.2.64.50 | Kamera kayıt sunucusu. |
| `izm-proxy` | Sunucu | — | 10.2.64.10 | İnternet çıkış proxy'si. |
| `izm-yazici` | Sunucu | — | 10.2.80.20 | Yazıcı. |
| `tunel-izmir` | Sunucu | — | 172.31.2.2 | İzmir tünel arayüzü adresi. |
| `izm-izleme-kaynaklari` | Grup | `izm-v60-sunucu`, `izm-v64-sinir` | 10.2.60.0/25, 10.2.64.0/26 | Zabbix aracısı veri gönderen sunucular. |
| `izm-kurumsal` | Grup | `izm-v20-personel`, `izm-v30-yazilim`, `izm-v50-teknik` | 10.2.20.0/23, 10.2.30.0/25, 10.2.50.0/26 | İnternete denetimli çıkan kurum ağları. |
| `izm-log-hedefi` | Grup | `wazuh` | 10.1.61.10 | İzmir'in log hedefi. |
| `izm-log-kaynaklari` | Grup | `izm-v10-yonetim`, `izm-v60-sunucu`, `izm-v64-sinir` | 10.2.10.0/26, 10.2.60.0/25, 10.2.64.0/26 | Logları Wazuh'a giden cihaz ve sunucular. |
| `izm-yazici-istemcileri` | Grup | `izm-v20-personel`, `izm-v30-yazilim`, `izm-v40-arge`, `izm-v50-teknik` | 10.2.20.0/23, 10.2.30.0/25, 10.2.40.0/25, 10.2.50.0/26 | Yazıcı kullanan ağlar. |
| `izm-yonetilen-sunucular` | Grup | `izm-v60-sunucu`, `izm-v64-sinir` | 10.2.60.0/25, 10.2.64.0/26 | Teknik ekibin yönettiği sunucu ağları. |
| `izm-yonetim-erisimi` | Grup | `izm-v10-yonetim` | 10.2.10.0/26 | Bu güvenlik duvarının arkasındaki yönetim ağı. |
| `wan-izmir` | Girdi | — | Kurulum girdisi, tanımlı değil | İzmir güvenlik duvarı WAN adresi. Operatörden alınacak gerçek adres burada tanımlanmaz, kurulum girdisidir. |

## Amsterdam

| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |
|---|---|---|---|---|
| `ams-tum` | Ağ | — | 10.3.0.0/16 | Amsterdam adres bloğu. |
| `ams-v10-yonetim` | Ağ | — | 10.3.10.0/26 | VLAN 10: ağ cihazı yönetimi. |
| `ams-v20-personel` | Ağ | — | 10.3.20.0/24 | VLAN 20: personel. |
| `ams-v30-yazilim` | Ağ | — | 10.3.30.0/26 | VLAN 30: yazılım. |
| `ams-v50-teknik` | Ağ | — | 10.3.50.0/27 | VLAN 50: teknik ekip. |
| `ams-v60-sunucu` | Ağ | — | 10.3.60.0/26 | VLAN 60: altyapı, log toplayıcı ve müşteri verisi. |
| `ams-v64-sinir` | Ağ | — | 10.3.64.0/26 | VLAN 64: kamera kayıt. |
| `ams-v80-iot` | Ağ | — | 10.3.80.0/26 | VLAN 80: kamera, yazıcı, kartlı geçiş. |
| `ams-v85-misafir` | Ağ | — | 10.3.85.0/24 | VLAN 85: misafir. |
| `ams-crm` | Sunucu | — | 10.3.60.20 | Müşteri (CRM) sunucusu. |
| `ams-dns` | Sunucu | — | 10.3.60.2 | DNS, DHCP ve NTP. |
| `ams-kamera-kayit` | Sunucu | — | 10.3.64.50 | Kamera kayıt sunucusu. |
| `ams-log-toplayici` | Sunucu | — | 10.3.60.10 | Yerel log toplayıcı (GDPR). |
| `ams-yazici` | Sunucu | — | 10.3.80.20 | Yazıcı. |
| `tunel-amsterdam` | Sunucu | — | 172.31.3.2 | Amsterdam tünel arayüzü adresi. |
| `ams-kurumsal` | Grup | `ams-v20-personel`, `ams-v30-yazilim`, `ams-v50-teknik` | 10.3.20.0/24, 10.3.30.0/26, 10.3.50.0/27 | İnternete denetimli çıkan kurum ağları. |
| `ams-log-hedefi` | Grup | `ams-log-toplayici` | 10.3.60.10 | Amsterdam'ın log hedefi. Veri Hollanda'da kalır. |
| `ams-log-kaynaklari` | Grup | `ams-v10-yonetim`, `ams-v64-sinir` | 10.3.10.0/26, 10.3.64.0/26 | Logları yerel toplayıcıya giden, başka VLAN'daki kaynaklar. |
| `ams-sunucular` | Grup | `ams-v60-sunucu`, `ams-v64-sinir` | 10.3.60.0/26, 10.3.64.0/26 | Amsterdam sunucu ağları. |
| `ams-uzak-ozel` | Grup | `ist-tum`, `izm-tum`, `ank-tum`, `tunel-ist-ams` | 10.1.0.0/16, 10.2.0.0/16, 10.4.0.0/16, 172.31.3.1 | Tünelin karşısındaki bütün adresler. |
| `ams-yazici-istemcileri` | Grup | `ams-v20-personel`, `ams-v30-yazilim`, `ams-v50-teknik` | 10.3.20.0/24, 10.3.30.0/26, 10.3.50.0/27 | Yazıcı kullanan ağlar. |
| `ams-yonetim-erisimi` | Grup | `ams-v10-yonetim` | 10.3.10.0/26 | Bu güvenlik duvarının arkasındaki yönetim ağı. |
| `onayli-guncelleme` | FQDN | — | archive.ubuntu.com, security.ubuntu.com | Amsterdam sunucu güncelleme adresleri. Sunucuların Ubuntu olduğu varsayılmıştır; işletim sistemi kesinleşince güncellenir. |
| `wan-amsterdam` | Girdi | — | Kurulum girdisi, tanımlı değil | Amsterdam güvenlik duvarı WAN adresi. Operatörden alınacak gerçek adres burada tanımlanmaz, kurulum girdisidir. |

## Ankara Akademik

| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |
|---|---|---|---|---|
| `ank-tum` | Ağ | — | 10.4.0.0/16 | Ankara adres bloğu. |
| `ank-v10-yonetim` | Ağ | — | 10.4.10.0/26 | VLAN 10: ağ cihazı ve erişim noktası yönetimi. |
| `ank-v100-ogrenci-yurt-1` | Ağ | — | 10.4.128.0/20 | VLAN 100: öğrenci Wi-Fi, Yurt 1. |
| `ank-v101-ogrenci-yurt-2` | Ağ | — | 10.4.144.0/20 | VLAN 101: öğrenci Wi-Fi, Yurt 2. |
| `ank-v102-ogrenci-kutuphane` | Ağ | — | 10.4.160.0/20 | VLAN 102: öğrenci Wi-Fi, Kütüphane. |
| `ank-v103-ogrenci-muhendislik` | Ağ | — | 10.4.176.0/20 | VLAN 103: öğrenci Wi-Fi, Mühendislik. |
| `ank-v104-ogrenci-fen-edebiyat` | Ağ | — | 10.4.192.0/20 | VLAN 104: öğrenci Wi-Fi, Fen-Edebiyat. |
| `ank-v105-ogrenci-iibf` | Ağ | — | 10.4.208.0/20 | VLAN 105: öğrenci Wi-Fi, İİBF. |
| `ank-v106-ogrenci-sosyal` | Ağ | — | 10.4.224.0/20 | VLAN 106: öğrenci Wi-Fi, Yemekhane ve sosyal alan. |
| `ank-v107-ogrenci-acik-alan` | Ağ | — | 10.4.240.0/20 | VLAN 107: öğrenci Wi-Fi, Spor ve açık alan. |
| `ank-v110-lab` | Ağ | — | 10.4.110.0/23 | VLAN 110: laboratuvar. |
| `ank-v20-personel` | Ağ | — | 10.4.20.0/22 | VLAN 20: personel. |
| `ank-v30-yazilim` | Ağ | — | 10.4.30.0/27 | VLAN 30: yazılım. |
| `ank-v40-arge` | Ağ | — | 10.4.40.0/26 | VLAN 40: Ar-Ge. |
| `ank-v50-teknik` | Ağ | — | 10.4.50.0/25 | VLAN 50: teknik ekip. |
| `ank-v60-sunucu` | Ağ | — | 10.4.60.0/24 | VLAN 60: altyapı ve uygulama sunucuları. |
| `ank-v63-veri` | Ağ | — | 10.4.63.0/26 | VLAN 63: LMS veritabanı. |
| `ank-v64-sinir` | Ağ | — | 10.4.64.0/26 | VLAN 64: proxy ve kamera kayıt. |
| `ank-v70-dmz` | Ağ | — | 10.4.70.0/26 | VLAN 70: WAF ve LMS uygulaması. |
| `ank-v80-iot` | Ağ | — | 10.4.80.0/24 | VLAN 80: kamera, yazıcı, kartlı geçiş. |
| `ank-v85-misafir` | Ağ | — | 10.4.85.0/24 | VLAN 85: misafir. |
| `ank-v90-hoca` | Ağ | — | 10.4.88.0/21 | VLAN 90: hoca. |
| `ank-dns` | Sunucu | — | 10.4.60.2 | DNS, DHCP ve NTP. |
| `ank-dosya` | Sunucu | — | 10.4.60.40 | Laboratuvar dosya sunucusu. |
| `ank-kamera-kayit` | Sunucu | — | 10.4.64.50 | Kamera kayıt sunucusu. |
| `ank-lms-db` | Sunucu | — | 10.4.63.30 | LMS veritabanı. |
| `ank-lms-uyg` | Sunucu | — | 10.4.70.11 | LMS uygulaması. |
| `ank-obs` | Sunucu | — | 10.4.60.31 | Öğrenci bilgi sistemi. |
| `ank-proxy` | Sunucu | — | 10.4.64.10 | İnternet çıkış proxy'si. |
| `ank-radius` | Sunucu | — | 10.4.60.3 | Yerel RADIUS. Tünel kopsa da kampüs 802.1X çalışır. |
| `ank-waf-1` | Sunucu | — | 10.4.70.12 | WAF düğümü 1. |
| `ank-waf-2` | Sunucu | — | 10.4.70.13 | WAF düğümü 2. |
| `ank-waf-vip` | Sunucu | — | 10.4.70.10 | WAF sanal adresi (VRRP). |
| `ank-yazici` | Sunucu | — | 10.4.80.20 | Yazıcı. |
| `tunel-ankara` | Sunucu | — | 172.31.4.2 | Ankara tünel arayüzü adresi. |
| `ank-ogrenci` | Özet | — | 10.4.128.0/17 | Öğrenci adres rezervi ve kural özeti. VLAN değildir, arayüze atanmaz. Gerçek ağlar VLAN 100-107'dir. |
| `ank-guncelleme-kaynaklari` | Grup | `ank-v60-sunucu`, `ank-v63-veri` | 10.4.60.0/24, 10.4.63.0/26 | Güncellemeyi proxy'den alan sunucu ağları. |
| `ank-izleme-kaynaklari` | Grup | `ank-v60-sunucu`, `ank-v63-veri`, `ank-v64-sinir`, `ank-waf-dugumleri`, `ank-lms-uyg` | 10.4.60.0/24, 10.4.63.0/26, 10.4.64.0/26, 10.4.70.12, 10.4.70.13, 10.4.70.11 | Zabbix aracısı veri gönderen sunucular. |
| `ank-kurumsal` | Grup | `ank-v20-personel`, `ank-v30-yazilim`, `ank-v50-teknik`, `ank-v90-hoca` | 10.4.20.0/22, 10.4.30.0/27, 10.4.50.0/25, 10.4.88.0/21 | İnternete denetimli çıkan kurum ağları. |
| `ank-lms-istemcileri` | Grup | `ank-v20-personel`, `ank-v90-hoca`, `ank-ogrenci`, `ank-v110-lab` | 10.4.20.0/22, 10.4.88.0/21, 10.4.128.0/17, 10.4.110.0/23 | Kampüsten LMS kullanan ağlar. |
| `ank-log-hedefi` | Grup | `wazuh` | 10.1.61.10 | Ankara'nın log hedefi. |
| `ank-log-kaynaklari` | Grup | `ank-v10-yonetim`, `ank-v60-sunucu`, `ank-v63-veri`, `ank-v64-sinir`, `ank-waf-dugumleri`, `ank-lms-uyg` | 10.4.10.0/26, 10.4.60.0/24, 10.4.63.0/26, 10.4.64.0/26, 10.4.70.12, 10.4.70.13, 10.4.70.11 | Logları Wazuh'a giden cihaz ve sunucular. |
| `ank-ogrenci-ve-misafir` | Grup | `ank-ogrenci`, `ank-v85-misafir` | 10.4.128.0/17, 10.4.85.0/24 | İç ağa geçemeyen ağlar. |
| `ank-waf-dugumleri` | Grup | `ank-waf-1`, `ank-waf-2` | 10.4.70.12, 10.4.70.13 | Logları ve izleme verisini gönderen gerçek WAF adresleri. |
| `ank-yazici-istemcileri` | Grup | `ank-v20-personel`, `ank-v30-yazilim`, `ank-v40-arge`, `ank-v50-teknik`, `ank-v90-hoca`, `ank-v110-lab` | 10.4.20.0/22, 10.4.30.0/27, 10.4.40.0/26, 10.4.50.0/25, 10.4.88.0/21, 10.4.110.0/23 | Yazıcı kullanan ağlar. |
| `ank-yonetilen-sunucular` | Grup | `ank-v60-sunucu`, `ank-v64-sinir`, `ank-v70-dmz` | 10.4.60.0/24, 10.4.64.0/26, 10.4.70.0/26 | Teknik ekibin yönettiği sunucu ağları. |
| `ank-yonetim-erisimi` | Grup | `ank-v10-yonetim` | 10.4.10.0/26 | Bu güvenlik duvarının arkasındaki yönetim ağı. |
| `wan-ankara` | Girdi | — | Kurulum girdisi, tanımlı değil | Ankara güvenlik duvarı WAN adresi. Operatörden alınacak gerçek adres burada tanımlanmaz, kurulum girdisidir. |
