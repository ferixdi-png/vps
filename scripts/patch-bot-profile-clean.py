#!/usr/bin/env python3
from pathlib import Path
import sys

path = Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ferixdi/bot/main.py')
s = path.read_text()
old = '''        for fp_name, fp_label in (("chrome", "Chrome"), ("firefox", "Firefox")):\n            q_variant = dict(q)\n            q_variant["fp"] = fp_name\n            variant_label = f"{label} {fp_label}"\n            links.append(\n                f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_variant, safe='/')}#{quote(variant_label)}"\n            )\n'''
new = '''        short_ids = [str(x) for x in (reality.get("shortIds") or []) if x] or [sid]\n        friendly = {\n            17443: "⚡ VLESS gRPC Reality • Быстрый",\n            443: "🚀 VLESS gRPC Reality • HTTPS 443",\n            8443: "🔁 VLESS gRPC Reality • Резерв",\n            12443: "🛡️ VLESS XHTTP Reality • Стабильный",\n            13443: "🌐 VLESS XHTTP Reality • Универсальный",\n        }.get(int(port), f"VLESS {network.upper()} Reality • {port}")\n\n        # Publish exactly one normal profile per real endpoint. Additional\n        # shortIds stay on the server as hidden rotation/failover material.\n        q_variant = dict(q)\n        q_variant["sid"] = short_ids[0]\n        if network == "xhttp":\n            q_variant["mode"] = "auto"\n            q_variant["extra"] = json.dumps({\n                "xPaddingBytes": "100-1000",\n                "scStreamUpServerSecs": "20-80",\n                "xmux": {\n                    "maxConcurrency": "5",\n                    "hMaxRequestTimes": "300-600",\n                    "hMaxReusableSecs": "900-1800",\n                    "hKeepAlivePeriod": 0\n                }\n            }, separators=(",", ":"))\n        links.append(\n            f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_variant, safe='/')}#{quote(friendly)}"\n        )\n\n        # Only these three extra visible profiles have a distinct user-facing\n        # purpose. They use reserved shortIds but the same proven endpoints.\n        special_cases = {\n            443: "🧱 VLESS gRPC Reality • если режут нестандартные порты",\n            12443: "🛰️ VLESS XHTTP Reality • если режут gRPC/HTTP2",\n            13443: "🛟 VLESS XHTTP Reality • запасной маршрут при DPI",\n        }\n        if int(port) in special_cases and len(short_ids) >= 3:\n            q_case = dict(q)\n            q_case["sid"] = short_ids[2]\n            if network == "xhttp":\n                q_case["mode"] = "auto"\n                q_case["extra"] = json.dumps({\n                    "xPaddingBytes": "100-1000",\n                    "scStreamUpServerSecs": "20-80",\n                    "xmux": {\n                        "maxConcurrency": "5",\n                        "hMaxRequestTimes": "300-600",\n                        "hMaxReusableSecs": "900-1800",\n                        "hKeepAlivePeriod": 0\n                    }\n                }, separators=(",", ":"))\n            links.append(\n                f"vless://{row['vpn_uuid']}@{host}:{port}?{urlencode(q_case, safe='/')}#{quote(special_cases[int(port)])}"\n            )\n'''
count = s.count(old)
if count != 1:
    raise SystemExit(f'profile-clean patch expected 1 match, found {count}')
s = s.replace(old, new, 1)

old_url = '''    return f"{PUBLIC_SCHEME}://{host}{port}/sub/{row['sub_token']}"\n'''
new_url = '''    return f"{PUBLIC_SCHEME}://{host}{port}/sub/{row['sub_token']}?rev=8clean-20260915"\n'''
if s.count(old_url) != 1:
    raise SystemExit(f'profile-clean subscription revision expected 1 match, found {s.count(old_url)}')
s = s.replace(old_url, new_url, 1)

path.write_text(s)
print(f'profile-clean patched {path}')
