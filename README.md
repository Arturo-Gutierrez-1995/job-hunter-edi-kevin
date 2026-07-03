# Job Hunter EDI - Kevin v2

Free automation stack:

- Python for job search and scoring
- Notion as CRM
- Telegram for notifications
- GitHub Actions for scheduled execution
- Gmail job alerts for LinkedIn, Indeed, OCC, Computrabajo, and Glassdoor

## 1. Local install

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

## 3. GitHub secrets

Create these secrets under:

`Settings → Secrets and variables → Actions → New repository secret`

Required:

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional for LinkedIn / Indeed / OCC / Computrabajo / Glassdoor via email alerts:

- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `GMAIL_LABEL` with value `JobHunter`

## 4. Gmail setup

1. Create job alerts in LinkedIn, Indeed, OCC, Computrabajo, and Glassdoor.
2. In Gmail, create a label named `JobHunter`.
3. Create filters that apply the `JobHunter` label to those alert emails.
4. Enable 2-Step Verification in your Google Account.
5. Create an App Password and save it as `GMAIL_APP_PASSWORD` in GitHub secrets.

## 5. GitHub Actions workflow

Use only one workflow file:

`.github/workflows/action.yml`

The workflow runs manually with `workflow_dispatch` and automatically on a UTC cron schedule aligned with Mexico City business hours.
