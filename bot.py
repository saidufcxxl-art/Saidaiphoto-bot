AI Photo Bot — OpenAI + Telegram + Telegram Stars

1. Replace your bot.py with the included bot.py.
2. Add the included requirements.txt to the repository.
3. In Render:
   Build Command: pip install -r requirements.txt
   Start Command: python bot.py
4. Set these Environment Variables in Render:
   BOT_TOKEN=...
   OPENAI_API_KEY=...
   ADMIN_IDS=123456789
   PORT=10000
5. Optional: set PYTHON_VERSION=3.13.5 in Render.

Important:
- Do NOT put your OpenAI API key into the Python source code.
- Replicate is no longer used.
- The bot supports up to 2 reference photos.
- The credit is charged only after OpenAI successfully returns an image.
- User balances are currently stored in RAM and reset after a restart/redeploy.
  For a paid production bot, move balances to PostgreSQL/another database.
