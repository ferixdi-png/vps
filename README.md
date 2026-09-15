# Ferixdi VPN Final Architecture

Production-oriented starter with:

- 3 independent VPN nodes
- USA / Germany / Netherlands layout
- 5 profiles per node = 15 total
- one personal subscription link per user
- per-node REALITY public keys
- health monitoring
- automatic removal of dead nodes from subscription output
- automatic recovery when a node becomes healthy again
- separate management layer
- Telegram bot
- signed subscription URLs
- Xray-core 26.9.9

## Architecture

```text
                    ┌───────────────────────┐
Telegram ---------->│ Management VPS        │
                    │ Bot / API / DB        │
                    │ Subscription / Monitor│
                    └──────────┬────────────┘
                               │
              health + config  │
          ┌────────────────────┼─────────────────────┐
          │                    │                     │
          v                    v                     v
     USA node              Germany node        Netherlands node
     5 profiles            5 profiles          5 profiles
```

User receives ONE link:

```text
https://vpn.example.com/sub/PERSONAL_ID?token=SIGNED_TOKEN
```

If all nodes are healthy, it returns 15 profiles.
If one node is down, it returns 10.
If two are down, it returns 5.

The user's link does not change.

## Recommended infrastructure

Use 4 VPS total:

1. Management VPS
2. USA VPN node
3. Germany VPN node
4. Netherlands VPN node

Prefer different hosting providers / ASNs for the VPN nodes.

## Node setup

On each VPN node:

```bash
cd nodes/node1
cp .env.example .env
../../scripts/generate-node-keys.sh
```

Put the generated private/public key and short ID into that node's `.env`.

Start:

```bash
docker compose up -d
```

Repeat for node2 and node3.

Open TCP ports:

```text
443
8443
12443
13443
17443
9444   # health endpoint
```

For production, protect the health endpoint by firewall so only the management server can reach it.

## Management setup

Copy:

```bash
cp .env.example .env
./scripts/generate-management-secrets.sh
```

Fill:

```text
BOT_TOKEN
ADMIN_IDS
PUBLIC_SUB_BASE_URL

NODE1_HOST
NODE1_HEALTH_URL
NODE1_REALITY_PUBLIC_KEY
NODE1_REALITY_SERVER_NAME
NODE1_REALITY_SHORT_ID

NODE2_...
NODE3_...
```

Then:

```bash
cd management
docker compose up -d
```

## Health logic

The monitor checks each node every 60 seconds.

Default:
- 2 consecutive failures -> node marked DOWN
- 2 consecutive successes -> node marked UP again

A DOWN node is automatically omitted from new subscription responses.

This prevents users from receiving a node that the management server currently considers unavailable.

## Important limitation

A central health checker cannot fully represent every user's ISP/network conditions.

A node may be reachable from the management server but unreachable from a specific mobile/home network.

For a commercial client, add client-side latency/availability testing as well.

## Security notes

- Never commit `.env`.
- Use a domain + HTTPS for the subscription service.
- Keep management API private.
- Restrict node health ports by firewall.
- Use a different REALITY keypair per VPN node.
- Back up the management database.
- Use different infrastructure providers for better resilience.
- Rotate credentials if a node is compromised.

## Current scope

This package builds the multi-node infrastructure and subscription resilience layer.

Billing/payment automation and live Xray user synchronization across all three nodes should be added as a dedicated provisioning service before a public launch.

## FERIXDI FLOW ONLY

Dedicated split-routing subscription:

`https://YOUR_DOMAIN/flow/PERSONAL_ID?token=SIGNED_TOKEN`

Flow-related Google domains -> healthy US Ferixdi route.
Everything else -> DIRECT.

See `FLOW-ONLY.md`.
