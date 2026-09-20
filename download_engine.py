"""
IDM Clone - Download Engine untuk GUI
Berisi logic download multi-segment + resume, dibungkus jadi QThread
supaya bisa jalan di background tanpa nge-freeze GUI.
"""

import os
import re
import json
import time
import shutil
import threading
import requests
from urllib.parse import urlparse, unquote
from PyQt6.QtCore import QThread, pyqtSignal

# Nama-nama reserved di Windows (gak boleh dipakai sebagai nama file,
# dengan atau tanpa ekstensi). Gak masalah kalau dicek di Linux juga.
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def format_size(num_bytes):
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


def sanitize_filename(name, fallback="downloaded_file"):
    """
    Bikin nama file aman dipakai di Windows maupun Linux/macOS.
    - Buang karakter ilegal di Windows: \\ / : * ? " < > |
    - Buang trailing dot/space (Windows gak suka)
    - Hindari nama reserved Windows (CON, PRN, COM1, dst.)
    - Batasi panjang biar gak kena limit filesystem
    """
    name = (name or "").strip()
    if not name:
        return fallback

    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip(" .")

    if not name:
        return fallback

    stem, ext = os.path.splitext(name)
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
        name = stem + ext

    # Batasi panjang nama file (bukan full path) biar aman di kedua OS
    max_len = 200
    if len(name) > max_len:
        stem, ext = os.path.splitext(name)
        name = stem[: max_len - len(ext)] + ext

    return name or fallback


def filename_from_url(url, fallback="downloaded_file"):
    """Ekstrak & sanitize nama file dari URL (buang query string/fragment dulu)."""
    path = urlparse(url).path
    raw_name = unquote(path.rsplit("/", 1)[-1])
    return sanitize_filename(raw_name, fallback=fallback)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def parse_cookie_string(cookie_str):
    """
    Ubah string cookie mentah (hasil copy dari DevTools -> Network -> header 'Cookie')
    jadi dict, format: 'nama1=nilai1; nama2=nilai2'.
    """
    cookies = {}
    if not cookie_str:
        return cookies
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def build_request_kwargs(cookies=None):
    """Header & cookie default dipakai di semua request (HEAD maupun segment GET)."""
    kwargs = {"headers": {"User-Agent": DEFAULT_USER_AGENT}}
    if cookies:
        kwargs["cookies"] = cookies
    return kwargs


def get_file_info(url, cookies=None):
    """
    Coba HEAD dulu (lebih ringan). Kalau ditolak (403/405), fallback ke GET
    dengan Range kecil -- banyak pre-signed URL (AWS S3, dsb.) cuma valid
    untuk method tertentu (biasanya GET), karena signature-nya menghitung
    method request juga.
    """
    req_kwargs = build_request_kwargs(cookies)
    try:
        resp = requests.head(url, allow_redirects=True, timeout=15, **req_kwargs)
        resp.raise_for_status()
        total_size = int(resp.headers.get("Content-Length", 0))
        accept_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
        filename = filename_from_url(url)
        return total_size, accept_ranges, filename
    except requests.exceptions.RequestException as head_error:
        status = getattr(head_error.response, "status_code", None)
        if status not in (403, 405):
            _log_request_error("get_file_info (HEAD)", url, head_error)
            raise

    # Fallback: HEAD ditolak -> coba GET dengan Range kecil, tanpa unduh full body
    try:
        range_kwargs = build_request_kwargs(cookies)
        range_kwargs["headers"]["Range"] = "bytes=0-0"
        with requests.get(url, stream=True, timeout=15, **range_kwargs) as resp:
            resp.raise_for_status()
            if resp.status_code == 206 and "Content-Range" in resp.headers:
                # Format: "bytes 0-0/12345"
                total_size = int(resp.headers["Content-Range"].split("/")[-1])
                accept_ranges = True
            else:
                # Server tidak mendukung Range -> anggap single-segment,
                # ambil Content-Length kalau ada (mungkin 0 kalau chunked).
                total_size = int(resp.headers.get("Content-Length", 0))
                accept_ranges = False
            filename = filename_from_url(url)
            return total_size, accept_ranges, filename
    except requests.exceptions.RequestException as get_error:
        _log_request_error("get_file_info (GET fallback)", url, get_error)
        raise


