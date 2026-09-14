// IDM Clone Integration - background service worker
// Nama native host harus PERSIS sama dengan "name" di file manifest native host (com.idmclone.host.json)
const NATIVE_HOST_NAME = "com.idmclone.host";

// ------------------------------------------------------------------
// KONFIGURASI FILTER
// Tentuin download seperti apa yang mau di-intercept & dilempar ke
// IDM Clone. Selain itu, biarkan browser download sendiri seperti biasa.
// ------------------------------------------------------------------
const FILTER_CONFIG = {
  // Ekstensi file yang SELALU di-intercept, apapun ukurannya
  // (installer, arsip, ISO, media besar, dsb.)
  alwaysInterceptExtensions: [
    "zip", "rar", "7z", "tar", "gz", "iso",
    "exe", "msi", "deb", "rpm", "appimage",
    "mp4", "mkv", "avi", "mov", "webm",
    "mp3", "flac", "wav",
    "pdf" // opsional, hapus kalau PDF kecil biar tetap lewat browser
  ],

  // Ekstensi yang SELALU dibiarkan lewat browser biasa (gambar, dokumen ringan)
  // Ini override alwaysInterceptExtensions kalau ada konflik.
  neverInterceptExtensions: [
    "jpg", "jpeg", "png", "gif", "webp", "svg", "ico",
    "txt", "csv", "json", "html", "htm"
  ],

  // Kalau ekstensi tidak masuk dua daftar di atas, pakai threshold ukuran (bytes).
  // -1 di fileSize artinya browser belum tahu ukurannya saat onCreated -> kita anggap "tidak diketahui",
  // pada kasus ini kita fallback ke minSizeUnknownAction.
  minSizeBytes: 10 * 1024 * 1024, // 10 MB

  // Aksi kalau ukuran file tidak diketahui saat onCreated: "intercept" atau "allow"
  minSizeUnknownAction: "allow",
};

function getExtensionFromUrl(url) {
  try {
    const pathname = new URL(url).pathname;
    const match = pathname.match(/\.([a-zA-Z0-9]+)$/);
    return match ? match[1].toLowerCase() : "";
  } catch (e) {
    return "";
  }
}

function shouldIntercept(downloadItem) {
  const url = downloadItem.finalUrl || downloadItem.url;

  // Cuma proses http/https, biarkan blob:/data:/filesystem: lewat browser
  // (URL jenis ini nggak akan valid lagi kalau diminta ulang dari luar browser)
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    return false;
  }

  const ext = getExtensionFromUrl(url);

  if (FILTER_CONFIG.neverInterceptExtensions.includes(ext)) {
    return false;
  }

  if (FILTER_CONFIG.alwaysInterceptExtensions.includes(ext)) {
    return true;
  }

  // Ekstensi tidak dikenal / ambigu -> putuskan berdasarkan ukuran
  const fileSize = downloadItem.fileSize; // -1 kalau belum diketahui
  if (fileSize == null || fileSize < 0) {
    return FILTER_CONFIG.minSizeUnknownAction === "intercept";
  }

  return fileSize >= FILTER_CONFIG.minSizeBytes;
}

// ------------------------------------------------------------------
// Context menu manual: klik kanan link -> "Download with IDM Clone"
// Tetap dipertahankan buat kasus kamu mau paksa kirim file kecil juga.
// ------------------------------------------------------------------
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send-to-idm-clone",
    title: "Download with IDM Clone",
    contexts: ["link"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "send-to-idm-clone" && info.linkUrl) {
    sendUrlToNativeHost(info.linkUrl);
  }
});

// ------------------------------------------------------------------
// Auto-intercept: setiap kali browser MAU mulai download baru
// ------------------------------------------------------------------
chrome.downloads.onCreated.addListener((downloadItem) => {
  if (!shouldIntercept(downloadItem)) {
    return; // biarkan browser download seperti biasa
  }

  const url = downloadItem.finalUrl || downloadItem.url;

  chrome.downloads.cancel(downloadItem.id, () => {
    if (chrome.runtime.lastError) {
      console.warn("IDM Clone: gagal cancel download bawaan browser ->", chrome.runtime.lastError.message);
    }
    // Bersihkan entry (file .crdownload kosong) dari daftar & history download browser
    chrome.downloads.erase({ id: downloadItem.id });
  });

  console.log(`IDM Clone: intercept download (${url}), dilempar ke IDM Clone.`);
  sendUrlToNativeHost(url);
});

// ------------------------------------------------------------------
// Kirim URL ke native host
// ------------------------------------------------------------------
function sendUrlToNativeHost(url) {
  chrome.runtime.sendNativeMessage(
    NATIVE_HOST_NAME,
    { action: "add_download", url: url },
    (response) => {
      if (chrome.runtime.lastError) {
        console.error("IDM Clone: gagal konek ke native host ->", chrome.runtime.lastError.message);
        chrome.action?.setBadgeText?.({ text: "ERR" });
        return;
      }
      console.log("IDM Clone: respon dari native host ->", response);
    }
  );
}
