#!/usr/bin/env python3
"""Atlas Holding kural politikası denetimi. Yalnızca standart kütüphane kullanır.

  politika.py dogrula            Nesne, VLAN, kural yapısı ve README tutarlılığı
  politika.py model              Gereksinim testlerini ilk eşleşme modeliyle çalıştırır
  politika.py hepsi              dogrula + model, sonuclar/MODEL.md yazar
  politika.py nft <sube>         company.json'dan lab için nftables kural seti üretir
  politika.py testler            Lab için değerleri çözülmüş test listesi
  politika.py sunucu-nft <ad>    Bir sunucunun sunucu-akislari.json'dan gelen güvenlik duvarı
  politika.py nesneler-md        NESNELER.md dosyasını üretir

Model, company.json'u bir politika olarak değerlendirir. Paket göndermez; IPS, uygulama
tanıma, WAF, HA veya hız sınırı davranışı hakkında bir şey kanıtlamaz.
"""
import ipaddress
import json
import re
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
KOK = LAB.parent
SUBELER = {"istanbul": "ist", "izmir": "izm", "amsterdam": "ams", "ankara-akademik": "ank"}
KISA = {v: k for k, v in SUBELER.items()}
WAN = {"istanbul": "wan-istanbul", "izmir": "wan-izmir", "amsterdam": "wan-amsterdam", "ankara-akademik": "wan-ankara"}
DNAT_443 = {"wan-istanbul": "10.1.70.10", "wan-ankara": "10.4.70.10"}
BLOK = {"istanbul": "10.1.0.0/16", "izmir": "10.2.0.0/16", "amsterdam": "10.3.0.0/16", "ankara-akademik": "10.4.0.0/16"}


def oku_json(ad):
    return json.loads((KOK / ad).read_text(encoding="utf-8"))


def ag_mi(x):
    try:
        ipaddress.ip_network(x, strict=False)
        return True
    except ValueError:
        return False


def ip(x):
    return ipaddress.ip_network(x, strict=False)


