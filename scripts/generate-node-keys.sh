#!/usr/bin/env sh
set -eu
docker run --rm ghcr.io/xtls/xray-core:26.9.9 x25519
echo "Short ID:"
openssl rand -hex 8
