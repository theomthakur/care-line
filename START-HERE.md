# MemberGuide: start here

Take2 x Reach voice agent hackathon, Fri 6 Nov 2026. Team: **Om** (voice, `src/`), **Aneesh** (booking core, `backend/core/`, `data/`), **Siddhant** (console and handoff, `frontend/`, `backend/ops/`).

This repo is the event starter kit (README.md and LIVEKIT_README.md are the kit's own, MIT licensed) plus our plan and an empty folder structure. No MemberGuide code exists yet. Everything is written at the event.

## First 10 minutes, everyone
1. Make your own free LiveKit Cloud account (credits are per person).
2. `uv sync`
3. `lk cloud auth`
4. `lk app env --write --destination .env.local` (never commit it)
5. `lk agent console`, and talk to Riley.

## Then
- Read `docs/MEMBERGUIDE-FINAL-PLAN.md`: your page is section 15 (Om), 16 (Aneesh) or 17 (Siddhant). The list at the top overrides anything below it.
- Aneesh turns section 8 into `contracts/`. Nobody starts a coding agent until it is agreed.
- Only Om's laptop runs `lk agent dev --deployment production`.
- Every coding agent reads `AGENTS.md` first.

## Folders
```
src/          Om        agent, tools, prompt (kit files plus ours)
contracts/    all       locked at 4:00
backend/core/ Aneesh    schema, rules, booking
backend/ops/  Siddhant  state, packet, summary, admin
frontend/     Siddhant  console
data/         Aneesh    seed
tests/        owners    core, ops, agent
docs/         plan, seminar notes, review
```
Synthetic data only. Never commit secrets.
