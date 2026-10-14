# RasPBX Android Lab

Source aplikasi Android yang menjalankan FreePBX 14, Asterisk 13.20.0,
MariaDB 10.1.23 dan PHP 5.6.33 di HP melalui PRoot. Tidak membutuhkan root,
Termux terpasang, QEMU, Ubuntu, atau server PBX di laptop.

Paket: `com.naufal.raspbx`; versionCode 5; minSdk 26 (Android 8.0), targetSdk 28.
Runtime host ARM64 membutuhkan HP yang masih mendukung eksekusi ARM 32-bit.
Perangkat pengujian: Redmi Note 13, Android 13. Penyiapan pertama membutuhkan
sekitar 3,5 GB ruang kosong.

## Isi

- `android/app/src/`: MainActivity (UI/WebView) dan PbxService (layanan server).
- `android/app/AndroidManifest.xml`: izin, versi dan minimum SDK.
- `android/guest-*.sh`, `guest-*.php`: startup, shutdown, dashboard dan konfigurasi PBX.
- `tools/`: build APK, ekspor image, penyiapan PRoot, konfigurasi lab dan pengujian SIP/RTP.
- `docs/validation/`: hasil uji Ring Group, musik, dan ACD yang sudah dilakukan.
- `runtime/android/rootfs-manifest.json`: checksum filesystem RasPBX bawaan.
- `runtime/android/native/provenance.json`: asal dan versi runtime native.

Repository ini berisi source kode Android dan metadata runtime. Rootfs
`runtime/android/raspbx-android-armhf.tar.gz` (sekitar 746 MiB), library
`native/*.so`, image disk, APK, database HP, dan musik pribadi tidak dicommit.
Siapkan input runtime melalui langkah di bawah sebelum build. Rootfs berasal
dari image awal, bukan data HP yang sedang digunakan. Konfigurasi server
disimpan pada penyimpanan privat aplikasi setelah instalasi.

Source Java dan empat skrip startup sama dengan proyek APK 0.2.1. Skrip build
dan alat pengembangan dalam ekspor dibuat portable. Contoh konfigurasi lab
membuat password acak; password SIP/AMI/admin aktif, keystore, dan database HP
tidak diekspor. Dua lagu pribadi juga tidak disertakan; berikan file musik
sendiri saat menjalankan alat konfigurasi.

## Build di Windows

1. Clone repository ini dan siapkan input runtime sesuai langkah di bawah.
2. Pasang Python 3.11 atau lebih baru, JDK 17 atau lebih baru, Android SDK
   Platform 35 dan Build Tools **35.0.1**. `platform-tools` hanya dibutuhkan
   untuk pemeliharaan melalui ADB.
3. Tentukan `ANDROID_SDK_ROOT` dan `JAVA_HOME` bila SDK/JDK tidak ditemukan
   otomatis. Android Studio menyediakan JDK pada folder `jbr`.
4. Jalankan `BUILD.cmd`, atau `python tools/build_android_apk.py`.
5. APK dihasilkan pada `output/android/RasPBX-Android-Lab.apk`.

Contoh PowerShell:
```powershell
$env:ANDROID_SDK_ROOT = "$env:LOCALAPPDATA\Android\Sdk"
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
python tools/build_android_apk.py
```

Build menggunakan javac, D8, aapt2, zipalign dan apksigner; tidak menggunakan
Gradle. Keystore baru dibuat lokal pada `runtime/private` jika belum ada.
Keystore asli aplikasi yang terpasang tidak disertakan. APK dengan kunci baru
tidak dapat menjadi pembaruan aplikasi lama dengan identitas paket yang sama;
untuk pembaruan diperlukan kunci asli. Source ZIP tidak mengubah instalasi HP.

## Menyiapkan input runtime

1. Letakkan image awal `raspbx-04-04-2018.img` milik Anda di root repository.
   SHA256 image yang dipakai pada pengujian:
   `72b9ceb816f6572b5bde107858f67a68d6a4c269469cdfa89de30a12b40efcff`.
2. Jalankan `python tools/export_android_rootfs.py` untuk mengekspor filesystem.
   Proses ini membaca image tanpa mengubahnya.
3. Pasang decoder paket jika diperlukan: `python -m pip install backports.zstd`.
4. Jalankan `python tools/prepare_android_native.py`. Paket native dipilih
   dari versi, URL dan checksum yang tercatat dalam `provenance.json`.
5. Jalankan build setelah rootfs dan kelima library native tersedia.

Rootfs yang diuji mempunyai SHA256
`c227dd7e230d9e20bc60ab82693ec256bd2172e7e8c3d274e809ef7505c19a8d`.
Metadata ini juga dipakai oleh APK untuk memeriksa integritas saat ekstraksi.
Jika mengekspor ulang menghasilkan tarball berbeda (misalnya metadata arsip
berubah), periksa isi ekspor sebelum menyesuaikan konstanta `ROOTFS_SHA` pada
`PbxService.java`. Source FreePBX PHP berada dalam rootfs pada
`/var/www/html/admin/`; lisensi paket Linux juga berada di dalam rootfs.

