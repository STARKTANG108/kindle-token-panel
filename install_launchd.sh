#!/bin/zsh
# 一键部署并注册 / 卸载 macOS 开机自启守护服务 (LaunchAgent)
# 自动同步运行副本至 ~/Library/Application Support/KindlePanel 以避开 macOS 对 ~/Documents 的 TCC 后台读取拦截
set -e

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$HOME/Library/Application Support/KindlePanel"
PLIST_LABEL="io.github.kindlepanel"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_OUT="$RUNTIME_DIR/server.log"
PORT="${KPANEL_PORT:-8765}"

# 动态探测本机局域网 IP
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

# 平滑迁移清理函数：卸载并移除任何历史旧版 kindlepanel plist
cleanup_legacy_plists() {
  for old_file in "$HOME/Library/LaunchAgents/"*kindlepanel*.plist(N); do
    if [[ "$old_file" != "$PLIST_PATH" && -f "$old_file" ]]; then
      launchctl unload "$old_file" 2>/dev/null || true
      rm -f "$old_file"
    fi
  done
}

if [[ "$1" == "uninstall" ]]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  cleanup_legacy_plists
  echo "[kindle-panel] 已安全卸载开机自启服务。"
  exit 0
fi

# 确保运行时目录存在
mkdir -p "$RUNTIME_DIR/static"
mkdir -p "$HOME/Library/LaunchAgents"

# 同步最新脚本与前端静态资源
cp "$SRC_DIR/server.py" "$RUNTIME_DIR/server.py"
cp "$SRC_DIR/static/index.html" "$RUNTIME_DIR/static/index.html"
chmod +x "$RUNTIME_DIR/server.py"

# 清理旧命名 plist 进程避免双重常驻
cleanup_legacy_plists

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>${RUNTIME_DIR}/server.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_OUT}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_OUT}</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "================================================================"
echo "  [kindle-panel] macOS 开机自启常驻服务已成功部署并加载！"
echo "  • 本机访问: http://127.0.0.1:${PORT}"
echo "  • 局域网 Kindle 访问: http://${LAN_IP}:${PORT}"
echo "  • 运行时目录: ${RUNTIME_DIR}"
echo "  • 日志文件: ${LOG_OUT}"
echo "================================================================"
