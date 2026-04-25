# Chessverse-monorepo — detailed overview

**Purpose:** AI Chess monorepo: frontends, backends, mobile, serverless, simulation, chat, coaching, infrastructure. pnpm workspaces; packages by domain; microservices in parallel layout.

---

## Root

- **package.json:** name "chessverse-monorepo", workspaces: packages/frontend/*, packages/backend/*, packages/mobile/*, packages/serverless/*, packages/simulation/*, packages/chat/*, packages/coaching/*, packages/infrastructure/*. Scripts: build, dev, test, lint, clean, install-all, backend:start, frontend:start, mobile:start, format, format:check, analyze:deps, analyze:structure, setup. packageManager pnpm@8.15.0; engines Node >= 18, pnpm >= 8.
- **pnpm install** at root; **pnpm run dev** runs dev recursively; **pnpm --filter <package-name> run dev** for one package.

---

## Packages (from README)

### Frontend

- packages/frontend/front-mock — mock frontend
- packages/frontend/chessai_fe_ts_redux — TypeScript/Redux frontend
- packages/frontend/fe — main frontend

### Backend

- packages/backend/server-be — main backend
- packages/backend/chess-ai-wss-tcp-server — WebSocket/TCP server
- packages/backend/server-receiver — receiver service
- packages/backend/tournament-service-be — tournament service (with qa-team, postman)

### Mobile

- packages/mobile/chess-ai-mobile-app

### Serverless

- packages/serverless/chess-ai-lambdas — AWS Lambda (Java 11+)

### Simulation

- packages/simulation/chess-simulator — game simulation logic

### Chat

- packages/chat/ai_chess_chat_server, packages/chat/ai_chess_chat

### Coaching

- packages/coaching/coach, packages/coaching/train-app (Python)

### Infrastructure

- packages/infrastructure/monolith — monolith app

---

## Microservices (microservices/)

- **bff/** — BFF service; README.
- **alerts/** — Alerts; README.
- **train/** — Training; README.
- **tournament/** — Tournament; README.
- **tournament-service-be/** — Tournament backend; README, postman/.
- **history/** — History service; README, README.dev, app/db/.
- **videostreaming/** — rtsp_to_hls, rtsp_emu_1, rtsp_emu_many; readme.md each.
- **simulation/simulation_service/** — Simulation service; README.
- **bridge/** — Bridge; README (monorepo has bridge; chessverse-monorepo may have same).
- microservices/README.md — overview.

---

## Commands (summary)

```bash
pnpm install
pnpm run dev
pnpm run build
pnpm run test
pnpm run lint
pnpm run format
pnpm run clean
pnpm run backend:start    # all backend packages
pnpm run frontend:start    # all frontend packages
pnpm run mobile:start
pnpm --filter <name> run dev
pnpm run install-all       # pnpm install --recursive
pnpm run setup             # install + analyze:deps
```

---

## Prerequisites

Node.js >= 18, pnpm >= 8. Python 3.x for some packages (e.g. train-app). Java 11+ for Lambda. See README.

---

## Structure notes

- Workspaces are under packages/ by domain. Some apps may also live under microservices/ (e.g. bff, train, history) with their own READMEs.
- packages/backend/tournament-service-be has qa-team/ and postman/ subdirs.
- packages/frontend/front-mock, packages/infrastructure/monolith have README.MD / README.md.

---

## Source

Repo README for full package list, install-all, and domain-specific commands. Individual package and microservice READMEs for run and config.
