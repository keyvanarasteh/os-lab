# Doğu Teknoloji

> Bu tasarım, Doğu Teknoloji’nin çok şubeli kurumsal ağ ve güvenlik duvarı mimarisini anlatır. Şirketin merkez ve şubelerindeki çalışanlar, yazılım ekipleri, Ar-Ge, misafir ağları ve sunucu katmanları ayrı VLAN’lara ayrılmıştır. Her şubede güvenlik duvarı, iç ağ ve yönetsel erişim politikaları belirli bir iş akışına göre tasarlanmıştır.

## Şirket

Doğu Teknoloji, bilişim, yazılım geliştirme, üretim destek ve dijital dönüşüm hizmetleri sunan çok uluslu bir teknoloji şirketidir. Mersin merkez, Adana ve İstanbul şubeleri ile Hamburg’daki Almanya ofisi, kurumsal üretim ve operasyonel verimliliği destekler. Şirketin ortak hedefi, çalışanların iş akışı içerisinde güvenli ama hızlı erişim elde etmesi, yazılım ekiplerinin hızlı geliştirme yapması ve misafir / ziyaretçi ağlarının ayrı tutulmasıdır.

## Ağ ve VLAN düşüncesi

Her şubede ağ planı aynı mantıkla kurulmuştur:
- Çalışanlar, Ar-Ge, yazılım ekibi ve sunucular ayrı VLAN’lara ayrılır.
- Misafir ağı dışarıdan gelen kullanıcılar için ayrı tutulur.
- Yönetim ağı yalnızca VPN üzerinden erişilir.
- DMZ katmanı, internetten erişilen web ve portal servislerini barındırır.
- Şube içindeki tüm kritik hizmetler, iç ağdan ancak kısıtlı port ve protokol erişimi ile ulaşılacak şekilde tasarlanmıştır.

Örnek olarak Mersin merkezde `10.10.0.0/16` ağ kapsamı kullanılmıştır. Şube yönetim, misafir ve DMZ katmanları ayrı alt ağı olarak ayrılmıştır. Bu, R&D ve yazılım ekiplerinin aynı fiziksel erişim katmanında bir arada tutulmaması için gereklidir.

## Bant genişliği ve işletme mantığı

- Mersin merkez: 2 Gbps / 2 Gbps
- Adana şube: 1.2 Gbps / 1.2 Gbps
- İstanbul şube: 2 Gbps / 2 Gbps
- Almanya şube: 1.2 Gbps / 1.2 Gbps

Bu bağlantı hızları, kurumsal ERP, video toplantı, e-posta, git ve CI/CD kullanımına göre belirlenmiştir. Özellikle İstanbul merkezi ve Mersin merkezde büyük yazılım ekibi ve üst düzey kurumsal iş yükü olduğu için 2 Gbps hattın seçimi daha uygun görülmüştür. Bu değerler, normal iş yükü ve güvenlik filtreleri açıkken de dinamik performans sağlamayı hedefler.

## Ürün seçimi

Merkez ve büyük şubelerde FortiGate 200F seçilmiştir. Bu cihaz, 2 Gbps hattı ve IPS/UTM tabanlı güvenlik filtreleri ile birlikte iyi bir tampon sunar. 2 Gbps seviyedeki bir hat üzerinde, güvenlik servisleri açıkken yalnızca temel firewall değil, UTM ve IPS tabanlı koruma da gerektiği için ürünün bazı rakiplerine göre daha güçlü operasyonel yönetimi ve tek merkezli kontrol yeteneği avantaj oluşturmaktadır.

Alt segmentlerde:
- Mersin ve İstanbul için: FortiGate 200F
- Adana ve Almanya için: FortiGate 100F
- Seçilen ürünler genel olarak Fortinet’in kurumsal yönetim, SD-WAN ve merkezi izleme araçlarıyla uyumludur.

Alternatifler arasında Palo Alto, Sophos, Check Point ve pfSense seçenekleri değerlendirilmiştir. FortiGate, tüm şubelerde tek bir yönetim anlayışı sunması, güvenlik özellikleri ve kurumsal destek nedeniyle tercih edilmiştir. pfSense daha uygun fiyatlı görünse de kurumsal operasyonel denetim, lisans ve destek açısından daha zayıf kalmaktadır.

## Uzaktan erişim ve izleme

- Yönetim erişimi: yalnızca role-based VPN + bastion
- Public SSH: açık değil
- Yönetici erişimi: MFA ve rol tabanlı yetkilendirme
- Tüm güvenlik olayları merkez SIEM’e iletilir
- Yüksek öncelikli bloklar ve güvenlik olayları Telegram kanalı üzerinden bildirilir

Bu yaklaşım, dışarıdan gelen erişim noktalarının azaltılması ve yönetsel erişimde yalnızca yetkilendirilmiş kullanıcıların kalmasını sağlar. Ayrıca uygulama servisleri ve güvenlik olayları birbirinden ayrılır; operasyon ekibi servis durumu ile uğraşırken, güvenlik ekibi blok, yetki ve IPS olaylarına odaklanır.

## CVE izleme

Bir bonus olarak, güvenlik duvarı ve web katmanı için açık web uygulama zafiyetleri takip edilir. Ancak güvenlik duvarı tek başına uygulama katmanındaki güvenlik açıklarını tamamen kapatamaz. Bu nedenle, web uygulama ve PHP stack sürümleri düzenli olarak kontrol edilir ve kritik zafiyetler, uygulama geliştiricileriyle birlikte çalışma kapsamında değerlendirilir.

---

Bu şirket tasarımı, kurumsal ağ segmentasyonu, güvenlik duvarı seçimi, DMZ kullanımı, VPN erişimi ve izleme planı ile birlikte baştan sona bir iş ve operasyon tasarımı olarak ele alınmıştır. Amacı, her kuralın neden var olduğunu ve neye karşı koruma sağladığını açıklayan bir şema üretmektir.