def strip_query(url):
    """
    Buang query string dari URL (termasuk parameter signature seperti
    X-Amz-Signature, X-Amz-Expires, dst). Dipakai untuk membandingkan
    apakah dua URL "pada dasarnya" menunjuk ke file yang sama, walau
    pre-signed URL-nya beda tiap digenerate ulang.
    """
    return url.split("?", 1)[0]


def _log_request_error(context, url, e):
    status = getattr(e.response, "status_code", None)
    body_preview = ""
    if e.response is not None:
        try:
            body_preview = e.response.text[:300]
        except Exception:
            pass
    print(f"[!] {context} gagal untuk {url}")
    print(f"    Status code : {status}")
    print(f"    Pesan       : {e}")
    if body_preview:
        print(f"    Preview body: {body_preview!r}")


class SegmentWorker:
    """Satu segment. Bisa di-pause (via flag) dan resume (baca ulang file part)."""

    def __init__(self, url, start, end, part_num, tmp_dir, cookies=None):
        self.url = url
        self.original_start = start
        self.end = end
        self.part_num = part_num
        self.tmp_path = os.path.join(tmp_dir, f"part_{part_num}.tmp")
        self.cookies = cookies
        self.error = None
        self.pause_flag = threading.Event()  # set() -> pause
        self.cancel_flag = threading.Event()  # set() -> stop total

        existing = os.path.getsize(self.tmp_path) if os.path.exists(self.tmp_path) else 0
        self.start = start + existing
        self.downloaded = existing

    def run(self):
        if self.end >= 0 and self.start > self.end:
            return  # segment ini udah full selesai dari sesi sebelumnya

        # end < 0 artinya ukuran file tidak diketahui (server tidak kasih Content-Length,
        # misal linknya bukan file langsung tapi halaman HTML) -> download tanpa Range,
        # streaming biasa sampai selesai.
        unknown_length = self.end < 0
        req_kwargs = build_request_kwargs(self.cookies)
        if not unknown_length:
            req_kwargs["headers"]["Range"] = f"bytes={self.start}-{self.end}"
        mode = "ab" if self.start > self.original_start else "wb"
        try:
            with requests.get(self.url, stream=True, timeout=15, **req_kwargs) as r:
                r.raise_for_status()
                with open(self.tmp_path, mode) as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if self.cancel_flag.is_set():
                            return
                        while self.pause_flag.is_set():
                            # nunggu selama di-pause, cek cancel juga tiap 0.2s
                            if self.cancel_flag.is_set():
                                return
                            time.sleep(0.2)
                        if chunk:
                            f.write(chunk)
                            self.downloaded += len(chunk)
        except requests.exceptions.RequestException as e:
            self.error = str(e)
        except Exception as e:
            # Guard tambahan: jangan biarkan error tak terduga apapun bocor ke thread
            # induk dan bikin seluruh aplikasi crash.
            self.error = f"Unexpected error: {e}"


