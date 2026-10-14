# Temuan awal dashboard Android — 14 Oktober 2026

Pemeriksaan langsung dilakukan pada APK 0.2.1-lab di Redmi Note 13 Android 13.
Ini catatan diagnosis yang masih terbuka, bukan laporan perbaikan selesai.

## Temuan yang terverifikasi

- Guest tanpa root ditolak ketika membaca `/proc/stat`, `/proc/loadavg`,
  `/proc/net/dev`, `/proc/net/route` dan `/proc/uptime` (`Permission denied`).
  `/proc/meminfo` tetap dapat dibaca.
- Kelas CPUInfo FreePBX membaca `/proc/loadavg`; pengumpul jaringan bergantung
  pada statistik antarmuka Linux. PRoot tidak memberikan izin kernel Android
  tambahan untuk sumber data tersebut.
- Pengumpul pada `android/guest-collect.php` saat ini memanggil `genSysInfo()`.
  FreePBX juga mempunyai scheduler `runTrigger()` dan proses `netmon.php`;
  riwayat grafik memerlukan pemeriksaan lebih lanjut pada jalur-jalur ini.
- Log memuat timeout pembaruan kunci GPG ke keyserver lama, serta kegagalan
  koneksi AMI di sekitar penghentian/startup layanan. Kondisi AMI setelah
  startup harus diperiksa terpisah sebelum menyimpulkan gangguan permanen.
- Log startup bersifat append, sehingga kesalahan dari versi/proses lama
  masih dapat muncul bersama startup yang berhasil.

Tidak ada password, alamat IP perangkat, log penuh, atau database pengguna
yang disalin ke repository. Pengamatan panggilan berhasil tidak membuktikan
seluruh sumber statistik dashboard tersedia.

## Pekerjaan yang masih terbuka

1. Periksa isi/history yang dipakai AJAX grafik dan kelengkapan scheduler.
2. Sediakan metrik melalui API Android yang diizinkan jika metrik Linux
   ditolak, dengan label sumber/ruang lingkup yang jujur.
3. Bedakan nilai tidak tersedia dari nol; jangan mengganti data yang ditolak
   dengan angka palsu.
4. Uji tampilan grafik setelah adaptasi tanpa menghentikan panggilan aktif.

Sumber diagnosis: kode modul Dashboard pada image FreePBX 14 dan pemeriksaan
izin pembacaan dalam konteks APK. Perbaikan grafik belum termasuk commit ini.
