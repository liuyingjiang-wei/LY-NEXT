#!/usr/bin/env bash
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
        echo "检测到 Windows 环境，请运行 install-windows.ps1"
        echo "  powershell -ExecutionPolicy Bypass -File install-windows.ps1"
        ;;
    *)
        bash "$(dirname "$0")/install.sh"
        ;;
esac
