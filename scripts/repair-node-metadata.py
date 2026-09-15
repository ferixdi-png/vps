#!/usr/bin/env python3
"""Repair derived Reality client metadata from the live Xray config.

The Xray private key stays on the VPS. We derive its X25519 public key locally
using RFC 7748 math and only persist the public key to the node info file.
"""
import base64
import json
from pathlib import Path

CONFIG = Path("/opt/ferixdi/node/xray-config.json")
NODE_INFO = Path("/root/FERIXDI-NODE-INFO.txt")
P = 2**255 - 19
A24 = 121665


def decode_b64url(value: str) -> bytes:
    value = value.strip()
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode_b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def cswap(swap: int, x2: int, x3: int):
    mask = -swap
    dummy = mask & (x2 ^ x3)
    return x2 ^ dummy, x3 ^ dummy


def x25519_public(private_b64: str) -> str:
    raw = bytearray(decode_b64url(private_b64))
    if len(raw) != 32:
        raise ValueError(f"unexpected X25519 private key length: {len(raw)}")
    raw[0] &= 248
    raw[31] &= 127
    raw[31] |= 64
    scalar = int.from_bytes(raw, "little")

    x1 = 9
    x2, z2 = 1, 0
    x3, z3 = 9, 1
    swap = 0
    for t in range(254, -1, -1):
        kt = (scalar >> t) & 1
        swap ^= kt
        x2, x3 = cswap(swap, x2, x3)
        z2, z3 = cswap(swap, z2, z3)
        swap = kt
        a = (x2 + z2) % P
        aa = (a * a) % P
        b = (x2 - z2) % P
        bb = (b * b) % P
        e = (aa - bb) % P
        c = (x3 + z3) % P
        d = (x3 - z3) % P
        da = (d * a) % P
        cb = (c * b) % P
        x3 = ((da + cb) ** 2) % P
        z3 = (x1 * ((da - cb) ** 2)) % P
        x2 = (aa * bb) % P
        z2 = (e * (aa + A24 * e)) % P
    x2, x3 = cswap(swap, x2, x3)
    z2, z3 = cswap(swap, z2, z3)
    public_int = (x2 * pow(z2, P - 2, P)) % P
    return encode_b64url(public_int.to_bytes(32, "little"))


def parse_info(text: str):
    rows = []
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rows.append((k.strip(), v.strip()))
        elif line.strip():
            rows.append((line.strip(), None))
    return rows


def upsert(rows, key, value):
    out = []
    found = False
    for k, v in rows:
        if k == key:
            if not found:
                out.append((key, value))
                found = True
        else:
            out.append((k, v))
    if not found:
        out.append((key, value))
    return out


def main():
    cfg = json.loads(CONFIG.read_text())
    private_key = None
    short_id = None
    for inbound in cfg.get("inbounds", []):
        reality = inbound.get("streamSettings", {}).get("realitySettings", {})
        if reality.get("privateKey"):
            private_key = reality["privateKey"]
            ids = reality.get("shortIds") or []
            if ids:
                short_id = ids[0]
            break
    if not private_key:
        raise SystemExit("No Reality privateKey found in Xray config")

    public_key = x25519_public(private_key)
    rows = parse_info(NODE_INFO.read_text() if NODE_INFO.exists() else "")
    rows = upsert(rows, "PUBLIC_KEY", public_key)
    if short_id:
        rows = upsert(rows, "SHORT_ID", short_id)
    text = "\n".join(f"{k}={v}" if v is not None else k for k, v in rows) + "\n"
    NODE_INFO.write_text(text)
    NODE_INFO.chmod(0o600)
    print("Reality client metadata repaired: PUBLIC_KEY and SHORT_ID are present")


if __name__ == "__main__":
    main()
