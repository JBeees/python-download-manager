#!/bin/bash
# Instalasi Native Messaging Host untuk IDM Clone (target: Brave browser)
#
# Cara pakai:
#   1. Load extension dulu di Brave (lihat instruksi di README), catat Extension ID-nya.
#   2. Jalankan: ./install.sh <EXTENSION_ID>
#
set -e

if [ -z "$1" ]; then
    echo "Pemakaian: ./install.sh <EXTENSION_ID>"
    echo "Extension ID didapat setelah kamu load extension unpacked di brave://extensions"
    exit 1
fi

EXTENSION_ID="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_HOST_SCRIPT="$SCRIPT_DIR/idm_native_host.py"

# Brave di Linux baca native messaging host dari folder ini:
TARGET_DIR="$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts"
TARGET_FILE="$TARGET_DIR/com.idmclone.host.json"

mkdir -p "$TARGET_DIR"
chmod +x "$NATIVE_HOST_SCRIPT"

# Isi placeholder path & extension ID dengan nilai sebenarnya
sed -e "s|__NATIVE_HOST_SCRIPT_PATH__|$NATIVE_HOST_SCRIPT|" \
    -e "s|__EXTENSION_ID__|$EXTENSION_ID|" \
    "$SCRIPT_DIR/com.idmclone.host.json" > "$TARGET_FILE"

echo "[+] Native host terpasang di: $TARGET_FILE"
echo "[+] Path script native host : $NATIVE_HOST_SCRIPT"
echo "[+] Extension ID terdaftar  : $EXTENSION_ID"
echo ""
echo "Pastikan gui_main.py sedang berjalan sebelum kamu klik 'Download with IDM Clone' di Brave."
