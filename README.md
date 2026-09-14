# IDM Clone — Python Download Manager

Download manager sederhana berbasis Python, terinspirasi dari **Internet Download Manager (IDM)**. Punya GUI PyQt6, multi-segment download dengan resume, dan integrasi browser (Brave/Chrome) yang bisa otomatis menangkap download dari browser.

## ✨ Fitur

- **Multi-segment parallel download** dengan HTTP `Range` header untuk mempercepat proses download
- **Resume otomatis** — file `.parts` dan `meta.json` disimpan tiap sesi, jadi download yang terputus bisa dilanjutkan
- **Kontrol penuh per item**: Pause / Resume / Cancel / **Retry** (untuk download yang gagal)
- **Antrian download** dengan batas jumlah download bersamaan (concurrency limit) yang bisa diatur
- **Progress real-time**: persentase, kecepatan, total data terdownload per item maupun total sesi
- **Integrasi browser**:
  - Klik kanan pada link → "Download with IDM Clone" (manual)
  - **Auto-intercept**: browser otomatis membatalkan download bawaan dan melempar URL-nya ke IDM Clone, dengan filter berdasarkan ekstensi & ukuran file (file kecil seperti gambar/dokumen tetap didownload langsung oleh browser)
- **Dukungan cookie manual** — untuk link yang butuh session login/agreement (misal dataset akademik), cookie bisa ditempel manual saat menambah download
- **Fallback deteksi ukuran file** — kalau server menolak `HEAD` request (umum terjadi pada pre-signed URL seperti AWS S3/Dataverse), otomatis fallback ke `GET` dengan `Range` kecil
- **Custom User-Agent** default (browser-like), supaya tidak diblokir server yang menolak request dari library seperti `requests`
- Sanitasi nama file otomatis (aman untuk Windows & Linux)
- Penanganan file tanpa `Content-Length` (misalnya video) dengan fallback single-segment

## 🗂️ Struktur Proyek

```
idm-clone/
├── gui_main.py                 # Aplikasi utama (GUI PyQt6)
├── download_engine.py          # Logic download multi-segment + resume (QThread)
├── browser_extension/
│   ├── manifest.json           # Manifest extension (Manifest V3)
│   └── background.js           # Service worker: context menu + auto-intercept + filter
└── native_host/
    ├── idm_native_host.py      # Jembatan Native Messaging API <-> socket lokal
    ├── com.idmclone.host.json  # Template manifest native messaging host
    └── install.sh              # Script instalasi native host
```

## 📋 Requirement

- Python 3.9+
- Kali Linux (atau distro Linux lain yang mendukung PyQt6)
- Browser berbasis Chromium (Brave, Chrome, dll.) untuk fitur integrasi browser (opsional)

Install dependency Python:

```bash
pip install PyQt6 requests
```

## 🚀 Instalasi & Menjalankan

### 1. Clone repo

```bash
git clone https://github.com/<username>/idm-clone.git
cd idm-clone
```

### 2. Jalankan aplikasi utama

```bash
python3 gui_main.py
```

Aplikasi akan membuka window GUI dan otomatis mulai mendengarkan koneksi dari browser extension di `127.0.0.1:47821`.

### 3. (Opsional) Setup integrasi browser

Kalau kamu mau browser otomatis melempar download ke IDM Clone:

1. Buka `brave://extensions` (atau `chrome://extensions`), aktifkan **Developer mode**
2. Klik **Load unpacked**, pilih folder `browser_extension/`
3. Catat **Extension ID** yang muncul
4. Daftarkan native messaging host:

   ```bash
   cd native_host
   chmod +x install.sh
   ./install.sh <EXTENSION_ID>
   ```

   > **Catatan untuk pengguna Brave-Origin/varian Brave lain**: `install.sh` default menargetkan folder profil `Brave-Browser`. Kalau kamu pakai varian lain (misalnya `Brave-Origin`), sesuaikan `TARGET_DIR` di dalam `install.sh` ke folder profil browser kamu (cek `~/.config/BraveSoftware/`).

5. Pastikan `gui_main.py` sedang berjalan, lalu coba download file besar (zip, ISO, mp4, dll.) — browser akan otomatis membatalkannya dan melemparnya ke antrian IDM Clone

### Mengatur filter auto-intercept

Buka `browser_extension/background.js`, ada objek `FILTER_CONFIG` di bagian atas file untuk mengatur:
- Ekstensi yang **selalu** di-intercept (installer, arsip, video, dll.)
- Ekstensi yang **selalu dibiarkan** lewat browser (gambar, dokumen ringan)
- Ambang batas ukuran file (bytes) untuk ekstensi yang tidak masuk dua daftar di atas

## 🎮 Cara Pakai

1. Klik **"+ Tambah Download"**, masukkan URL dan jumlah segment
2. Kalau link butuh session/login (misal dataset yang perlu klik "Accept" agreement), ambil header `Cookie` dari DevTools browser (Network tab) dan tempel di kolom **Cookie** (opsional)
3. Pilih lokasi penyimpanan file
4. Download otomatis masuk antrian dan berjalan sesuai batas concurrency yang diatur
5. Gunakan tombol **Pause/Resume/Cancel** untuk mengontrol tiap item
6. Jika ada download yang gagal, tombol berubah jadi **Retry** — klik untuk mencoba ulang (otomatis melanjutkan dari segment yang sudah terdownload)

## ⚙️ Cara Kerja Singkat

- Setiap task download dijalankan di `QThread` terpisah (`DownloadTask`) supaya GUI tidak freeze
- File dipecah jadi beberapa segment (thread) berdasarkan header `Content-Length` dan `Accept-Ranges` — ini paralelisme I/O-bound (nunggu jaringan), bukan CPU-bound, jadi jumlah thread tidak terikat jumlah core CPU
- Progress tiap segment dilacak oleh `SegmentWorker`, digabung jadi satu file setelah semua segment selesai
- Kalau download gagal/dibatalkan, file `.parts` tetap disimpan sehingga bisa dilanjutkan (resume) di percobaan berikutnya
- Deteksi ukuran file: coba `HEAD` dulu, kalau ditolak (403/405) — umum terjadi pada pre-signed URL seperti S3 — otomatis fallback ke `GET` dengan `Range: bytes=0-0`

## ⚠️ Catatan & Limitasi

- Fitur integrasi browser dikonfigurasi untuk lokasi profil `Brave-Browser` standar secara default — sesuaikan `install.sh` kalau pakai varian Brave lain
- **Link pre-signed (AWS S3, Dataverse, dll.) biasanya punya masa berlaku terbatas** (lihat parameter `X-Amz-Expires` di URL) — kalau download dijeda terlalu lama atau link kadaluarsa, harus ambil ulang link/cookie yang baru
- Cookie yang ditempel manual **tidak** menangani autentikasi kompleks (misal OAuth dengan token yang expired cepat) — cocok untuk kasus sederhana seperti agreement/session cookie biasa
- Proyek ini dibuat untuk keperluan belajar/personal use, bukan pengganti IDM yang sesungguhnya secara fitur

## 🛣️ Roadmap

- [ ] Dukungan download video YouTube (via `yt-dlp`)
- [ ] Deteksi otomatis semua varian Brave/Chromium saat instalasi native host
- [ ] Ambil cookie otomatis dari browser (via `chrome.cookies` API) untuk auto-intercept, tanpa perlu copy-paste manual
- [ ] Scheduler download (jadwal otomatis)

## 📄 Lisensi

Silakan tambahkan lisensi sesuai kebutuhan (misalnya MIT License).
