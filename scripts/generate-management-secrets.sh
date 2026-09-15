#!/usr/bin/env sh
set -eu
echo "VPN_API_TOKEN=$(openssl rand -hex 32)"
echo "SUBSCRIPTION_SIGNING_SECRET=$(openssl rand -hex 32)"
