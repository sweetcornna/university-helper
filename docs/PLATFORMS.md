# Platform support

University Helper comes in two forms. The server edition is a web application (FastAPI backend, React/Vite frontend, PostgreSQL) meant for a Linux server. The desktop app (学道) packages the same backend for one user on Windows, macOS or Linux and needs no Docker, Postgres or Python. Android users open the server edition in the browser or install it as a PWA.

## Support matrix

| Platform | Supported use | Recommended path | Notes |
|---|---|---|---|
| Linux | Local development, production deployment, operations, desktop app | Docker Engine + Compose, Python 3.11, Node 20, Bash | The main target for servers. |
| macOS | Local development, deployment client, desktop app | Docker Desktop or Colima, Python 3.11, Node 20, Bash | Use the same `scripts/setup.sh` flow as Linux. |
| Windows | Server (Docker Desktop), deployment client, desktop app | `scripts/deploy_server.ps1` (PowerShell), or WSL2 Ubuntu + Docker Desktop WSL integration | The PowerShell script covers pull, start and health check. Set up TLS on a Linux box or your own reverse proxy. |
| Android | End-user app access | Install/open the PWA from Chrome/Edge at `https://shuake.cornna.xyz` | No native APK is shipped. Browser/PWA behavior depends on Android/browser version. |

## Desktop app

Installers are attached to each [GitHub release](https://github.com/sweetcornna/university-helper/releases):

| OS | File |
|---|---|
| Windows 10/11 | `xuedao_<ver>_windows_x64-setup.exe` or `xuedao_<ver>_windows_x64.msi` |
| macOS (Apple Silicon) | `xuedao_<ver>_darwin_aarch64.dmg` |
| macOS (Intel) | `xuedao_<ver>_darwin_x64.dmg` |
| Linux | `xuedao_<ver>_linux_amd64.AppImage` or `.deb` |

The builds are not code-signed, so Windows SmartScreen and macOS Gatekeeper warn on first launch. The [README](../README.md) explains how to open them anyway.

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

The guided installer only needs Docker. It writes a `.env` with random secrets,
pulls the prebuilt multi-arch images (`ghcr.io/sweetcornna/university-helper-{app,web}`),
starts the stack and waits for the health check. With `--domain` it also writes
a host-nginx vhost template and prints the certbot commands for TLS. Running it
again later keeps the existing secrets and data.

```bash
# Linux / macOS / WSL2 — first-time deploy
bash scripts/deploy_server.sh --domain <domain>     # production with TLS
bash scripts/deploy_server.sh --host <server-ip>    # plain-http on an IP
bash scripts/deploy_server.sh --build               # build from source instead of pulling
```

`--admin-email <email>` sets who sees new-version notices, and
`--allowed-hosts <list>` adds extra hostnames or IPs the site is opened with.
[DEPLOYMENT.md](./DEPLOYMENT.md) lists every option.

On native Windows (Docker Desktop), use the PowerShell equivalent:

```powershell
pwsh scripts/deploy_server.ps1 -Port 8080
```

It takes the same settings as `-Domain`, `-HostIp`, `-AdminEmail` and `-AllowedHosts`.

For incremental updates to an already-provisioned production box, use:

```bash
./scripts/hotfix_publish.sh <changed-file> [more-files...]
```
