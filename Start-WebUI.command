#!/bin/bash
# macOS 一键启动图标：双击即在“终端”中打开并启动 WebUI。
# 实际逻辑在 scripts/start-webui-macos.sh，本文件仅做目录定位与转发。
cd "$(dirname "$0")"
exec bash scripts/start-webui-macos.sh