def fqdn_mi(x):
    return bool(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", x)) and not ag_mi(x)


def kural_no(not_):
    return not_.split(":", 1)[0].strip()


def cevre_kurallari(d, sube):
    b = next(x for x in d["branches"] if x["id"] == sube)
    return next(f for f in b["firewalls"] if f["segment"] == "perimeter")["rules"]


# ------------------------------------------------------------------ nesneler
class Envanter:
    def __init__(self):
        veri = oku_json("nesneler.json")
        self.liste = veri["nesneler"]
        self.ad = {n["ad"]: n for n in self.liste}

    def coz(self, ad, _yigin=()):
        if ad in _yigin:
            raise ValueError(f"döngülü grup: {ad}")
        n = self.ad[ad]
        if n["tur"] in ("ozel", "girdi"):
            return [ad]
        if n["tur"] == "grup":
            out = []
            for u in n["uyeler"]:
                out += self.coz(u, _yigin + (ad,))
            return out
        return list(n["uyeler"])

    def somut_degerler(self):
        out = set()
        for n in self.liste:
            if n["tur"] in ("ag", "host", "ozet", "fqdn"):
                out.update(n["uyeler"])
            elif n["tur"] in ("girdi", "ozel"):
                out.add(n["ad"])
        return out


# ------------------------------------------------------------------ model
def yerel_sube(adres):
    if not ag_mi(adres):
        return None
    a = ip(adres)
    for sube, blok in BLOK.items():
        if a.subnet_of(ip(blok)):
            return sube
    return None


def internet_mi(adres):
    """Şirketin özel adres alanında olmayan her adres internettir."""
    if adres.startswith("wan-") or fqdn_mi(adres):
        return True
    if not ag_mi(adres):
        return False
    return not any(ip(adres).subnet_of(ip(o)) for o in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def eslesir_adres(kural_degeri, adres, taraf):
    if kural_degeri is None or kural_degeri == "any":
        return True
    if kural_degeri == "internet":
        return internet_mi(adres)
    if kural_degeri.startswith("wan-") or fqdn_mi(kural_degeri):
        return kural_degeri == adres
    if not ag_mi(adres):
        return False
    return ip(adres).subnet_of(ip(kural_degeri))


def eslesir_port(kural_port, port):
    if kural_port is None:
        return True
    k = str(kural_port)
    if ":" in k:
        a, b = k.split(":")
        return int(a) <= port <= int(b)
    return int(k) == port


def degerlendir(kurallar, yon, kaynak, hedef, proto, port):
    """İlk eşleşen satırı döndürür."""
    for i, r in enumerate(kurallar):
        if r.get("direction", "in") != yon:
            continue
        if r.get("proto", "any") not in ("any", proto):
            continue
        if not eslesir_port(r.get("port"), port):
            continue
        if eslesir_adres(r.get("from"), kaynak, "kaynak") and eslesir_adres(r.get("to"), hedef, "hedef"):
            return i, r
    return None, None


TUNEL_MERKEZ = {"172.31.2.1": "izmir", "172.31.3.1": "amsterdam", "172.31.4.1": "ankara-akademik"}
TUNEL_SUBE = {"172.31.2.2", "172.31.3.2", "172.31.4.2"}


def yol(kaynak, hedef, proto, port):
    """Trafiğin geçtiği güvenlik duvarları: [(sube, yon, hedef_adres)]."""
    if hedef.startswith("wan-"):
        sube = next(s for s, w in WAN.items() if w == hedef)
        if proto == "tcp" and port == 443 and hedef in DNAT_443 and not kaynak.startswith("wan-"):
            return [(sube, "forward", DNAT_443[hedef])]
        return [(sube, "in", hedef)]
    if kaynak in TUNEL_MERKEZ:  # merkez tünel ucundan çıkan trafik karşı güvenlik duvarına gelir
        return [(TUNEL_MERKEZ[kaynak], "forward", hedef)]
    if kaynak in TUNEL_SUBE:  # şube tünel ucundan çıkan trafik merkeze gelir
        return [("istanbul", "forward", hedef)]
    ks, hs = yerel_sube(kaynak), yerel_sube(hedef)
    if ks and not hs:
        return [(ks, "forward", hedef)]
    if hs and not ks:
        return [(hs, "forward", hedef)]
    if ks == hs:
        return [(ks, "forward", hedef)]
    duraklar = [ks]
    if "istanbul" not in (ks, hs):
        duraklar.append("istanbul")  # şubeler arası yönlendirme merkezden geçer
    duraklar.append(hs)
    return [(s, "forward", hedef) for s in duraklar]


def akis(d, kaynak, hedef, proto, port, kural_kaynagi=None):
    """Sonuç, karar veren kurallar."""
    kural_kaynagi = kural_kaynagi or (lambda sube: cevre_kurallari(d, sube))
    kararlar = []
    for sube, yon, hedef_adres in yol(kaynak, hedef, proto, port):
        _, r = degerlendir(kural_kaynagi(sube), yon, kaynak, hedef_adres, proto, port)
        if r is None:
            kararlar.append(f"{SUBELER[sube]}:eslesme-yok")
            return "red", kararlar
        kararlar.append(f"{SUBELER[sube]}:{kural_no(r['note'])}")
        if r["action"] == "deny":
            return "red", kararlar
        if r["action"] == "reject":
            return "reject", kararlar
    return "izin", kararlar


def testleri_oku():
    out = []
    for satir in (LAB / "gereksinimler.txt").read_text(encoding="utf-8").splitlines():
        if not satir.strip() or satir.startswith("#"):
            continue
        p = satir.split("|")
        if len(p) != 9:
            raise ValueError(f"hatalı test satırı: {satir}")
        out.append(dict(no=p[0], kaynak_ad=p[1], kaynak=p[2], hedef_ad=p[3], hedef=p[4], proto=p[5],
                        port=int(p[6]), beklenen=p[7], aciklama=p[8]))
    return out


# ------------------------------------------------------------------ yapısal denetimler
def denetle_envanter(env, d, hatalar):
    gorulen = set()
    for n in env.liste:
        if n["ad"] in gorulen:
            hatalar.append(f"yinelenen nesne: {n['ad']}")
        gorulen.add(n["ad"])
        t = n["tur"]
        if t in ("ag", "ozet"):
            for u in n["uyeler"]:
                if "/" not in u or not ag_mi(u):
                    hatalar.append(f"{n['ad']}: geçersiz CIDR {u}")
        if t == "host":
            for u in n["uyeler"]:
                if "/" in u or not ag_mi(u):
                    hatalar.append(f"{n['ad']}: geçersiz IP {u}")
        if t == "fqdn":
            for u in n["uyeler"]:
                if not fqdn_mi(u):
                    hatalar.append(f"{n['ad']}: geçersiz FQDN {u}")
        if t == "grup":
            for u in n["uyeler"]:
                if u not in env.ad:
                    hatalar.append(f"{n['ad']}: tanımsız üye {u}")
        if t == "girdi" and (n["uyeler"] or n["durum"] != "girdi-gerekli"):
            hatalar.append(f"{n['ad']}: gerçek değer burada tutulmaz, durum girdi-gerekli olmalı")
    for n in env.liste:
        if n["tur"] == "grup":
            try:
                env.coz(n["ad"])
            except (KeyError, ValueError) as e:
                hatalar.append(f"{n['ad']}: çözülemedi: {e}")
    somut = env.somut_degerler()
    for b in d["branches"]:
        for f in b["firewalls"]:
            for r in f["rules"]:
                for alan in ("from", "to"):
                    v = r.get(alan)
                    if v is not None and v not in somut:
                        hatalar.append(f"{b['id']}/{f['segment']}: envanterde olmayan {alan} değeri: {v}")


def denetle_vlan(env, d, hatalar):
    for b in d["branches"]:
        s = SUBELER[b["id"]]
        blok = ip(b["network"]["cidr"])
        ag_listesi = []
        for v in b["network"]["vlans"]:
            a = ip(v["cidr"])
            if not a.subnet_of(blok):
                hatalar.append(f"{b['id']} VLAN {v['id']}: {a} şube bloğu dışında")
            ag_listesi.append((v["id"], a))
            ad = [n for n in env.liste if n["ad"].startswith(f"{s}-v{v['id']}-") and n["tur"] == "ag"]
            if len(ad) != 1 or ad[0]["uyeler"] != [v["cidr"]]:
                hatalar.append(f"{b['id']} VLAN {v['id']}: nesne envanteriyle uyuşmuyor")
        for i, (va, a) in enumerate(ag_listesi):
            for vb, c in ag_listesi[i + 1:]:
                if a.overlaps(c):
                    hatalar.append(f"{b['id']}: VLAN {va} ile {vb} çakışıyor")
        for n in env.liste:
            m = re.fullmatch(rf"{s}-v(\d+)-.*", n["ad"])
            if m and n["tur"] == "ag" and int(m.group(1)) not in [v for v, _ in ag_listesi]:
                hatalar.append(f"{n['ad']}: company.json'da VLAN yok")
    # Topoloji
    for satir in (LAB / "topoloji.txt").read_text(encoding="utf-8").splitlines():
        if not satir.strip() or satir.startswith("#"):
            continue
        s, ad, cidr, gecit, hostlar = satir.split("|")
        if ad.startswith("vpn"):
            havuz = {"vpnper": "vpn-personel", "vpngel": "vpn-gelistirici", "vpnyon": "vpn-yonetici", "vpnhoc": "vpn-hoca"}[ad]
            if env.ad[havuz]["uyeler"] != [cidr]:
                hatalar.append(f"topoloji {ad}: envanterle uyuşmuyor")
            continue
        b = next(x for x in d["branches"] if x["id"] == KISA[s])
        if not any(v["cidr"] == cidr and f"v{v['id']}" == ad for v in b["network"]["vlans"]):
            hatalar.append(f"topoloji {s}-{ad} {cidr}: company.json'da yok")
        for h in hostlar.split(","):
            if ipaddress.ip_address(h) not in ip(cidr):
                hatalar.append(f"topoloji {s}-{ad}: {h} alt ağ dışında")


def denetle_ogrenci(env, d, hatalar, rapor):
    b = next(x for x in d["branches"] if x["id"] == "ankara-akademik")
    ozet = ip(env.ad["ank-ogrenci"]["uyeler"][0])
    alt = [(v["id"], ip(v["cidr"]), v) for v in b["network"]["vlans"] if 100 <= v["id"] <= 107]
    if len(alt) != 8 or any(a.prefixlen != 20 or not a.subnet_of(ozet) for _, a, _ in alt):
        hatalar.append("öğrenci ağı: 10.4.128.0/17 içinde tam 8 adet /20 VLAN olmalı")
    if sorted(a for _, a, _ in alt) != sorted(ozet.subnets(new_prefix=20)):
        hatalar.append("öğrenci ağı: /20 VLAN'lar /17 bloğunu tam olarak bölmüyor")
    if any(v["cidr"] == str(ozet) for v in b["network"]["vlans"]):
        hatalar.append("öğrenci ağı: /17 hem rezerv hem VLAN olarak kullanılamaz")
    toplam = 0
    for vid, a, v in alt:
        m = re.search(r"Ağ geçidi (\S+), ayrılmış (\S+)-(\S+), DHCP havuzu (\S+)-([\d.]+), kullanılabilir ([\d.]+) adres", v["note"])
        if not m:
            hatalar.append(f"VLAN {vid}: notta ağ geçidi, ayrılmış aralık ve havuz yok")
            continue
        gecit, _, _, h1, h2, kap = m.groups()
        taban = str(a.network_address).rsplit(".", 1)[0]
        ayr_son = f"{taban}.{m.group(3)}"
        h1i, h2i = int(ipaddress.ip_address(h1)), int(ipaddress.ip_address(h2))
        adet = h2i - h1i + 1
        if ipaddress.ip_address(gecit) not in a or ipaddress.ip_address(h1) not in a or ipaddress.ip_address(h2) not in a:
            hatalar.append(f"VLAN {vid}: ağ geçidi veya havuz alt ağ dışında")
        if ipaddress.ip_address(gecit) >= ipaddress.ip_address(h1):
            hatalar.append(f"VLAN {vid}: ağ geçidi havuzun içinde")
        if h2i == int(a.broadcast_address) or h1i == int(a.network_address):
            hatalar.append(f"VLAN {vid}: havuz ağ veya yayın adresini içeriyor")
        if adet != int(kap.replace(".", "")):
            hatalar.append(f"VLAN {vid}: notta {kap} yazıyor, hesap {adet}")
        toplam += adet
    bugun, buyume = 25000, 32500
    rapor.append(("Öğrenci DHCP havuzu (8 VLAN)", f"{toplam} adres"))
    rapor.append(("Bugünkü hedef 25.000 cihaz", f"%{bugun / toplam * 100:.1f}"))
    rapor.append(("Büyüme hedefi 32.500 cihaz", f"%{buyume / toplam * 100:.2f}, kalan {toplam - buyume} adres"))
    if toplam < buyume:
        hatalar.append(f"öğrenci ağı: {toplam} adres büyüme hedefi {buyume} için yetmiyor")
    for rezerv in ("10.4.112.0/20", "10.4.96.0/21"):
        for v in b["network"]["vlans"]:
            if ip(rezerv).overlaps(ip(v["cidr"])):
                hatalar.append(f"rezerv {rezerv} VLAN {v['id']} ile çakışıyor")


def kapsar(a, b):
    """a satırı b satırının bütün trafiğini kapsıyor mu?"""
    if a.get("direction") != b.get("direction"):
        return False
    if a.get("proto", "any") not in ("any", b.get("proto", "any")):
        return False
    if a.get("port") is not None:
        if b.get("port") is None:
            return False
        ap, bp = str(a["port"]), str(b["port"])
        a1, a2 = (ap.split(":") + [ap])[:2] if ":" in ap else (ap, ap)
        b1, b2 = (bp.split(":") + [bp])[:2] if ":" in bp else (bp, bp)
        if not (int(a1) <= int(b1) and int(b2) <= int(a2)):
            return False

    def uc_kapsar(x, y):
        if x is None or x == "any":
            return True
        if y is None or y == "any":
            return False
        if x == y:
            return True
        if x == "internet":
            return fqdn_mi(y)
        if ag_mi(x) and ag_mi(y):
            return ip(y).subnet_of(ip(x))
        return False

    return uc_kapsar(a.get("from"), b.get("from")) and uc_kapsar(a.get("to"), b.get("to"))


def denetle_bicim(d, hatalar):
    """Port biçimi: dersin kural üreticisi virgüllü port için geçersiz kural üretir."""
    for sube in SUBELER:
        for r in cevre_kurallari(d, sube):
            p = r.get("port")
            if p is not None and not re.fullmatch(r"\d+(:\d+)?", str(p)):
                hatalar.append(f"{sube}: virgüllü veya geçersiz port dersin aracında geçersiz kural üretir: {p}")


def denetle_yapi(d, hatalar, rapor):
    for sube in SUBELER:
        kurallar = cevre_kurallari(d, sube)
        son = kurallar[-1]
        if not (son["action"] == "deny" and son.get("proto") == "any" and "from" not in son and "to" not in son and "port" not in son):
            hatalar.append(f"{sube}: son satır varsayılan ret değil")
        if kural_no(son["note"]) != "O7":
            hatalar.append(f"{sube}: son kural O7 değil")
        nolar = [kural_no(r["note"]) for r in kurallar]
        ilk_sube = next(i for i, n in enumerate(nolar) if not n.startswith("O"))
        if any(n.startswith("O") for n in nolar[ilk_sube:-1]):
            hatalar.append(f"{sube}: ortak kural şube kurallarının altında")
        sira = []
        for n in nolar[:ilk_sube]:
            if n not in sira:
                sira.append(n)
        if sira != ["O1", "O2", "O3", "O4", "O5", "O6"]:
            hatalar.append(f"{sube}: ortak kural sırası bozuk: {sira}")
        for r in kurallar:
            p = r.get("port")
            if r.get("proto") == "any" and p is not None:
                hatalar.append(f"{sube}: proto any ile port birlikte kullanılamaz: {r['note'][:40]}")
            if r.get("direction") == "out":
                hatalar.append(f"{sube}: 'out' güvenlik duvarının kendi çıkışıdır, geçen trafik 'forward' olmalı")
            if r.get("direction") == "in" and not str(r.get("to", "")).startswith("wan-"):
                hatalar.append(f"{sube}: 'in' yalnızca güvenlik duvarının kendisine gelen trafik içindir")
        # Gölgelenen satırlar
        for j, b in enumerate(kurallar[:-1]):
            for a in kurallar[:j]:
                if kapsar(a, b) and kural_no(a["note"]) != kural_no(b["note"]):
                    hatalar.append(f"{sube}: kural {kural_no(b['note'])} ({b.get('from')}→{b.get('to')} {b.get('proto')}/{b.get('port')}) "
                                   f"kural {kural_no(a['note'])} tarafından tamamen gölgelenmiş")
                    break
    # Eski kural 5 hatası geri gelmesin
    for r in cevre_kurallari(d, "ankara-akademik"):
        if r["action"] in ("deny", "reject") and r.get("from") == "10.4.128.0/17" and r.get("to") == "internet":
            hatalar.append("Ankara: öğrenciden internete L3/L4 ret satırı var. P2P engeli uygulama profilindedir.")


def denetle_iki_uc(d, hatalar, rapor):
    """Bir şubeler arası izin yazılmışsa akış uçtan uca geçmelidir; tek taraflı izin işe yaramaz."""
    sayi = 0
    for sube in SUBELER:
        for r in cevre_kurallari(d, sube):
            if r["action"] not in ("allow", "limit") or r.get("direction") != "forward":
                continue
            k, h = r.get("from"), r.get("to")
            if not k or not h or not ag_mi(k) or not ag_mi(h):
                continue
            ks, hs = yerel_sube(k), yerel_sube(h)
            if not ks or not hs or ks == hs:
                continue
            # Ağdan örnek bir adres seçilir
            k_ip = str(next(ip(k).hosts(), ip(k).network_address)) if ip(k).num_addresses > 1 else k
            h_ip = str(next(ip(h).hosts(), ip(h).network_address)) if ip(h).num_addresses > 1 else h
            sonuc, kararlar = akis(d, k_ip, h_ip, r["proto"], int(r.get("port", 0)))
            sayi += 1
            if sonuc != "izin":
                hatalar.append(f"tek taraflı izin: {k}→{h} {r['proto']}/{r.get('port')} ({sube} {kural_no(r['note'])}) uçtan uca geçmiyor: {kararlar}")
    rapor.append(("Şubeler arası izin satırı, iki uçta doğrulandı", str(sayi)))


SERVIS = re.compile(r"(tcp|udp)/(\d+(?::\d+)?)|tümü")


def tablo_satirlari(metin, baslik):
    """Başlıktan sonraki ilk kural tablosunun satırlarını döndürür."""
    i = metin.find(baslik)
    if i < 0:
        return None
    out = []
    icinde = False
    for s in metin[i:].splitlines():
        if s.startswith("| No |"):
            icinde = True
            continue
        if icinde:
            if not s.startswith("|"):
                break
            if s.startswith("|---"):
                continue
            hucre = [h.strip() for h in s.strip().strip("|").split(" | ")]
            out.append(hucre)
    return out


def tablo_acilim(env, satirlar, on_ek):
    eylem = {"İzin": "allow", "Hız sınırı": "limit", "Red": "deny", "Reject": "reject"}
    out = []
    for h in satirlar:
        no, kay, hed, srv, isl = h[0], h[1], h[2], h[3], h[4]
        kaynaklar = [x.replace("<s>", on_ek) for x in re.findall(r"`([^`]+)`", kay)]
        hedefler = [x.replace("<s>", on_ek) for x in re.findall(r"`([^`]+)`", hed)]
        act = eylem[isl.split(",")[0].strip()]
        servisler = []
        for m in SERVIS.finditer(srv):
            servisler.append(("any", None) if m.group(0) == "tümü" else (m.group(1), m.group(2)))
        for k in kaynaklar:
            for t in hedefler:
                for ks in env.coz(k):
                    for ts in env.coz(t):
                        for p, port in servisler:
                            out.append((no, act, ks, ts, p, port))
    return out


def json_acilim(kurallar):
    out = []
    for r in kurallar:
        out.append((kural_no(r["note"]), r["action"], r.get("from", "any"), r.get("to", "any"),
                    r.get("proto", "any"), None if r.get("port") is None else str(r["port"])))
    return out


def denetle_readme(env, d, hatalar, rapor):
    ana = (KOK / "README.md").read_text(encoding="utf-8")
    ortak = tablo_satirlari(ana, "## 6. Ortak kurallar")
    if not ortak:
        hatalar.append("README: ortak kural tablosu bulunamadı")
        return
    dosyalar = {"istanbul": "01-istanbul", "izmir": "02-izmir", "amsterdam": "03-amsterdam", "ankara-akademik": "04-ankara-akademik"}
    toplam = 0
    for sube, klasor in dosyalar.items():
        s = SUBELER[sube]
        metin = (KOK / klasor / "README.md").read_text(encoding="utf-8")
        tablo = tablo_satirlari(metin, "## Kural seti")
        if tablo is None:
            hatalar.append(f"{klasor}: kural tablosu yok")
            continue
        o_satir = [h for h in ortak if h[0] != "O7"]
        o7 = [h for h in ortak if h[0] == "O7"]
        beklenen = tablo_acilim(env, o_satir + tablo + o7, s)
        gercek = json_acilim(cevre_kurallari(d, sube))
        toplam += len(gercek)
        if beklenen != gercek:
            for i, (a, b) in enumerate(zip(beklenen, gercek)):
                if a != b:
                    hatalar.append(f"{klasor}: README ile company.json {i + 1}. satırda ayrılıyor: README {a} / JSON {b}")
                    break
            else:
                hatalar.append(f"{klasor}: README {len(beklenen)} satır, company.json {len(gercek)} satır")
        # VLAN tabloları
        b = next(x for x in d["branches"] if x["id"] == sube)
        readme_vlan = {}
        for satir in metin.splitlines():
            m = re.match(r"\|\s*(\d+)\s*\|.*?(\d+\.\d+\.\d+\.\d+/\d+)", satir)
            if m:
                readme_vlan[int(m.group(1))] = m.group(2)
        for v in b["network"]["vlans"]:
            if readme_vlan.get(v["id"]) != v["cidr"]:
                hatalar.append(f"{klasor}: VLAN {v['id']} README'de {readme_vlan.get(v['id'])}, company.json'da {v['cidr']}")
    rapor.append(("README tablolarından açılan kural satırı, company.json ile aynı", str(toplam)))

    # Eski adresler ve tanımsız nesneler
    hostlar = {u for n in env.liste if n["tur"] == "host" for u in n["uyeler"]}
    aglar = {u for n in env.liste if n["tur"] in ("ag", "ozet") for u in n["uyeler"]}
    izinli_ag = {"10.4.112.0/20", "10.4.96.0/21"}
    sunucu_aglari = [ip(u) for n in env.liste if re.search(r"-v(60|61|63|64|70|80)-", n["ad"]) for u in n["uyeler"]]
    belgeler = [KOK / "README.md", KOK / "waf" / "README.md"] + [KOK / k / "README.md" for k in dosyalar.values()]
    adlar = set(env.ad)
    for yol_ in belgeler:
        if not yol_.exists():
            continue
        m_ = yol_.read_text(encoding="utf-8")
        for adres in set(re.findall(r"\b10\.\d+\.\d+\.\d+/\d+\b", m_)):
            if adres not in aglar and adres not in izinli_ag:
                hatalar.append(f"{yol_.relative_to(KOK)}: envanterde olmayan ağ {adres}")
        for adres in set(re.findall(r"\b10\.\d+\.\d+\.\d+\b(?!/)", m_)):
            a = ipaddress.ip_address(adres)
            if adres not in hostlar and any(a in n for n in sunucu_aglari):
                hatalar.append(f"{yol_.relative_to(KOK)}: envanterde olmayan sunucu adresi {adres}")
        # Tablolarda geçen nesne adları tanımlı olmalı
        for satir in m_.splitlines():
            if satir.startswith("|"):
                for ad in re.findall(r"`((?:ist|izm|ams|ank|vpn|wan|sube|onayli|yonetim|tunel)-[a-z0-9-]+)`", satir):
                    if ad not in adlar:
                        hatalar.append(f"{yol_.relative_to(KOK)}: tanımsız nesne `{ad}`")

    # Maliyet toplamı
    satirlar = re.findall(r"\| (FG-\S+) \| (\S+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|", ana)
    if not satirlar:
        hatalar.append("README: maliyet tablosu bulunamadı")
    else:
        sayi = lambda t: int(t.replace(".", ""))
        don = sum(sayi(x[2]) for x in satirlar)
        ha_don = sum(sayi(x[3]) for x in satirlar)
        paket = sum(sayi(x[4]) for x in satirlar)
        ha_paket = sum(sayi(x[5]) for x in satirlar)
        for x in satirlar:
            if sayi(x[3]) != 2 * sayi(x[2]) or sayi(x[5]) != 2 * sayi(x[4]):
                hatalar.append(f"README maliyet: {x[0]} HA tutarı tek cihazın iki katı değil")
        if ha_paket != 295880:
            hatalar.append(f"README maliyet: HA paket toplamı {ha_paket}, 295.880 bekleniyor")
        if f"{ha_don:,}".replace(",", ".") not in ana:
            hatalar.append(f"README maliyet: donanım toplamı {ha_don} metinde yok")
        rapor.append(("HA çifti toplamı: yalnızca donanım / donanım + 3 yıl paket", f"{ha_don} / {ha_paket} USD"))

    # Fiyat anlamı
    for b in d["branches"]:
        for f in b["firewalls"]:
            if "HA çifti" in f["chosen"]["product"]:
                hatalar.append(f"{b['id']}: ürün adında HA çifti var, priceUsd tek cihazdır")

    # NGFW profilleri
    prof = oku_json("ngfw-profilleri.json")["profiller"]
    prof_ad = {p["ad"] for p in prof}
    for p in prof:
        for hedef in p["uygulandigiKurallar"]:
            sube, no = hedef.split(":")
            if no not in {kural_no(r["note"]) for r in cevre_kurallari(d, sube)}:
                hatalar.append(f"{p['ad']}: {hedef} kuralı yok")
            klasor = dosyalar[sube]
            tablo = tablo_satirlari((KOK / klasor / "README.md").read_text(encoding="utf-8"), "## Kural seti") or []
            satir = [h for h in tablo if h[0] == no]
            if not satir or f"`{p['ad']}`" not in satir[0][4]:
                hatalar.append(f"{p['ad']}: {klasor} kural {no} README'de bu profili göstermiyor")
    # Sunucu akışları
    akislar = oku_json("sunucu-akislari.json")["ayniVlanIzinleri"]
    for a in akislar:
        for alan in ("vlan", "kaynak", "hedef"):
            if a[alan] not in env.ad:
                hatalar.append(f"sunucu-akislari: tanımsız nesne {a[alan]}")
        v = ip(env.ad[a["vlan"]]["uyeler"][0])
        for alan in ("kaynak", "hedef"):
            if a[alan] in env.ad:
                for u in env.coz(a[alan]):
                    if ipaddress.ip_address(u) not in v:
                        hatalar.append(f"sunucu-akislari: {a[alan]} {a['vlan']} içinde değil")
    # NESNELER.md güncel mi
    if (KOK / "NESNELER.md").read_text(encoding="utf-8") != nesneler_md(env):
        hatalar.append("NESNELER.md güncel değil: politika.py nesneler-md çalıştırın")


def dogrula(sessiz=False):
    env, d = Envanter(), oku_json("company.json")
    hatalar, rapor = [], []
    denetle_envanter(env, d, hatalar)
    denetle_bicim(d, hatalar)
    if hatalar:  # Adres veya port biçimi bozuksa sonraki hesaplar anlamsızdır
        if not sessiz:
            for h in hatalar:
                print(f"HATA: {h}")
            print(f"Yapısal denetim: {len(hatalar)} hata.")
        return hatalar, rapor
    denetle_vlan(env, d, hatalar)
    denetle_ogrenci(env, d, hatalar, rapor)
    denetle_yapi(d, hatalar, rapor)
    denetle_iki_uc(d, hatalar, rapor)
    denetle_readme(env, d, hatalar, rapor)
    if not sessiz:
        for a, b in rapor:
            print(f"  {a}: {b}")
        for h in hatalar:
            print(f"HATA: {h}")
        print(f"Yapısal denetim: {len(hatalar)} hata.")
    return hatalar, rapor


# ------------------------------------------------------------------ model testleri
def model_calistir(kural_kaynagi=None, d=None):
    d = d or oku_json("company.json")
    out = []
    for t in testleri_oku():
        sonuc, kararlar = akis(d, t["kaynak"], t["hedef"], t["proto"], t["port"], kural_kaynagi)
        out.append({**t, "gercek": sonuc, "kararlar": kararlar, "gecti": sonuc == t["beklenen"]})
    return out


def mutasyonlar(d):
    """README'nin sıra iddiaları ve eski kural 5 hatası: bozulunca hangi testler kalıyor?"""
    ank = cevre_kurallari(d, "ankara-akademik")
    ist = cevre_kurallari(d, "istanbul")
    ilk = lambda kurallar, no: next(i for i, r in enumerate(kurallar) if kural_no(r["note"]) == no)
    eski5 = {"action": "deny", "direction": "forward", "proto": "any", "from": "10.4.128.0/17", "to": "internet",
             "note": "5e: eski kural"}

    def kaynak(degisen, liste):
        return lambda sube: liste if sube == degisen else cevre_kurallari(d, sube)

    deneyler = []
    i = ilk(ank, "5")
    deneyler.append(("Eski kural 5 geri kondu: öğrenci → internet, portsuz ret",
                     "Web erişimi kesilir", kaynak("ankara-akademik", ank[:i] + [eski5] + ank[i:]), {"G1-09", "G1-10", "G1-11", "G1-12"}))
    i3 = ilk(ank, "3")
    k4 = [r for r in ank if kural_no(r["note"]) == "4"]
    deneyler.append(("Ankara kural 4, kural 3'ün üstüne alındı", "Öğrenciler LMS'e ulaşamaz",
                     kaynak("ankara-akademik", ank[:i3] + k4 + ank[i3:]), {"G1-01", "G1-08"}))
    deneyler.append(("Ankara'da O4 silindi", "İstemciler IP ve DNS alamaz",
                     kaynak("ankara-akademik", [r for r in ank if kural_no(r["note"]) != "O4"]), {"G8-09", "G8-10", "G8-11"}))
    i2 = ilk(ist, "O2")
    o3 = [r for r in ist if kural_no(r["note"]) == "O3"]
    deneyler.append(("İstanbul'da O3, O2'nin üstüne alındı", "Zabbix cihazları okuyamaz",
                     kaynak("istanbul", ist[:i2] + o3 + ist[i2:]), {"G5-06", "G5-07"}))
    i17 = ilk(ist, "4")
    deneyler.append(("İstanbul kural 4 silindi: şube personeli için merkez izni yok", "Şube izni tek başına yetmez",
                     kaynak("istanbul", [r for r in ist if kural_no(r["note"]) != "4"]), {"G7-01", "G7-02", "G7-03"}))
    out = []
    for ad, iddia, kk, beklenen_kalan in deneyler:
        sonuc = model_calistir(kk, d)
        kalan = {t["no"] for t in sonuc if not t["gecti"]}
        out.append({"ad": ad, "iddia": iddia, "beklenen": sorted(beklenen_kalan), "kalan": sorted(kalan),
                    "dogrulandi": beklenen_kalan <= kalan})
    return out


def kapsam(d, sonuc):
    """Numaralı kuralların her biri en az bir testte karar verdi mi?"""
    kararlar = {x for t in sonuc for x in t["kararlar"]}
    out = []
    for sube, s in SUBELER.items():
        nolar = []
        for r in cevre_kurallari(d, sube):
            n = kural_no(r["note"])
            if n not in nolar:
                nolar.append(n)
        eksik = [n for n in nolar if f"{s}:{n}" not in kararlar]
        out.append((sube, len(nolar), len(nolar) - len(eksik), eksik))
    return out


def model_raporu():
    env, d = Envanter(), oku_json("company.json")
    hatalar, rapor = dogrula(sessiz=True)
    if hatalar and not rapor:
        for h in hatalar:
            print(f"HATA: {h}")
        print("Biçim hataları düzeltilmeden model çalıştırılmaz.")
        return 1
    sonuc = model_calistir(d=d)
    gecen = sum(t["gecti"] for t in sonuc)
    mut = mutasyonlar(d)
    kap = kapsam(d, sonuc)
    (LAB / "sonuclar").mkdir(exist_ok=True)
    y = ["# Model sonuçları", "",
         "Bu dosyayı `lab/politika.py hepsi` üretir, elle düzenlenmez.", "",
         "Model, `company.json` kurallarını ilk eşleşme mantığıyla **hesaplar, paket göndermez**. "
         "Kuralların tutarlılığını gösterir. IPS, uygulama tanıma, WAF, HA, hız sınırı veya FortiGate davranışı hakkında bir şey kanıtlamaz. "
         "Gerçek paket testleri ayrı rapordadır: [PAKET.md](PAKET.md).", "",
         "## Özet", "", "| Denetim | Sonuç |", "|---|---:|",
         f"| Yapısal ve tutarlılık hatası | {len(hatalar)} |",
         f"| Gereksinim testleri | {gecen} / {len(sonuc)} |",
         f"| Bozma deneyleri: test kaldı | {sum(m['dogrulandi'] for m in mut)} / {len(mut)} |"]
    for a, b in rapor:
        y.append(f"| {a} | {b} |")
    y += ["", "## Yapısal hatalar", ""]
    y += [f"- {h}" for h in hatalar] or ["Yok."]
    kalan = [t for t in sonuc if not t["gecti"]]
    y += ["", "## Kalan testler", ""]
    if kalan:
        y += ["| No | Akış | Beklenen | Model | Karar veren kural |", "|---|---|---|---|---|"]
        y += [f"| {t['no']} | {t['aciklama']} | {t['beklenen']} | {t['gercek']} | {' '.join(t['kararlar'])} |" for t in kalan]
    else:
        y.append("Yok.")
    y += ["", "## Kural kapsamı", "", "Numaralı her kuralın en az bir testte karar verip vermediğini gösterir. Bir kuralın sınanması, o kuralın doğru olduğunu tek başına kanıtlamaz.", "",
          "| Güvenlik duvarı | Numaralı kural | Karar veren | Hiç karar vermeyen |", "|---|---:|---:|---|"]
    y += [f"| {a} | {b} | {c} | {', '.join(e) or 'yok'} |" for a, b, c, e in kap]
    y += ["", "## Bozma deneyleri", "",
          "Kurallar bellekte bozulur, testlerin bunu yakalayıp yakalamadığı ölçülür. Yakalamayan test işe yaramaz.", "",
          "| Yapılan bozma | Beklenen etki | Kalan test sayısı | Beklenen testler kaldı mı? |", "|---|---|---:|---|"]
    y += [f"| {m['ad']} | {m['iddia']} | {len(m['kalan'])} | {'Evet' if m['dogrulandi'] else 'Hayır'} |" for m in mut]
    y += ["", "## Tüm testler", "", "| No | Akış | Kaynak → hedef | Servis | Beklenen | Model | Karar veren kural | Sonuç |",
          "|---|---|---|---|---|---|---|---|"]
    y += [f"| {t['no']} | {t['aciklama']} | `{t['kaynak']}` → `{t['hedef']}` | {t['proto']}/{t['port']} | {t['beklenen']} | {t['gercek']} | "
          f"{' '.join(t['kararlar'])} | {'Geçti' if t['gecti'] else 'Kaldı'} |" for t in sonuc]
    (LAB / "sonuclar" / "MODEL.md").write_text("\n".join(y) + "\n", encoding="utf-8", newline="\n")
    print(f"Yapısal denetim: {len(hatalar)} hata.")
    for h in hatalar:
        print(f"  HATA: {h}")
    print(f"Model testleri: {gecen} / {len(sonuc)} geçti.")
    for t in kalan:
        print(f"  KALDI {t['no']}: {t['aciklama']}: beklenen {t['beklenen']}, model {t['gercek']} ({' '.join(t['kararlar'])})")
    print(f"Bozma deneyleri: {sum(m['dogrulandi'] for m in mut)} / {len(mut)} yakalandı.")
    for a, b, c, e in kap:
        print(f"Kapsam {a}: {c} / {b}" + (f", eksik: {', '.join(e)}" if e else ""))
    return 0 if not hatalar and not kalan and all(m["dogrulandi"] for m in mut) else 1


# ------------------------------------------------------------------ nftables üretimi
def lab_degerleri():
    out = {}
    for s in (LAB / "lab-degerleri.txt").read_text(encoding="utf-8").splitlines():
        if s and not s.startswith("#"):
            k, v = s.split("=")
            out[k] = v
    return out


def nft_uret(sube):
    d, lv = oku_json("company.json"), lab_degerleri()
    kurallar = cevre_kurallari(d, sube)
    eylem = {"allow": "accept", "limit": "accept", "deny": "drop", "reject": "reject"}

    def parca(r):
        p = []
        k, h = r.get("from"), r.get("to")
        if k == "internet":
            p.append('iifname "wan"')
        elif k and k != "any":
            p.append(f"ip saddr {lv.get(k, k)}")
        if h == "internet":
            p.append('oifname "wan"')
        elif h and h != "any":
            if fqdn_mi(h):
                p.append(f'ip daddr {lv[h]} oifname "wan"')
            else:
                p.append(f"ip daddr {lv.get(h, h)}")
        if r.get("proto") in ("tcp", "udp"):
            if r.get("port") is not None:
                p.append(f"{r['proto']} dport {str(r['port']).replace(':', '-')}")
            else:
                p.append(f"meta l4proto {r['proto']}")
        p.append(f'counter {eylem[r["action"]]} comment "{kural_no(r["note"])}"')
        return " ".join(p)

    ileri = [parca(r) for r in kurallar if r.get("direction") == "forward"]
    giris = [parca(r) for r in kurallar if r.get("direction") == "in"]
    wan = WAN[sube]
    nat = []
    if wan in DNAT_443:
        nat.append(f'chain once {{\n\t\ttype nat hook prerouting priority dstnat;\n\t\tiifname "wan" ip daddr {lv[wan]} tcp dport 443 counter dnat to {DNAT_443[wan]}\n\t}}')
    nat.append('chain sonra {\n\t\ttype nat hook postrouting priority srcnat;\n\t\toifname "wan" ip saddr 10.0.0.0/8 counter masquerade\n\t}')
    t = ["# Otomatik üretildi: lab/politika.py nft. Kaynak: company.json. Elle düzenlemeyin.", "flush ruleset", "table inet atlas {",
         "\tchain ileri {", "\t\ttype filter hook forward priority filter; policy drop;",
         "\t\tct state established,related accept", "\t\tct state invalid drop"]
    t += [f"\t\t{x}" for x in ileri]
    t += ["\t}", "\tchain giris {", "\t\ttype filter hook input priority filter; policy drop;",
          '\t\tiif "lo" accept', "\t\tct state established,related accept", "\t\tct state invalid drop"]
    t += [f"\t\t{x}" for x in giris]
    t += ['\t\tcounter drop comment "O7"', "\t}", "\tchain cikis {", "\t\ttype filter hook output priority filter; policy accept;", "\t}", "}",
          "table ip nat {", "\t" + "\n\t".join(nat), "}", ""]
    return "\n".join(t)


def sunucu_nft(ad):
    env = Envanter()
    ip_adresi = env.ad[ad]["uyeler"][0]
    satir = ["flush ruleset", "table inet sunucu {", "\tchain giris {", "\t\ttype filter hook input priority filter; policy drop;",
             '\t\tiif "lo" accept', "\t\tct state established,related accept"]
    for a in oku_json("sunucu-akislari.json")["ayniVlanIzinleri"]:
        if ip_adresi in env.coz(a["hedef"]) and "/" in a["servis"]:
            p, port = a["servis"].split("/")
            for k in env.coz(a["kaynak"]):
                satir.append(f"\t\tip saddr {k} {p} dport {port} counter accept")
    satir += ['\t\tcounter drop comment "sunucu-reddi"', "\t}", "}", ""]
    return "\n".join(satir)


def testler_cozulmus():
    lv = lab_degerleri()
    for t in testleri_oku():
        print("|".join([t["no"], t["kaynak_ad"], lv.get(t["kaynak"], t["kaynak"]), t["hedef_ad"], lv.get(t["hedef"], t["hedef"]),
                        t["proto"], str(t["port"]), t["beklenen"], t["aciklama"]]))


# ------------------------------------------------------------------ envanter belgesi
def nesneler_md(env):
    sube_adi = {"ortak": "Ortak", "istanbul": "İstanbul", "izmir": "İzmir", "amsterdam": "Amsterdam", "ankara-akademik": "Ankara Akademik"}
    tur_adi = {"ag": "Ağ", "host": "Sunucu", "ozet": "Özet", "grup": "Grup", "fqdn": "FQDN", "girdi": "Girdi", "ozel": "Özel"}
    y = ["# Adres ve servis nesneleri", "",
         "Bu dosya [nesneler.json](nesneler.json) dosyasından üretilir: `python3 lab/politika.py nesneler-md`. Elle düzenlenmez.", "",
         "Kural tabloları bu adları kullanır. `company.json` ise aynı kuralların somut adresli hâlini taşır, çünkü dersin aracı tanımadığı adları `any` olarak işler. İkisinin aynı olduğunu `lab/politika.py dogrula` denetler.", "",
         "**Girdi** türündeki nesnelerin değeri burada yoktur: gerçek WAN adresleri kurulumda operatörden alınır, uydurulmaz. Testlerde belgeleme adresleri kullanılır ([lab/lab-degerleri.txt](lab/lab-degerleri.txt)).", "",
         "Adresler hayali şirket içindir, gerçek altyapı bilgisi değildir.", ""]
    for sube in ["ortak", "istanbul", "izmir", "amsterdam", "ankara-akademik"]:
        y += [f"## {sube_adi[sube]}", "", "| Nesne | Tür | Üyeler | Çözülmüş değer | Açıklama |", "|---|---|---|---|---|"]
        for n in sorted((n for n in env.liste if n["sube"] == sube), key=lambda n: (list(tur_adi).index(n["tur"]), n["ad"])):
            if n["tur"] == "grup":
                uyeler = ", ".join(f"`{u}`" for u in n["uyeler"])
                cozum = ", ".join(env.coz(n["ad"]))
            elif n["tur"] == "girdi":
                uyeler, cozum = "—", "Kurulum girdisi, tanımlı değil"
            elif n["tur"] == "ozel":
                uyeler, cozum = "—", "—"
            else:
                uyeler, cozum = "—", ", ".join(n["uyeler"])
            y.append(f"| `{n['ad']}` | {tur_adi[n['tur']]} | {uyeler} | {cozum} | {n['aciklama']} |")
        y.append("")
    return "\n".join(y)


def main(a):
    if not a:
        print(__doc__)
        return 2
    k = a[0]
    if k == "dogrula":
        return 1 if dogrula()[0] else 0
    if k in ("model", "hepsi"):
        return model_raporu()
    if k == "nft":
        print(nft_uret(a[1]), end="")
        return 0
    if k == "testler":
        testler_cozulmus()
        return 0
    if k == "sunucu-nft":
        print(sunucu_nft(a[1]), end="")
        return 0
    if k == "nesneler-md":
        (KOK / "NESNELER.md").write_text(nesneler_md(Envanter()), encoding="utf-8", newline="\n")
        print("NESNELER.md yazıldı.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
