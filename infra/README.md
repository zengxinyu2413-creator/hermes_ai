# Hermes Infra — Operations Cheatsheet

## TimescaleDB

All commands assume cd ~/hermes_ai/infra. After re-login (docker group active), drop the sudo.

| Action | Command |
|---|---|
| Start | docker compose up -d |
| Stop (keep data) | docker compose stop |
| Restart | docker compose restart tsdb |
| Logs (live) | docker compose logs -f tsdb |
| Health | docker inspect --format='{{.State.Health.Status}}' hermes-tsdb |
| psql shell | docker compose exec tsdb psql -U hermes -d hermes |
| psql from script | docker compose exec -T tsdb psql -U hermes -d hermes (NOTE: -T disables TTY, required when piping SQL via heredoc) |
| Backup | docker compose exec tsdb pg_dump -U hermes -d hermes -F c -f /tmp/hermes.dump |
| Destroy (keep volume) | docker compose down |
| Nuke (delete data) | docker compose down -v (DANGER) |

## Connection from host (server side)

psql -h 127.0.0.1 -p 5432 -U hermes -d hermes
(password lives in ./.env)

## Connection from Mac (via SSH tunnel)

# On Mac (terminal 1):
ssh -L 5432:127.0.0.1:5432 xinyu@<tokyo-ip>

# On Mac (terminal 2):
psql -h 127.0.0.1 -p 5432 -U hermes -d hermes

## Secrets

.env is 600, in .gitignore. Never commit. Back up password to 1Password / Bitwarden.
