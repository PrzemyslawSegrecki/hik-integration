# Security policy

This application can open a door or gate, so security reports are taken seriously.

## Reporting a vulnerability

Please do **not** open a public issue. Use GitHub's private reporting:
**Security → Report a vulnerability** on this repository. Include the version or commit, what you did and what
happened. You should get a first reply within a few days.

## Deployment advice

- Always set `APP_TOKEN` and/or `APP_PASSWORD` unless you deliberately use `TRUST_LOCAL_NETWORK=true` on a trusted LAN.
- Do not expose the app to the internet without HTTPS and authentication; do not expose go2rtc (port 1984) at all.
- Use a dedicated, strong password for the doorbell's admin account and keep `.env` readable only by you.
- If a secret was ever published (in an issue, log or commit), rotate it.
