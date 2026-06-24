# Platform Support

University Helper is a web application: a FastAPI backend, a React/Vite frontend, and PostgreSQL. The production target is a Linux server. Desktop platforms are supported as development/deployment clients, and Android is supported as a browser/PWA client.

## Support matrix

| Platform | Supported use | Recommended path | Notes |
|---|---|---|---|
| Linux | Local development, production deployment, operations | Docker Engine + Compose, Python 3.11, Node 20, Bash | Fully supported target for servers. |
| macOS | Local development and deployment client | Docker Desktop or Colima, Python 3.11, Node 20, Bash | Use the same `scripts/setup.sh` flow as Linux. |
| Windows | Server (Docker Desktop) and deployment client | `scripts/deploy_server.ps1` (PowerShell), or WSL2 Ubuntu + Docker Desktop WSL integration | PowerShell deploys the pull/up/health flow; TLS/host-nginx setup is left to a Linux box or your own reverse proxy. |
| Android | End-user app access | Install/open the PWA from Chrome/Edge at `https://shuake.cornna.xyz` | No native APK is shipped. Browser/PWA behavior depends on Android/browser version. |

## Linux quick start

```bash
bash scripts/setup.sh
make start
make test
```

## macOS quick start

Install Docker Desktop, Python 3.11, Node 20, and npm, then run:

```bash
bash scripts/setup.sh
make start
make test
```

## Windows quick start

1. Install WSL2 with Ubuntu.
2. Install Docker Desktop and enable WSL integration for the Ubuntu distribution.
3. Clone this repository inside the WSL filesystem, not under `/mnt/c`.
4. Run:

```bash
bash scripts/setup.sh
make start
make test
```

## Android PWA install

1. Open `https://shuake.cornna.xyz` in Chrome or Edge on Android.
2. Use the browser menu's install option, usually named **Install app** or **Add to Home screen**.
3. Launch University Helper from the home-screen icon.

University Helper does not currently include a native Android project, APK build, Capacitor wrapper, or React Native app.

## Server deployment

The guided installer only needs Docker. It generates a hardened `.env`, pulls the
prebuilt multi-arch images (`ghcr.io/sweetcornna/university-helper-{app,web}`),
starts the stack, waits for health, and — with `--domain` — scaffolds a
host-nginx + Let's Encrypt vhost.

```bash
# Linux / macOS / WSL2 — first-time deploy
bash scripts/deploy_server.sh --domain <domain>     # production with TLS
bash scripts/deploy_server.sh --host <server-ip>    # plain-http on an IP
bash scripts/deploy_server.sh --build               # build from source instead of pulling
```

On native Windows (Docker Desktop), use the PowerShell equivalent:

```powershell
pwsh scripts/deploy_server.ps1 -Port 8080
```

For incremental updates to an already-provisioned production box, use:

```bash
./scripts/hotfix_publish.sh <changed-file> [more-files...]
```
