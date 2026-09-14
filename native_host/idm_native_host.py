#!/usr/bin/env python3
"""
IDM Clone - Native Messaging Host

Script ini dijalankan OTOMATIS oleh browser (Brave/Chrome), bukan manual.
Browser komunikasi lewat stdin/stdout pakai protokol Native Messaging:
- Tiap pesan diawali 4 byte little-endian yang menyatakan panjang JSON-nya.
- Kita baca JSON dari stdin, teruskan URL-nya ke gui_main.py lewat socket lokal,
  lalu balas ke browser lewat stdout dengan format yang sama.
"""

import sys
import json
import struct
import socket

# Port lokal yang didengarkan oleh gui_main.py (harus sama persis di kedua sisi)
APP_HOST = "127.0.0.1"
APP_PORT = 47821


def read_message():
    """Baca satu pesan dari stdin sesuai protokol Native Messaging Chrome."""
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) == 0:
        sys.exit(0)  # stdin ditutup oleh browser -> keluar
    message_length = struct.unpack("=I", raw_length)[0]
    message = sys.stdin.buffer.read(message_length).decode("utf-8")
    return json.loads(message)


def send_message(message_dict):
    """Kirim satu pesan balik ke browser lewat stdout, dengan prefix panjang 4-byte."""
    encoded = json.dumps(message_dict).encode("utf-8")
    length_prefix = struct.pack("=I", len(encoded))
    sys.stdout.buffer.write(length_prefix)
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def forward_to_app(url):
    """Kirim URL ke gui_main.py yang lagi jalan, lewat socket TCP localhost."""
    try:
        with socket.create_connection((APP_HOST, APP_PORT), timeout=3) as sock:
            payload = json.dumps({"url": url}).encode("utf-8")
            sock.sendall(payload)
        return {"status": "ok", "message": f"URL dikirim ke IDM Clone: {url}"}
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        return {"status": "error", "message": f"IDM Clone tidak berjalan atau tidak bisa dihubungi: {e}"}


def main():
    try:
        msg = read_message()
    except Exception as e:
        send_message({"status": "error", "message": f"Gagal baca pesan dari browser: {e}"})
        return

    if msg.get("action") == "add_download" and msg.get("url"):
        result = forward_to_app(msg["url"])
        send_message(result)
    else:
        send_message({"status": "error", "message": "Pesan tidak dikenali."})


if __name__ == "__main__":
    main()
