#!/usr/bin/env python3
"""
IDM Clone - Tahap 4 (revisi): GUI dengan PyQt6
Fitur:
- Tambah download lewat dialog URL + pilih jumlah segment
- Antrian download beneran, dibatasi max N download jalan bersamaan
- Tombol Pause / Resume / Cancel per item
- Progress bar, kecepatan, total data terdownload per item
- Total keseluruhan data yang sudah didownload (status bar)
"""

import sys
import os
import uuid
import socket
import json

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QTableWidget, QTableWidgetItem,
    QProgressBar, QFileDialog, QMessageBox, QHeaderView, QSpinBox,
    QDialog, QFormLayout, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from download_engine import DownloadTask, format_size, filename_from_url, parse_cookie_string

# Harus sama persis dengan APP_PORT di native_host/idm_native_host.py
BROWSER_LISTEN_HOST = "127.0.0.1"
BROWSER_LISTEN_PORT = 47821


class BrowserListener(QThread):
    """
    Server socket sederhana yang jalan di background thread.
    Menerima URL dari native_host.py (dikirim saat user klik kanan
    'Download with IDM Clone' di browser), lalu emit sinyal ke GUI.
    """

    url_received = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_socket = None
        self._running = True

    def run(self):
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind((BROWSER_LISTEN_HOST, BROWSER_LISTEN_PORT))
            self._server_socket.listen(5)
        except OSError as e:
            print(f"[!] Browser listener gagal start di port {BROWSER_LISTEN_PORT}: {e}")
            return

        while self._running:
            try:
                conn, _addr = self._server_socket.accept()
            except OSError:
                break  # socket ditutup saat app close
            try:
                data = conn.recv(65536)
                if data:
                    payload = json.loads(data.decode("utf-8"))
                    url = payload.get("url")
                    if url:
                        self.url_received.emit(url)
            except Exception as e:
                print(f"[!] Browser listener error saat baca koneksi: {e}")
            finally:
                conn.close()

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass


class AddDownloadDialog(QDialog):
    """Dialog untuk input URL + jumlah segment sebelum download dimulai."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tambah Download")
        layout = QFormLayout(self)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://contoh.com/file.zip")
        layout.addRow("URL:", self.url_input)

        self.segment_input = QSpinBox()
        self.segment_input.setRange(1, 32)
        self.segment_input.setValue(8)
        layout.addRow("Jumlah segment:", self.segment_input)

        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText(
            "Opsional, untuk link yang butuh login/agreement (lihat DevTools > Network > header 'Cookie')"
        )
        layout.addRow("Cookie:", self.cookie_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return (
            self.url_input.text().strip(),
            self.segment_input.value(),
            self.cookie_input.text().strip(),
        )


class DownloadRow:
    """Menyimpan referensi widget & task untuk satu baris di tabel."""

    def __init__(self, task_id, url, output_path, num_segments, row_index, cookies=None):
        self.task_id = task_id
        self.url = url
        self.output_path = output_path
        self.num_segments = num_segments
        self.cookies = cookies
        self.row_index = row_index
        self.task = None
        self.status = "queued"  # queued -> downloading -> paused/done/error/cancelled
        self.downloaded_bytes = 0
        self.progress_bar = None
        self.status_label = None
        self.speed_label = None
        self.downloaded_label = None
        self.pause_btn = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IDM Clone - Download Manager")
        self.resize(1000, 520)

        self.rows = {}  # task_id -> DownloadRow
        self.pending_queue = []  # task_id yang menunggu slot kosong
        self.active_count = 0
        self.total_downloaded_session = 0  # total bytes semua download (yang sudah selesai)

        self._build_ui()

        # Nyalakan listener buat nangkep URL dari browser extension
        self.browser_listener = BrowserListener()
        self.browser_listener.url_received.connect(self.on_browser_url)
        self.browser_listener.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Baris kontrol atas ---
        top_layout = QHBoxLayout()
        add_btn = QPushButton("+ Tambah Download")
        add_btn.clicked.connect(self.open_add_dialog)
        top_layout.addWidget(add_btn)

        top_layout.addWidget(QLabel("Max download bersamaan:"))
        self.max_concurrent_input = QSpinBox()
        self.max_concurrent_input.setRange(1, 10)
        self.max_concurrent_input.setValue(2)
        self.max_concurrent_input.valueChanged.connect(self.try_start_pending)
        top_layout.addWidget(self.max_concurrent_input)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # --- Tabel antrian ---
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Nama File", "Progress", "Status", "Kecepatan", "Terdownload", "Ukuran", "Aksi"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # --- Status bar: total data terdownload ---
        self.total_label = QLabel("Total data terdownload sesi ini: 0 B")
        self.statusBar().addWidget(self.total_label)

    # ---------- Tambah & antrian ----------

    def open_add_dialog(self):
        dialog = AddDownloadDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url, num_segments, cookie_str = dialog.get_values()
        if not url:
            QMessageBox.warning(self, "Error", "Masukkan URL terlebih dahulu.")
            return

        suggested_name = filename_from_url(url)
        save_path, _ = QFileDialog.getSaveFileName(self, "Simpan sebagai", suggested_name)
        if not save_path:
            return

        cookies = parse_cookie_string(cookie_str) if cookie_str else None
        self._add_to_queue(url, save_path, num_segments, cookies=cookies)

    def on_browser_url(self, url):
        """
        Dipanggil (di main thread, aman untuk update GUI) saat ada URL masuk
        dari browser extension lewat BrowserListener.
        Otomatis simpan ke ~/Downloads tanpa dialog, biar alurnya cepat
        seperti IDM asli (klik kanan -> langsung masuk antrian).
        """
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        suggested_name = filename_from_url(url)
        save_path = os.path.join(downloads_dir, suggested_name)

        # Kalau nama file udah ada, tambahin angka biar gak ketimpa
        base, ext = os.path.splitext(save_path)
        counter = 1
        while os.path.exists(save_path):
            save_path = f"{base}({counter}){ext}"
            counter += 1

        self._add_to_queue(url, save_path, num_segments=8)
        self.raise_()
        self.activateWindow()

    def _add_to_queue(self, url, save_path, num_segments, cookies=None):
        task_id = str(uuid.uuid4())
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)

        row = DownloadRow(task_id, url, save_path, num_segments, row_index, cookies=cookies)

        self.table.setItem(row_index, 0, QTableWidgetItem(os.path.basename(save_path)))

        progress_bar = QProgressBar()
        progress_bar.setValue(0)
        self.table.setCellWidget(row_index, 1, progress_bar)
        row.progress_bar = progress_bar

        status_label = QLabel("Menunggu antrian...")
        self.table.setCellWidget(row_index, 2, status_label)
        row.status_label = status_label

        speed_label = QLabel("-")
        self.table.setCellWidget(row_index, 3, speed_label)
        row.speed_label = speed_label

        downloaded_label = QLabel("0 B")
        self.table.setCellWidget(row_index, 4, downloaded_label)
        row.downloaded_label = downloaded_label

        self.table.setItem(row_index, 5, QTableWidgetItem("-"))

        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        pause_btn = QPushButton("Pause")
        pause_btn.setEnabled(False)  # belum aktif selagi masih antri
        cancel_btn = QPushButton("Cancel")
        pause_btn.clicked.connect(lambda: self.toggle_pause(task_id))
        cancel_btn.clicked.connect(lambda: self.cancel_download(task_id))
        action_layout.addWidget(pause_btn)
        action_layout.addWidget(cancel_btn)
        self.table.setCellWidget(row_index, 6, action_widget)
        row.pause_btn = pause_btn

        self.rows[task_id] = row
        self.pending_queue.append(task_id)

        self.try_start_pending()

    def try_start_pending(self):
        """Jalankan task dari pending_queue selama slot concurrent masih ada."""
        max_concurrent = self.max_concurrent_input.value()
        while self.active_count < max_concurrent and self.pending_queue:
            task_id = self.pending_queue.pop(0)
            row = self.rows.get(task_id)
            if not row or row.status == "cancelled":
                continue
            self._start_task(row)

    def _start_task(self, row):
        task = DownloadTask(
            row.task_id, row.url, row.output_path,
            num_segments=row.num_segments, cookies=row.cookies,
        )
        task.progress_updated.connect(self.on_progress)
        task.status_changed.connect(self.on_status_changed)
        row.task = task
        self.active_count += 1
        task.start()

    # ---------- Kontrol per-item ----------

    def toggle_pause(self, task_id):
        row = self.rows.get(task_id)
        if not row:
            return
        if row.status == "error":
            self.retry_download(task_id)
            return
        if not row.task:
            return
        if row.status == "downloading":
            row.task.pause()
        elif row.status == "paused":
            row.task.resume()

    def retry_download(self, task_id):
        """Coba download ulang task yang gagal. File .parts lama (kalau ada)
        akan otomatis dipakai lagi buat resume oleh DownloadTask."""
        row = self.rows.get(task_id)
        if not row:
            return

        row.status = "queued"
        row.status_label.setText("Menunggu antrian...")
        row.pause_btn.setText("Pause")
        row.pause_btn.setEnabled(False)
        row.speed_label.setText("-")

        if task_id not in self.pending_queue:
            self.pending_queue.append(task_id)
        self.try_start_pending()

    def cancel_download(self, task_id):
        row = self.rows.get(task_id)
        if not row:
            return

        if row.status == "queued" and task_id in self.pending_queue:
            # Belum jalan sama sekali, cukup keluarkan dari antrian
            self.pending_queue.remove(task_id)
            row.status = "cancelled"
            row.status_label.setText("Dibatalkan")
            row.pause_btn.setEnabled(False)
            return

        if not row.task:
            return

        reply = QMessageBox.question(
            self, "Konfirmasi",
            "Batalkan download ini? Progress akan tetap tersimpan untuk dilanjutkan nanti.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            row.task.cancel()

    # ---------- Update dari sinyal ----------

    def on_progress(self, task_id, percent, speed, downloaded):
        row = self.rows.get(task_id)
        if not row:
            return

        # Update total sesi: kurangi kontribusi lama row ini, tambah yang baru
        self.total_downloaded_session += (downloaded - row.downloaded_bytes)
        row.downloaded_bytes = downloaded

        row.progress_bar.setValue(int(percent))
        row.speed_label.setText(f"{format_size(speed)}/s")
        row.downloaded_label.setText(format_size(downloaded))

        if row.task and row.task.total_size:
            self.table.item(row.row_index, 5).setText(format_size(row.task.total_size))

        self.total_label.setText(f"Total data terdownload sesi ini: {format_size(self.total_downloaded_session)}")

    def on_status_changed(self, task_id, status):
        row = self.rows.get(task_id)
        if not row:
            return
        row.status = status

        status_text_map = {
            "downloading": "Downloading...",
            "paused": "Dijeda",
            "done": "Selesai",
            "error": "Gagal",
            "cancelled": "Dibatalkan",
        }
        row.status_label.setText(status_text_map.get(status, status))

        if status == "downloading":
            row.pause_btn.setText("Pause")
            row.pause_btn.setEnabled(True)
        elif status == "paused":
            row.pause_btn.setText("Resume")
            row.pause_btn.setEnabled(True)
        elif status in ("done", "error", "cancelled"):
            if status == "error":
                row.pause_btn.setText("Retry")
                row.pause_btn.setEnabled(True)
            else:
                row.pause_btn.setEnabled(False)
            if status == "done":
                row.progress_bar.setValue(100)
            # Task benar-benar berhenti (berhasil/gagal/dibatalkan) -> bebaskan slot buat antrian berikutnya
            self.active_count = max(0, self.active_count - 1)
            self.try_start_pending()

    def closeEvent(self, event):
        self.browser_listener.stop()
        self.browser_listener.wait(1000)
        for row in self.rows.values():
            if row.task and row.task.isRunning():
                row.task.cancel()
                row.task.wait(2000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