class DownloadTask(QThread):
    """
    Satu job download lengkap (semua segment), jalan di QThread terpisah.
    Emit sinyal ke GUI untuk update progress/status.
    """

    progress_updated = pyqtSignal(str, float, float, int)  # task_id, percent, speed, downloaded_bytes
    status_changed = pyqtSignal(str, str)  # task_id, status ("downloading"/"paused"/"done"/"error"/"cancelled")
    finished_ok = pyqtSignal(str)  # task_id

    def __init__(self, task_id, url, output_path, num_segments=8, cookies=None, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.url = url
        self.output_path = output_path
        self.num_segments = num_segments
        self.cookies = cookies  # dict hasil parse_cookie_string(), atau None
        self.tmp_dir = output_path + ".parts"
        self.segments = []
        self.total_size = 0
        self._paused = False
        self._cancelled = False

    def pause(self):
        self._paused = True
        for seg in self.segments:
            seg.pause_flag.set()
        self.status_changed.emit(self.task_id, "paused")

    def resume(self):
        self._paused = False
        for seg in self.segments:
            seg.pause_flag.clear()
        self.status_changed.emit(self.task_id, "downloading")

    def cancel(self):
        self._cancelled = True
        for seg in self.segments:
            seg.cancel_flag.set()
        self.status_changed.emit(self.task_id, "cancelled")

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            # Pengaman terakhir: apapun yang salah di dalam thread ini,
            # jangan biarkan bikin seluruh aplikasi PyQt crash.
            print(f"[!] DownloadTask error tak terduga ({self.task_id}): {e}")
            self.status_changed.emit(self.task_id, "error")

    def _run_inner(self):
        try:
            self.total_size, accept_ranges, _ = get_file_info(self.url, cookies=self.cookies)
        except requests.exceptions.RequestException as e:
            # Detail lengkap sudah di-print oleh get_file_info(); di sini cukup
            # kasih tau GUI kalau statusnya error.
            self.status_changed.emit(self.task_id, "error")
            return

        if self.total_size == 0 or not accept_ranges:
            # Fallback: treat as single segment
            num_segments = 1
        else:
            num_segments = self.num_segments

        resuming = False
        if os.path.exists(self.tmp_dir):
            meta_path = os.path.join(self.tmp_dir, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                # Bandingkan base URL (tanpa query/signature) + ukuran file, BUKAN
                # URL persis sama -- supaya link pre-signed yang diganti (misal
                # setelah accept ulang agreement / signature baru) tetap dianggap
                # file yang sama dan bisa lanjut dari progress sebelumnya.
                if (meta.get("base_url") == strip_query(self.url)
                        and meta.get("total_size") == self.total_size):
                    resuming = True
                    num_segments = meta["num_segments"]
                    segment_ranges = [tuple(r) for r in meta["segment_ranges"]]
            if not resuming:
                shutil.rmtree(self.tmp_dir)

        os.makedirs(self.tmp_dir, exist_ok=True)

        if not resuming:
            if self.total_size == 0:
                # Ukuran file tidak diketahui -> satu segment "open-ended" (end = -1
                # jadi sinyal buat SegmentWorker: download tanpa Range header).
                num_segments = 1
                segment_ranges = [(0, -1)]
            else:
                segment_size = self.total_size // num_segments
                segment_ranges = []
                for i in range(num_segments):
                    start = i * segment_size
                    end = (start + segment_size - 1) if i < num_segments - 1 else self.total_size - 1
                    segment_ranges.append((start, end))
            with open(os.path.join(self.tmp_dir, "meta.json"), "w") as f:
                json.dump({
                    "base_url": strip_query(self.url), "total_size": self.total_size,
                    "num_segments": num_segments, "segment_ranges": segment_ranges,
                }, f)

        self.segments = [
            SegmentWorker(self.url, start, end, i, self.tmp_dir, cookies=self.cookies)
            for i, (start, end) in enumerate(segment_ranges)
        ]

        already_done = sum(s.downloaded for s in self.segments)

        threads = [threading.Thread(target=s.run) for s in self.segments]
        for t in threads:
            t.start()

        self.status_changed.emit(self.task_id, "downloading")
        start_time = time.time()

        while any(t.is_alive() for t in threads):
            downloaded = sum(s.downloaded for s in self.segments)
            elapsed = time.time() - start_time
            new_data = downloaded - already_done
            speed = new_data / elapsed if elapsed > 0 else 0
            percent = (downloaded / self.total_size * 100) if self.total_size else 0
            self.progress_updated.emit(self.task_id, percent, speed, downloaded)
            time.sleep(0.3)

        for t in threads:
            t.join()

        if self._cancelled:
            return  # biarkan file .parts untuk kemungkinan resume nanti

        errors = [s for s in self.segments if s.error]
        if errors:
            self.status_changed.emit(self.task_id, "error")
            return

        missing = [s for s in self.segments if not os.path.exists(s.tmp_path)]
        if missing:
            print(f"[!] Part file hilang untuk task {self.task_id}: "
                  f"{[s.tmp_path for s in missing]}")
            self.status_changed.emit(self.task_id, "error")
            return

        # Gabungkan semua part
        with open(self.output_path, "wb") as outfile:
            for seg in self.segments:
                with open(seg.tmp_path, "rb") as pf:
                    outfile.write(pf.read())

        for seg in self.segments:
            os.remove(seg.tmp_path)
        os.remove(os.path.join(self.tmp_dir, "meta.json"))
        os.rmdir(self.tmp_dir)

        self.status_changed.emit(self.task_id, "done")
        self.finished_ok.emit(self.task_id)
