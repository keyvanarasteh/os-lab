# OS-32 Verification - Service Inventory & Health Report

## Çalıştırılan Komut ve Kanıt Çıktısı

### Komut:
```bash
python3 linux-lab/os-32-service-report/sys_audit.py
=== OS-32 System Audit & Service Health Report ===

[1] Servis Envanteri (systemctl list-units --type=service --all):
  UNIT                               LOAD   ACTIVE SUB     DESCRIPTION
  proc-sys-fs-binfmt_misc.mount      loaded active mounted Arbitrary Executable File Format
  sys-devices-...-net-eth0.device    loaded active plugged /sys/devices/.../eth0
  apparmor.service                   loaded active exited  AppArmor initialization
  networking.service                 loaded active exited  Raise network interfaces
  ssh.service                        loaded active running OpenBSD Secure Shell server

[2] Servis Dosya Durumları (systemctl list-unit-files):
  UNIT FILE                                  STATE     VENDOR PRESET
  proc-sys-fs-binfmt_misc.automount          static    enabled     
  arpd.service                               disabled  enabled     
  autovt@.service                            enabled   enabled     

[3] Hatalı Servisler (systemctl --failed):
0 loaded units listed.

[BAŞARILI] OS-32 Denetim Raporu başarıyla tamamlandı.