Kelima library host: `libproot.so`, `libproot-loader.so`,
`libproot-loader32.so`, `libtalloc.so`, dan `libandroid-shmem.so`.

## Menjalankan aplikasi

Buka APK dan tekan **Mulai**. Setelah **Aktif**, halaman FreePBX asli terbuka.
Instalasi baru membuat akun awal 101/102 dengan password acak; lihat **Akun SIP**.
HP ini memakai SIP `127.0.0.1:15060`; perangkat lain memakai `IP_WIFI_HP:15060`.
FreePBX: `http://IP_WIFI_HP:8088/admin/`. RTP UDP: 20000–20031.
Setelah berganti Wi-Fi, hentikan dan mulai server kembali, lalu ubah alamat
server di softphone. Pengguna Wi-Fi harus dapat saling mengakses.

## Membuat praktikum 201/202/203, Ring Group dan ACD

Konfigurasi yang sedang berjalan di HP pengguna tersimpan di database privat,
bukan di Java. Skrip berikut mereproduksi pengaturan praktikum pada instalasi
baru tanpa memakai password akun pengguna yang lama.

Hubungkan HP development melalui ADB dan mulai PBX sampai Aktif. Jika ada lebih
dari satu perangkat, set `ANDROID_SERIAL` ke serial perangkat yang dipilih.
ADB digunakan untuk pemeliharaan, bukan untuk panggilan sehari-hari.

```powershell
python tools/create_android_lab_agents.py
python tools/configure_android_ringgroups.py
python tools/install_android_hold_music.py "C:\musik\lagu-ring-group.mp3"
python tools/configure_android_acd.py "C:\musik\lagu-acd.mp3"
```

Dua perintah musik membutuhkan `ffmpeg` pada PATH; pemasangan musik Ring Group
juga membutuhkan `ffprobe`. Musik diubah menjadi WAV 8 kHz mono 16-bit dan
G.711 µ-law. Transfer ke penyimpanan privat APK diperiksa checksum-nya.
Konfigurasi menggunakan API modul FreePBX yang terpasang, dengan cadangan
database dan konfigurasi sebelum perubahan.

- 201/202: agen CS; 203: penelepon. Password ditampilkan melalui **Akun SIP**.
- 257: Ring Group `ringall`, dua agen berdering bersama.
- 258: Ring Group `hunt`, dua agen berdering bergiliran, 20 detik per giliran.
- 259: Queue ACD `rrmemory`; agen sibuk dilewati dan penelepon tetap mengantre.
  Dering 20 detik, retry 3 detik, batas antre 180 detik.
- 257/258 memakai kategori `praktikum_dj`; 259 memakai `acd_dj`.

Skrip konfigurasi musik dan ACD menolak nama/nomor yang sudah ada untuk mencegah
penimpaan konfigurasi yang tidak dikenal. Pengaturan juga dapat dibuat manual
melalui **Applications → Extensions / Ring Groups / Queues** di FreePBX.

## Verifikasi

Laporan menunjukkan registrasi SIP, dering bersama/bergiliran, musik RTP yang
cocok dengan sumber, antrean saat dua agen sibuk, rotasi agen dan RTP dua arah.
Uji ACD memakai akun/queue sementara yang terpisah dari softphone pengguna.
Mikrofon, speaker, video dan ketahanan saat layar mati tidak disimpulkan dari
uji paket RTP. Alat `test_android_*.py` membutuhkan IP server dan IP bind laptop.
Uji Ring Group menggunakan 201–203, jadi jalankan saat akun itu tidak sedang
dipakai softphone manusia. Uji ACD dan musik membuat lalu menghapus akun uji.

## Sumber komponen

Lihat `android/SOURCES.txt` dan `runtime/android/native/provenance.json`.
Rootfs menyertakan PHP FreePBX dan berkas lisensi paket Linux asalnya.
Library native serta sebagian program Linux adalah dependency hasil build;
source C dependency tersebut dirujuk melalui repositori upstream, bukan
dinyatakan sebagai source Java proyek ini. Ini proyek laboratorium, bukan
rilis resmi RasPBX/FreePBX untuk Android.

## Status dashboard

Pengujian SIP, Ring Group, ACD dan RTP tersedia pada `docs/validation/`.
Grafik CPU/jaringan dashboard masih membutuhkan adaptasi terhadap pembatasan
Android tanpa root. Temuan awal dan bagian yang masih harus diperiksa dicatat
di [docs/KNOWN-ISSUES.md](docs/KNOWN-ISSUES.md). Status tersebut terpisah dari
hasil pengujian panggilan; repository ini tidak mengklaim seluruh dashboard
sudah berfungsi normal pada Android.
