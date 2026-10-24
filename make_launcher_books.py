#!/usr/bin/env python3
"""
Kindle X Migu Browser Launcher E-Book Generator
Generates PDF and MOBI files with embedded hyperlinks to awaken the hidden
experimental browser on Kindle X Migu (KFBJWI) and other Kindle devices.
Zero third-party dependencies - Pure Python 3 standard library.
"""

import os
import sys
import time
import socket
import struct
import argparse
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOK_TITLE = "⚡ Token 实时任务面板"


def detect_lan_ip():
    """
    Detect local network IPv4 address.
    On macOS, checks en0/en1 first to bypass VPN/TUN virtual adapters.
    """
    if sys.platform == "darwin":
        for iface in ("en0", "en1"):
            try:
                ip = subprocess.check_output(
                    ["ipconfig", "getifaddr", iface],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                if ip and not ip.startswith("127."):
                    return ip
            except Exception:
                pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def detect_mdns_host():
    """
    Detect local mDNS hostname (e.g. my-mac.local).
    """
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(
                ["scutil", "--get", "LocalHostName"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            if out:
                return f"{out}.local"
        except Exception:
            pass
    try:
        host = socket.gethostname()
        if host:
            if not host.endswith(".local"):
                return f"{host}.local"
            return host
    except Exception:
        pass
    return "kindlepanel.local"


# ==============================================================================
# 1. Standard PDF 1.4 Generator with Clickable URI Annotations
# ==============================================================================

class PDFBuilder:
    def __init__(self):
        self.objects = []

    def add_object(self, content):
        self.objects.append(content)
        return len(self.objects)

    def build(self):
        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]

        for i, obj in enumerate(self.objects, 1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("latin1"))
            if isinstance(obj, str):
                out.extend(obj.encode("latin1"))
            elif isinstance(obj, (bytes, bytearray)):
                out.extend(obj)
            out.extend(b"\nendobj\n")

        xref_offset = len(out)
        total_objs = len(self.objects) + 1
        out.extend(f"xref\n0 {total_objs}\n0000000000 65535 f \n".encode("latin1"))
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("latin1"))

        trailer = (
            f"trailer\n<<\n  /Size {total_objs}\n  /Root 1 0 R\n>>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        )
        out.extend(trailer.encode("latin1"))
        return bytes(out)


def generate_pdf(output_path, primary_url, backup_url):
    pdf = PDFBuilder()

    # 1. Catalog
    pdf.add_object("<< /Type /Catalog /Pages 2 0 R >>")

    # 2. Pages
    pdf.add_object("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")

    # Content Stream Operators
    # Canvas: 450 pt wide x 600 pt high (3:4 ratio for Kindle 6-inch e-ink)
    stream_lines = [
        # Primary Button Background & Border
        "0.93 0.93 0.93 rg",
        "30 320 390 230 re",
        "f",
        "0 0 0 RG",
        "3 w",
        "30 320 390 230 re",
        "S",
        # Primary Button Inner Accent Box
        "1 1 1 rg",
        "42 410 366 50 re",
        "f",
        "0 0 0 RG",
        "1.5 w",
        "42 410 366 50 re",
        "S",
        # Secondary Button Background & Border
        "0.96 0.96 0.96 rg",
        "30 110 390 170 re",
        "f",
        "0 0 0 RG",
        "2 w",
        "30 110 390 170 re",
        "S",
        # Primary Button Typography
        "BT",
        "/F2 20 Tf",
        "56 500 Td",
        "(KINDLE TOKEN & TASK PANEL) Tj",
        "ET",
        "BT",
        "/F2 16 Tf",
        "60 428 Td",
        "([ TAP HERE TO OPEN DASHBOARD ]) Tj",
        "ET",
        "BT",
        "/F1 15 Tf",
        "82 375 Td",
        f"({primary_url}) Tj",
        "ET",
        "BT",
        "/F1 11 Tf",
        "70 340 Td",
        "(Tap anywhere in this box to wake browser) Tj",
        "ET",
        # Secondary Button Typography
        "BT",
        "/F2 15 Tf",
        "50 240 Td",
        "(BACKUP LAN HOSTNAME LINK) Tj",
        "ET",
        "BT",
        "/F1 13 Tf",
        "50 200 Td",
        f"({backup_url}) Tj",
        "ET",
        "BT",
        "/F1 10 Tf",
        "50 150 Td",
        "(Tap here if your router supports mDNS) Tj",
        "ET",
        # Footer Note
        "BT",
        "/F1 9 Tf",
        "38 45 Td",
        "(Kindle X Migu Launcher - Bookmark this page once browser opens) Tj",
        "ET"
    ]
    stream_data = "\n".join(stream_lines).encode("latin1")

    # 3. Page Object
    pdf.add_object(
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 450 600] "
        "/Contents 4 0 R /Resources 5 0 R /Annots [6 0 R 7 0 R] >>"
    )

    # 4. Contents Object
    pdf.add_object(
        f"<< /Length {len(stream_data)} >>\nstream\n".encode("latin1")
        + stream_data
        + b"\nendstream"
    )

    # 5. Resources Object (Standard Type 1 fonts: Helvetica & Helvetica-Bold)
    pdf.add_object(
        "<< /Font << "
        "/F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> "
        "/F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> "
        ">> >>"
    )

    # 6. Primary Link Annotation: Rect [left, bottom, right, top]
    pdf.add_object(
        f"<< /Type /Annot /Subtype /Link /Rect [30 320 420 550] /Border [0 0 0] "
        f"/A << /Type /Action /S /URI /URI ({primary_url}) >> >>"
    )

    # 7. Secondary Link Annotation: Rect [left, bottom, right, top]
    pdf.add_object(
        f"<< /Type /Annot /Subtype /Link /Rect [30 110 420 280] /Border [0 0 0] "
        f"/A << /Type /Action /S /URI /URI ({backup_url}) >> >>"
    )

    pdf_bytes = pdf.build()
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    return len(pdf_bytes)


# ==============================================================================
# 2. Standard PalmDB + MOBI + EXTH Generator
# ==============================================================================

def generate_mobi(output_path, primary_url, backup_url):
    html_content = f"""<html><head><meta charset="utf-8"><title>Token 实时任务面板</title></head><body>
<h1 align="center">📟 Token 实时任务面板</h1>
<hr/>
<p align="center"><font size="6"><b><a href="{primary_url}">👉 [点击此处一键打开实时监控面板] 👈</a></b></font></p>
<p align="center"><a href="{primary_url}">{primary_url}</a></p>
<hr/>
<p align="center">备用地址：<a href="{backup_url}">{backup_url}</a></p>
<p>提示：打开网页后，可点击右上角菜单将该页面加入书签。</p>
</body></html>"""

    text_bytes = html_content.encode("utf-8")
    title_bytes = BOOK_TITLE.encode("utf-8")

    # PalmDOC Header (16 bytes)
    # Compression: 1 (none), Unused: 0, text_len, record_count: 1, record_size: 4096, curr_pos: 0
    palmdoc_hdr = struct.pack(">HHIHH I", 1, 0, len(text_bytes), 1, 4096, 0)

    # EXTH Header (Extended Header for book metadata)
    exth_records = []
    # 503: Updated Title
    exth_records.append(struct.pack(">II", 503, 8 + len(title_bytes)) + title_bytes)
    # 100: Creator / Author
    author_bytes = "KindlePanel".encode("utf-8")
    exth_records.append(struct.pack(">II", 100, 8 + len(author_bytes)) + author_bytes)
    # 101: Publisher
    exth_records.append(struct.pack(">II", 101, 8 + len(author_bytes)) + author_bytes)
    # 204: Creator Software (Calibre/Mobi compatible ID)
    exth_records.append(struct.pack(">II", 204, 8 + 4) + struct.pack(">I", 201))

    exth_body = b"".join(exth_records)
    exth_len = 12 + len(exth_body)
    pad_len = (4 - (exth_len % 4)) % 4
    exth_hdr = b"EXTH" + struct.pack(">II", exth_len + pad_len, len(exth_records)) + exth_body + (b"\x00" * pad_len)

    # MOBI Header (232 bytes, 0xE8)
    mobi_hdr_len = 232
    # Offset of full name from beginning of Record 0:
    # Record 0 = palmdoc_hdr (16) + mobi_hdr (232) + exth_hdr (len)
    fullname_offset = 16 + mobi_hdr_len + len(exth_hdr)
    fullname_len = len(title_bytes)

    mobi_fields = [
        b"MOBI",                           # 0: Identifier
        struct.pack(">I", mobi_hdr_len),   # 4: Header length
        struct.pack(">I", 2),              # 8: MOBI type (2 = Book)
        struct.pack(">I", 65001),          # 12: Text encoding (65001 = UTF-8)
        struct.pack(">I", 0x12345678),     # 16: Unique ID
        struct.pack(">I", 6),              # 20: File version
        struct.pack(">I", 0xFFFFFFFF),     # 24: Orthographic index
        struct.pack(">I", 0xFFFFFFFF),     # 28: Inflection index
        struct.pack(">I", 0xFFFFFFFF),     # 32: Index names
        struct.pack(">I", 0xFFFFFFFF),     # 36: Index keys
        b"\xFF" * 24,                      # 40: Extra index 0..5
        struct.pack(">I", 2),              # 64: First non-book index (Rec 1 is text, Rec 2 is FLIS/End)
        struct.pack(">I", fullname_offset),# 68: Full name offset
        struct.pack(">I", fullname_len),   # 72: Full name length
        struct.pack(">I", 0x0804),         # 76: Locale (zh-CN)
        struct.pack(">I", 0),              # 80: Input language
        struct.pack(">I", 0),              # 84: Output language
        struct.pack(">I", 6),              # 88: Min version
        struct.pack(">I", 0xFFFFFFFF),     # 92: First image index
        struct.pack(">I", 0),              # 96: Huffman record offset
        struct.pack(">I", 0),              # 100: Huffman record count
        struct.pack(">I", 0),              # 104: Huffman table offset
        struct.pack(">I", 0),              # 108: Huffman table length
        struct.pack(">I", 0x50),           # 112: EXTH flags (bit 6 = EXTH exists)
    ]
    mobi_hdr_base = b"".join(mobi_fields)
    mobi_hdr = mobi_hdr_base + (b"\x00" * (mobi_hdr_len - len(mobi_hdr_base)))

    # Record 0
    rec0 = palmdoc_hdr + mobi_hdr + exth_hdr + title_bytes + b"\x00\x00"

    # Record 1: Text HTML
    rec1 = text_bytes

    # Record 2: FLIS Record (Standard Mobipocket Font Limit Information Structure)
    rec2_flis = b"FLIS\x00\x00\x00\x08\x00\x41\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x01\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff"

    # Record 3: FCIS Record
    rec3_fcis = (
        b"FCIS\x00\x00\x00\x14\x00\x00\x00\x10\x00\x00\x00\x01\x00\x00\x00\x00"
        + struct.pack(">I", len(text_bytes))
        + b"\x00\x00\x00\x00\x00\x00\x00\x20\x00\x00\x00\x08\x00\x01\x00\x01\x00\x00\x00\x00"
    )

    # Record 4: EOF Record
    rec4_eof = b"\xe9\x8e\r\n"

    records = [rec0, rec1, rec2_flis, rec3_fcis, rec4_eof]
    num_recs = len(records)

    # PalmDB Header (78 bytes)
    db_name = "Token_Panel".encode("ascii").ljust(32, b"\x00")
    attrs = 0
    version = 0
    creation_time = int(time.time()) + 2082844800  # Seconds since Palm epoch (1904)
    mod_time = creation_time
    backup_time = 0
    mod_num = 0
    app_info_id = 0
    sort_info_id = 0
    db_type = b"BOOK"
    db_creator = b"MOBI"
    uid_seed = 0
    next_rec_list_id = 0

    pdb_header = struct.pack(
        ">32sHHIIIIII4s4sIIH",
        db_name, attrs, version, creation_time, mod_time,
        backup_time, mod_num, app_info_id, sort_info_id,
        db_type, db_creator, uid_seed, next_rec_list_id, num_recs
    )

    # Calculate record offsets
    # Header: 78 bytes + num_recs * 8 bytes + 2 bytes padding
    rec_list_len = 78 + (num_recs * 8) + 2
    rec_offsets = []
    curr_off = rec_list_len
    for r in records:
        rec_offsets.append(curr_off)
        curr_off += len(r)

    rec_headers = bytearray()
    for i, off in enumerate(rec_offsets):
        # 4 bytes offset, 1 byte attr (0), 3 bytes unique ID
        rec_headers.extend(struct.pack(">IB", off, 0))
        rec_headers.extend((i * 2).to_bytes(3, "big"))

    rec_headers.extend(b"\x00\x00")  # 2 bytes gap padding

    mobi_bytes = pdb_header + bytes(rec_headers) + b"".join(records)
    with open(output_path, "wb") as f:
        f.write(mobi_bytes)
    return len(mobi_bytes)


# ==============================================================================
# 3. MTP Push Utility (Kindle X Migu / Android MTP Mode)
# ==============================================================================

def push_to_kindle_mtp(files):
    """
    Push generated books to Kindle's Documents directory via libmtp tools.
    """
    mtp_folders_bin = shutil.which("mtp-folders")
    mtp_connect_bin = shutil.which("mtp-connect") or shutil.which("mtp-sendfile")

    if not mtp_folders_bin or not mtp_connect_bin:
        print("\n\033[33m[!] libmtp 工具未安装，无法直接通过 MTP 推送。\033[0m")
        print("    可在 macOS 上运行: \033[1mbrew install libmtp\033[0m")
        print("    或直接将生成的 .pdf / .mobi 文件手动复制至 Kindle 的 documents 目录。")
        return False

    print("\n[MTP] 正在检测 USB 连接的 Kindle MTP 设备...")
    try:
        proc = subprocess.run(
            [mtp_folders_bin],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8.0
        )
        if proc.returncode != 0 and not proc.stdout:
            print("\033[31m[!] 未检测到 MTP 设备，请检查 Kindle 是否已用 USB 数据线接入电脑。\033[0m")
            return False

        # Locate Documents directory
        doc_found = False
        for line in proc.stdout.splitlines():
            if "Documents" in line or "documents" in line:
                doc_found = True
                print(f"[MTP] 找到 Kindle 文档目录: {line.strip()}")
                break

        for file_path in files:
            fname = os.path.basename(file_path)
            print(f"[MTP] 正在推送 {fname} 至 Kindle...")
            # Use mtp-connect --sendfile or mtp-sendfile
            if shutil.which("mtp-connect"):
                res = subprocess.run(
                    ["mtp-connect", "--sendfile", file_path, fname],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15.0
                )
            else:
                res = subprocess.run(
                    ["mtp-sendfile", file_path, fname],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15.0
                )
            if res.returncode == 0 or "OK" in res.stdout:
                print(f"\033[32m[✓] 成功推送到 Kindle: {fname}\033[0m")
            else:
                print(f"\033[33m[!] 推送 {fname} 完成（状态码 {res.returncode}）\033[0m")
        return True

    except Exception as e:
        print(f"\033[31m[!] MTP 推送过程中出现异常: {e}\033[0m")
        return False


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main():
    default_port = int(os.environ.get("KPANEL_PORT", 8765))
    default_ip = detect_lan_ip()
    default_mdns = detect_mdns_host()

    parser = argparse.ArgumentParser(
        prog="make_launcher_books.py",
        description="Kindle X Migu Browser Launcher E-Book Generator"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Server port (default: {default_port})"
    )
    parser.add_argument(
        "--url",
        default=None,
        help=f"Custom primary dashboard URL (default: http://{default_ip}:<port>)"
    )
    parser.add_argument(
        "--backup-url",
        default=None,
        help=f"Custom backup dashboard URL (default: http://{default_mdns}:<port>)"
    )
    parser.add_argument(
        "--out-dir",
        default=BASE_DIR,
        help=f"Output directory (default: {BASE_DIR})"
    )
    parser.add_argument(
        "--push-mtp",
        action="store_true",
        help="Push generated books to USB MTP-connected Kindle via libmtp"
    )

    args = parser.parse_args()

    port = args.port
    primary_url = args.url or f"http://{default_ip}:{port}"
    backup_url = args.backup_url or f"http://{default_mdns}:{port}"
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    pdf_out = os.path.join(out_dir, "Token监控面板入口.pdf")
    mobi_out = os.path.join(out_dir, "Token监控面板入口.mobi")

    print("=" * 64)
    print("  Kindle X Migu Launcher E-Book Generator")
    print(f"  • Primary Link : {primary_url}")
    print(f"  • Backup Link  : {backup_url}")
    print(f"  • Output Dir   : {out_dir}")
    print("=" * 64)

    # 1. Generate PDF
    pdf_size = generate_pdf(pdf_out, primary_url, backup_url)
    print(f"  [✓] PDF Launcher created: {pdf_out}")
    print(f"      Size: {pdf_size:,} bytes | Page: 450x600 pt")

    # 2. Generate MOBI
    mobi_size = generate_mobi(mobi_out, primary_url, backup_url)
    print(f"  [✓] MOBI Launcher created: {mobi_out}")
    print(f"      Size: {mobi_size:,} bytes | Title: {BOOK_TITLE}")

    # 3. Optional MTP Push
    if args.push_mtp:
        push_to_kindle_mtp([pdf_out, mobi_out])

    print("\n  [完成] 电子书跳板制作完毕！可直接在 Kindle 书架打开并点击链接唤醒浏览器。")
    print("=" * 64)


if __name__ == "__main__":
    main()
