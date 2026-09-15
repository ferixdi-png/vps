#!/usr/bin/env sh
set -eu
OUT="$(docker run --rm ghcr.io/xtls/xray-core:26.9.9 x25519)"
printf '%s\n' "$OUT"
echo "Short ID:"
openssl rand -hex 8
