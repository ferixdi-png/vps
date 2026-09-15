# Ferixdi VPN

Current working layout for the first production node:

- Xray-core 26.9.9 on the VPS
- VLESS + REALITY profiles
- Telegram bot with personal UUID per user
- 3-day trial
- automatic expiry and disable
- one personal subscription URL
- SQLite user database
- admin commands for extension/disable/stats
- bot automatically rewrites Xray clients and restarts Xray safely

The repository is also structured so more nodes can be added later.

## Telegram bot

The bot code is in:

```text
bot/main.py
```

Main user flow:

```text
/start
→ 3 days free
→ personal UUID is activated in Xray
→ My key
→ personal subscription URL
```

Buttons:

- 🎁 3 days free
- 🔑 My key
- 📊 Status
- 📱 How to connect

Admin commands:

```text
/stats
/extend TELEGRAM_ID DAYS
/disable TELEGRAM_ID
```

Set your Telegram numeric ID in `ADMIN_IDS` to enable admin commands.

## Server paths

The first node currently expects:

```text
/opt/ferixdi/node/xray-config.json
/root/FERIXDI-NODE-INFO.txt
```

`FERIXDI-NODE-INFO.txt` must contain:

```text
IP=SERVER_IPV4
UUID=BOOTSTRAP_UUID
PUBLIC_KEY=REALITY_PUBLIC_KEY
SHORT_ID=REALITY_SHORT_ID
```

The Telegram bot never commits private credentials to GitHub.

## Install the bot on the VPS

Clone/update the repository and run:

```bash
curl -fsSL https://raw.githubusercontent.com/ferixdi-png/vps/main/scripts/install-bot.sh | bash
```

The installer:

- installs Python/venv requirements
- updates the repository
- installs the bot under `/opt/ferixdi/bot`
- creates a systemd service `ferixdi-bot`
- opens TCP 8080 for subscription delivery
- starts the bot if `/opt/ferixdi/.env` already contains a valid `BOT_TOKEN`

## Environment

Secrets belong only on the VPS, never in the repository.

Example `/opt/ferixdi/.env`:

```env
BOT_TOKEN=telegram_bot_token
ADMIN_IDS=123456789
TRIAL_DAYS=3
SUPPORT=@ferixdiii
PUBLIC_HOST=72.56.126.97
SUB_PORT=8080
XRAY_CONFIG=/opt/ferixdi/node/xray-config.json
XRAY_CONTAINER=ferixdi-xray
NODE_INFO=/root/FERIXDI-NODE-INFO.txt
DB_PATH=/opt/ferixdi/data/bot.db
```

GitHub Actions secret `BOT_TOKEN` is safe for GitHub Actions, but it is not automatically copied to the VPS. The VPS bot still needs the token in its own environment.

## Service management

```bash
systemctl status ferixdi-bot
systemctl restart ferixdi-bot
journalctl -u ferixdi-bot -f
```

Health endpoint:

```text
http://SERVER_IP:8080/health
```

Personal subscriptions look like:

```text
http://SERVER_IP:8080/sub/RANDOM_PERSONAL_TOKEN
```

The subscription response is a standard base64 V2Ray subscription containing the user's currently configured VLESS profiles.

## Xray synchronization

Bot-managed users are written with email identifiers in this form:

```text
tg:123456789
```

Manual/bootstrap Xray clients are preserved. When trial/paid access changes, only bot-managed clients are rebuilt.

Before replacing the Xray config the bot creates a backup. If Xray restart fails, the previous config is restored.

## Security

- never commit `.env`
- revoke any Telegram token shown in screenshots/chat and issue a new one
- keep `/opt/ferixdi/.env` mode 600
- use HTTPS/domain for public subscriptions before a larger commercial launch
- restrict management endpoints and SSH
- back up `/opt/ferixdi/data/bot.db`

## Next expansion

Planned multi-node layout:

```text
Germany + USA + Netherlands
```

Each node can have multiple transports while the user keeps one subscription. A later management layer can health-check nodes and omit unavailable profiles automatically.

## Google Flow-only mode

The repository also contains `FLOW-ONLY.md` and `client-profiles/flow-domains.txt` for a split-routing profile where selected Google Flow-related domains use the VPN and unrelated traffic remains direct.
