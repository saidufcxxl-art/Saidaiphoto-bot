# Telegram AI Photo Bot — Replicate / FLUX.2 Max

## Environment variables on Render

- BOT_TOKEN
- REPLICATE_API_TOKEN
- ADMIN_IDS
- PORT=10000

## Model

black-forest-labs/flux-2-max

The bot accepts 1–2 reference photos and then a text instruction.
Telegram Stars packages:
- 50 Stars = 5 generations
- 100 Stars = 10 generations
- 150 Stars = 15 generations
- 2 free generations per user
- Admin IDs = unlimited

Important: balances are stored in RAM and reset after a Render restart/redeploy.
For a real paid production bot, move balances to SQLite/Postgres later.
