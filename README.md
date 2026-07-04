# Job Hunter EDI - Kevin v2

Free automation stack:

- Python for job search and scoring
- Notion as CRM
- Telegram for notifications
- GitHub Actions for scheduled execution
- Gmail and iCloud job alerts for OCC, Dice, Glassdoor, Computrabajo, Indeed, and LinkedIn

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

Required to process OCC / Dice / Glassdoor / Computrabajo / Indeed / LinkedIn alerts received in Gmail:

- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `GMAIL_LABEL` with value `JobHunter`

Required to read alerts received directly in iCloud:

- `ICLOUD_USER` with value `arturo.gutierrez1995@icloud.com`
- `ICLOUD_APP_PASSWORD` with an Apple app-specific password
- `ICLOUD_MAILBOX` with value `INBOX`

## 4. Gmail setup

1. Create job alerts in OCC, Dice, Glassdoor, Computrabajo, Indeed, and LinkedIn using either contact email:
   - `arturo.gutierrez1995@icloud.com`
   - `kevin.arturo.gtz@gmail.com`
2. Alerts can arrive in either Gmail or iCloud; both inboxes are read independently through IMAP.
3. In Gmail, create a label named `JobHunter`.
4. Create filters that apply the `JobHunter` label to those alert emails.
5. Enable 2-Step Verification in your Google Account.
6. Create an App Password and save it as `GMAIL_APP_PASSWORD` in GitHub secrets.
7. Set `GMAIL_USER` to `kevin.arturo.gtz@gmail.com` and `GMAIL_LABEL` to `JobHunter`.
8. In your Apple Account, create an app-specific password and save it as `ICLOUD_APP_PASSWORD` in GitHub secrets. Set `ICLOUD_USER` to `arturo.gutierrez1995@icloud.com` and `ICLOUD_MAILBOX` to `INBOX`.

Notion stores matching jobs and Telegram sends the notifications. The contact emails are not notification destinations in the current implementation.

## 5. GitHub Actions workflow

Use only one workflow file:

`.github/workflows/action.yml`

The workflow runs manually with `workflow_dispatch` and automatically on a UTC cron schedule aligned with Mexico City business hours.
