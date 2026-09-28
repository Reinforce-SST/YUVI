<div align="center">

# YUVI

**The Discord side of Reinforce Club SST.**

[Website](https://www.reinforce-sst.com/) · [Dashboard repository](https://github.com/Reinforce-SST/Reinforce-Student-Dashboard) · [API status](https://api.reinforce-sst.com/health)

</div>

---

YUVI handles private college-account verification, Discord roles, support
tickets, and the Idea Jar. Its FastAPI service lets the Reinforce dashboard
create a Discord ticket thread and relay messages. Both repositories share
Firestore; the [data contract](https://github.com/Reinforce-SST/Reinforce-Student-Dashboard/blob/main/docs/DATA_CONTRACT.md)
is the source of truth for documents crossing that boundary.

## Rollout status · 29 September 2026

| Item | State |
|---|---|
| [Ticket bridge PR #10](https://github.com/Reinforce-SST/YUVI/pull/10) | Merged into `main` |
| [Queue/bridge repair PR #13](https://github.com/Reinforce-SST/YUVI/pull/13) | Open; needed after a later queue merge caused dashboard thread requests to return 422 |
| [Dashboard review PR #37](https://github.com/Reinforce-SST/Reinforce-Student-Dashboard/pull/37) | Open; adds admin SPG approval and three mobile dashboard layouts |
| [Hosted Render health](https://yuvi-182k.onrender.com/health) | Returned HTTP 503 |
| [Dashboard API health](https://api.reinforce-sst.com/health) | Returned HTTP 200 |

The dashboard-to-Discord bridge is **not verified live**. A local passing test
or a running bot does not establish that the API callback, secret, Discord
permissions, and Firestore link all work on the deployed pair. Use the
[release checklist](https://github.com/Reinforce-SST/Reinforce-Student-Dashboard/blob/main/docs/verification.md)
after PR #13 is merged and deployed.

## Member flow

1. A member runs `/auth` (or uses the verification panel) in Discord. YUVI
   sends an ephemeral, ten-minute link to `{FRONTEND_AUTH_URL}#link_token=...`.
2. The member signs in with a verified `@sst.scaler.com` Google account. The
   dashboard API validates the private proof and links the Firebase UID to
   the Discord ID in Firestore.
3. The API calls `POST /internal/verify-success` with the shared internal
   secret. YUVI grants the Verified Member role and confirms the result.

The private link is a credential. Do not paste it into chat, logs, issues, or
screenshots. Old raw Discord-ID links are not ownership proof; members should
run `/auth` again.

## Ticket bridge

Discord tickets and dashboard tickets use the same `tickets/{ticket_id}`
documents and message subcollection. The dashboard API uses the private
`POST /tickets/create-thread` and `POST /tickets/relay-message` endpoints.
Compatibility aliases under `/internal/tickets/` exist for older callers.
All bridge requests require `X-Internal-Secret` matching `BOT_INTERNAL_SECRET`.
Thread creation is designed to resume partial setup without creating a second
thread. PR #13 repairs the endpoint registration on current `main`; do not
assume this works in production until the live acceptance test passes.

| Category | Typical request |
|---|---|
| SPG registration | Team, track, duration, reporting cadence |
| Resource request | Compute, equipment, credits, mentorship |
| Support | Questions and access problems |
| Idea Jar | Project ideas and feedback |
| Report | Confidential conduct or safety issue |

An SPG registration is a ticket for review. Changing its ticket status in
Discord does not create an SPG document. Dashboard PR #37 adds an admin-only
approval action that validates the stored ticket, creates one SPG, and resolves
the ticket in the same transaction. Project groups require a proposition PDF.

## Run locally

Use Python 3.13+ and [uv](https://docs.astral.sh/uv/). Copy `.env.example` to
`.env` and fill in your own Discord, Firebase, and bridge values. Never commit
the `.env` file or a service account key.

```bash
cp .env.example .env
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python main.py
```

`HOST` and `PORT` control the FastAPI listener; `.env.example` uses port 8001.
`0.0.0.0` binds all interfaces. Restrict public access with the host firewall
or reverse proxy. The local API and bot start together; use one bot instance
per Discord token.

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN`, `GUILD_ID` | Bot identity and server |
| `VERIFIED_ROLE_ID` | Role granted after verified linking |
| `FRONTEND_AUTH_URL` | Next.js `/auth` route, including its path |
| `BOT_INTERNAL_SECRET` | Shared secret with the dashboard API |
| `API_BASE_URL` | Dashboard API `/api/v1` base |
| `TICKETS_CHANNEL_ID` | Parent channel for private threads |
| `GOOGLE_APPLICATION_CREDENTIALS` or `FIREBASE_SERVICE_ACCOUNT_JSON` | Firebase Admin credentials |

`KICKOFF_ROLE_ID` and `ASSIGN_KICKOFF_ROLE` control the optional orientation
role. Keep YUVI's Firebase project and internal secret aligned with the
dashboard API.

## Code map

| Path | Responsibility |
|---|---|
| `cogs/` | Discord commands for auth, tickets, and ideas |
| `views/` | Persistent panels and ticket controls |
| `models/` | Firestore-facing ticket and idea models |
| `utils/` | Firestore access, member links, ticket manager, queue |
| `server.py` | FastAPI callbacks and bot lifecycle |
| `tests/` | Local fixtures; no production Discord or Firestore calls |
