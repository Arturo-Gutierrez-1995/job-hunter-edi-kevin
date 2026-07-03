# Job Hunter EDI - Kevin

Free automation stack:

- Python for job search and scoring
- Notion as CRM
- Telegram for notifications
- GitHub Actions for scheduled execution

## 1. Install locally

```bash
python -m venv .venv
source .venv/bin/activate   # Mac/Linux
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with your real tokens.

## 2. Run locally

```bash
python src/job_hunter.py
```

## 3. GitHub Actions

Create a private GitHub repo, upload these files, then add secrets:

- NOTION_TOKEN
- NOTION_DATABASE_ID
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

The workflow runs Monday-Friday every 4 hours and can also be started manually.

## 4. Configure sources

Edit `config.yaml`:

- Add Lever slugs under `lever_companies`
- Add Greenhouse slugs under `greenhouse_companies`
- Adjust match thresholds
- Add/remove keywords

## 5. Free mode vs AI mode

This project is free by default because it uses local keyword scoring. Claude API is optional and not required.
