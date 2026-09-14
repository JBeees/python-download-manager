# Setup Browser Integration (Brave) untuk IDM Clone

## Langkah 1: Load extension di Brave (mode developer)

1. Buka Brave, ketik di address bar: `brave://extensions`
2. Aktifkan toggle **Developer mode** (pojok kanan atas)
3. Klik **Load unpacked**
4. Pilih folder `browser_extension/` (folder yang isinya `manifest.json` dan `background.js`)
5. Extension akan muncul di daftar dengan sebuah **ID** (string panjang acak, misal `abcdefghijklmnopabcdefghijklmnop`) — **catat ID ini**, akan dipakai di langkah berikutnya.

## Langkah 2: Daftarkan Native Messaging Host

Di terminal, masuk ke folder `native_host/` lalu jalankan:

```bash
cd native_host
chmod +x install.sh
./install.sh <EXTENSION_ID_YANG_TADI_DICATAT>
```

Contoh:
```bash
./install.sh abcdefghijklmnopabcdefghijklmnop
```

Script ini akan:
- Membuat file `~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.idmclone.host.json`
- Mengisi path absolut ke `idm_native_host.py` dan Extension ID ke dalam file itu
- `chmod +x` skrip Python-nya

## Langkah 3: Jalankan aplikasi utama

```bash
cd ..  # balik ke folder idm-clone
python3 gui_main.py
```

**Aplikasi ini HARUS sedang berjalan** setiap kali kamu mau pakai fitur "Download with IDM Clone" dari Brave. Native host cuma jembatan; dia butuh aplikasi utama aktif di port `47821` (localhost) buat nerima URL-nya.

## Langkah 4: Testing

1. Buka halaman web mana saja yang ada link download (contoh: halaman rilis Ubuntu, GitHub releases, dsb).
2. Klik kanan pada link download tersebut.
3. Pilih **"Download with IDM Clone"** dari context menu.
4. Cek window IDM Clone — harusnya muncul item baru di antrian otomatis, tersimpan ke `~/Downloads/`.

## Troubleshooting

**Context menu "Download with IDM Clone" tidak muncul:**
- Pastikan extension ter-load dengan benar di `brave://extensions` (tidak ada error merah)
- Reload extension (klik ikon refresh di kartu extension-nya)

**Muncul error di console extension (`chrome.runtime.lastError`):**
- Cek nama native host di `background.js` (`com.idmclone.host`) SAMA PERSIS dengan `"name"` di file `com.idmclone.host.json`
- Cek Extension ID di file JSON yang ter-install cocok dengan ID asli extension (buka `~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/com.idmclone.host.json` dan lihat field `allowed_origins`)
- Cek log di terminal tempat kamu jalankan `gui_main.py` — kalau ada pesan "Browser listener gagal start", kemungkinan port 47821 sudah dipakai proses lain

**Link masuk tapi tidak muncul di app:**
- Pastikan `gui_main.py` sedang berjalan SEBELUM kamu klik context menu
- Cek firewall lokal tidak memblokir koneksi localhost

**Untuk melihat log native host secara langsung (debug):**
```bash
# Jalankan manual buat lihat apakah script native host jalan tanpa error python
python3 native_host/idm_native_host.py
# (Script ini nunggu input dari stdin sesuai protokol Native Messaging,
#  jadi kalau dijalankan manual dia akan "hang" nunggu -- itu normal, tekan Ctrl+C)
```
