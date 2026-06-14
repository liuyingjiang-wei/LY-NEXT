#!/usr/bin/env sh
# LY-NEXT dependency sync (keeps plugin packages; do not use plain `uv sync`).
exec uv run sync "$@"
