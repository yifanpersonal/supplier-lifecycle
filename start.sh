#!/usr/bin/env sh
# 在项目所在目录启动，只监听本机。
cd "$(dirname "$0")" || exit 1
python3 -m backend.server --port 8000
