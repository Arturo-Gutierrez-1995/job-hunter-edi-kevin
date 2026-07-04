import hashlib
import html
import imaplib
import json
import os
import re
import email as email_lib
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
raw_notion_database_id = os.getenv("NOTION_DATABASE_ID", "").strip()
notion_id_match = re.search(r"([0-9a-fA-F]{32})", raw_notion_database_id)
NOTION_DATABASE_ID = (notion_id_match.group(1) if notion_id_match else raw_notion_database_id.replace("-", "").strip())

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GMAIL_USER = os.getenv("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
GMAIL_LABEL = os.getenv("GMAIL_LABEL", "JobHunter").strip() or "JobHunter"

ICLOUD_USER = os.getenv("ICLOUD_USER", "").strip()
ICLOUD_APP_PASSWORD = os.getenv("ICLOUD_APP_PASSWORD", "").strip().replace(" ", "")
ICLOUD_MAILBOX = os.getenv("ICLOUD_MAILBOX", "INBOX").strip() or "INBOX"

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")

HEADERS = {
    "User-Agent": "KevinJobHunter/1.0 (+https://github.com/)"
}

NOTION_SCHEMA_CACHE: Optional[Dict[str, Any]] = None

EMAIL_NEGATIVE_KEYWORDS = {
    "password", "contraseña", "restablecido", "reset", "security", "seguridad",
    "unsubscribe", "desuscribir", "lamentamos que te vayas", "newsletter",
    "verification", "verificación", "codigo", "código", "account", "cuenta"
}

EMAIL_JOB_SIGNAL_KEYWORDS = {
    "job", "jobs", "vacante", "vacantes", "empleo", "empleos", "opportunity", "opportunities",
    "alert", "alerta", "hiring", "contratando", "application", "aplicar", "apply",
    "edi", "integration", "integraciones", "analyst", "specialist", "engineer", "support"
}

PROFILE_SKILLS = {
    "edi", "x12", "edifact", "as2", "sftp", "ftp", "mdn", "trading partner", "b2b",
    "ibm sterling", "sterling integrator", "axway", "b2bi", "stedi", "sap", "idoc",
    "servicenow", "incident management", "sla", "production support", "application support",
    "json", "xml", "postman", "oauth", "bigquery", "python", "aws", "linux", "api", "rest", "soap",
    "walmart retail link", "retail link", "mapping", "envelope", "onboarding"
}

SKILL_WEIGHTS = {
    # Core EDI/B2B
    "edi": 14, "x12": 12, "edifact": 8, "as2": 12, "sftp": 7, "ftp": 5, "mdn": 8,
    "trading partner": 10, "b2b": 12, "mapping": 9, "envelope": 8, "onboarding": 7,
    "850": 5, "855": 5, "856": 5, "810": 5, "997": 5, "860": 4, "864": 4,
    # Platforms
    "ibm sterling": 14, "sterling integrator": 14, "axway": 12, "b2bi": 12, "stedi": 12,
    "opentext": 7, "seeburger": 7,
    # SAP / middleware
    "sap": 9, "idoc": 10, "sap po": 8, "sap pi": 8, "sap cpi": 7, "sap integration suite": 7,
    "middleware": 8, "integration": 7, "integrations": 7,
    # Support / ops
    "servicenow": 9, "incident management": 8, "sla": 8, "production support": 9,
    "application support": 8, "troubleshooting": 8, "monitoring": 7,
    # APIs / automation
    "json": 7, "xml": 7, "postman": 7, "oauth": 6, "bigquery": 5, "python": 5,
    "api": 7, "rest": 6, "soap": 5, "aws": 4, "linux": 4,
}

NEGATIVE_KEYWORDS = {
    "nurse": -30, "physician": -30, "driver": -25, "cashier": -25, "restaurant": -20,
    "sales representative": -20, "real estate": -20, "insurance agent": -20,
    "marketing intern": -20, "warehouse associate": -18,
}

MARKET_GAPS = [
    "mulesoft", "boomi", "sap cpi", "sap integration suite", "azure", "sql", "docker",
    "kubernetes", "java", "javascript", "snowflake", "power bi", "oracle", "workato"
]


def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>|</li>|</h\d>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def job_hash(job: Dict[str, Any]) -> str:
    base = "|".join([
        normalize_text(job.get("company", "")),
        normalize_text(job.get("title", "")),
        normalize_text(job.get("location", "")),
        normalize_text(job.get("url", "")),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def contains_any(text: str, keywords: List[str]) -> bool:
    lowered = normalize_text(text)
    return any(k.lower() in lowered for k in keywords)


def score_job(job: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    title = job.get("title", "") or ""
    desc = job.get("description", "") or ""
    full_text = normalize_text(f"{title} {desc}")
    title_text = normalize_text(title)

    points = 0
    max_points = sum(v for v in SKILL_WEIGHTS.values() if v > 0)
    matched = []

    for skill, weight in SKILL_WEIGHTS.items():
        if skill in full_text:
            points += weight
            matched.append(skill)
            if skill in title_text:
                points += min(10, weight)  # title boost

    penalties = 0
    for bad, penalty in NEGATIVE_KEYWORDS.items():
        if bad in full_text:
            penalties += abs(penalty)

    # Role title bonus
    target_roles = [r.lower() for r in config["profile"].get("target_roles", [])]
    role_bonus = 0
    for role in target_roles:
        role_tokens = [t for t in re.split(r"\W+", role) if len(t) > 2]
        if role in title_text or sum(1 for t in role_tokens if t in title_text) >= max(1, len(role_tokens) - 1):
            role_bonus += 12
            break

    raw_score = ((points + role_bonus - penalties) / max_points) * 100 * 2.4
    overall = int(max(0, min(100, round(raw_score))))

    core_matches = [s for s in matched if s in PROFILE_SKILLS]
    technical = int(min(100, max(overall, len(core_matches) * 8))) if core_matches else overall
    ats = int(round((overall * 0.65) + (technical * 0.35)))

    missing = [gap for gap in MARKET_GAPS if gap in full_text and gap not in PROFILE_SKILLS]

    if overall >= 90:
        priority = "★★★★★ Apply immediately"
        interview_probability = "High"
        offer_probability = "Medium-High"
    elif overall >= 80:
        priority = "★★★★☆ Strong candidate"
        interview_probability = "Medium-High"
        offer_probability = "Medium"
    elif overall >= 70:
        priority = "★★★☆☆ Worth reviewing"
        interview_probability = "Medium"
        offer_probability = "Low-Medium"
    elif overall >= 55:
        priority = "★★☆☆☆ Archive / low touch"
        interview_probability = "Low"
        offer_probability = "Low"
    else:
        priority = "★☆☆☆☆ Skip"
        interview_probability = "Very Low"
        offer_probability = "Very Low"

    recruiter_message = build_recruiter_message(job, overall, matched[:8])

    return {
        "overall_match": overall,
        "technical_match": technical,
        "ats_match": ats,
        "priority": priority,
        "top_matching_skills": sorted(list(dict.fromkeys(matched)))[:12],
        "missing_skills": sorted(list(dict.fromkeys(missing)))[:8],
        "interview_probability": interview_probability,
        "offer_probability": offer_probability,
        "recommendation": make_recommendation(job, overall, matched, missing),
        "recruiter_message": recruiter_message,
    }


def make_recommendation(job: Dict[str, Any], score: int, matched: List[str], missing: List[str]) -> str:
    if score >= 80:
        return (
            f"Apply. Strong alignment with Kevin's EDI/B2B integration profile. "
            f"Main matching skills: {', '.join(matched[:8])}. "
            f"Review gaps before applying: {', '.join(missing) if missing else 'No critical gaps detected.'}"
        )
    if score >= 55:
        return (
            f"Save for review. Partial match with integration/support profile, but not strong enough for immediate alert. "
            f"Matching signals: {', '.join(matched[:6]) if matched else 'limited'}."
        )
    return "Skip. Low relevance to EDI, B2B integrations, SAP, middleware, or application support."


def build_recruiter_message(job: Dict[str, Any], score: int, matched: List[str]) -> str:
    company = job.get("company", "your company")
    title = job.get("title", "the role")
    skills = ", ".join(matched[:5]) if matched else "EDI/B2B integrations and production support"
    return (
        f"Hi, I’m Kevin Gutierrez. I noticed the {title} opening at {company}. "
        f"My background aligns well with this role, especially around {skills}. "
        f"I have hands-on experience supporting EDI/B2B integrations, AS2/SFTP connectivity, "
        f"IBM Sterling, Axway B2Bi, STEDI, SAP, ServiceNow, and SLA-driven production support. "
        f"I’d be glad to connect and share my CV."
    )


def fetch_remoteok(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config["sources"].get("remoteok"):
        return []
    url = "https://remoteok.com/api"
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"RemoteOK error: {e}")
        return []
    jobs = []
    for item in data:
        if not isinstance(item, dict) or "position" not in item:
            continue
        desc = clean_html(item.get("description", ""))
        job = {
            "source": "RemoteOK",
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "Remote"),
            "salary": item.get("salary", ""),
            "url": item.get("url", ""),
            "description": desc,
            "remote_type": "Remote",
            "posted_at": item.get("date", ""),
        }
        jobs.append(job)
    return jobs[: config["filters"].get("max_jobs_per_source", 80)]


def fetch_arbeitnow(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config["sources"].get("arbeitnow"):
        return []
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print(f"Arbeitnow error: {e}")
        return []
    jobs = []
    for item in data:
        desc = clean_html(item.get("description", ""))
        remote = "Remote" if item.get("remote") else "Unknown"
        job = {
            "source": "Arbeitnow",
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", ""),
            "salary": "",
            "url": item.get("url", ""),
            "description": desc,
            "remote_type": remote,
            "posted_at": item.get("created_at", ""),
        }
        jobs.append(job)
    return jobs[: config["filters"].get("max_jobs_per_source", 80)]


def fetch_lever(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config["sources"].get("lever"):
        return []
    jobs = []
    for slug in config.get("lever_companies", []):
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"Lever error for {slug}: {e}")
            continue
        for item in data:
            categories = item.get("categories", {}) or {}
            desc_parts = [
                item.get("descriptionPlain", ""),
                item.get("additionalPlain", ""),
            ]
            for lst in item.get("lists", []) or []:
                desc_parts.append(lst.get("text", ""))
                for content in lst.get("content", []) or []:
                    desc_parts.append(content.get("text", ""))
            job = {
                "source": "Lever",
                "title": item.get("text", ""),
                "company": slug,
                "location": categories.get("location", ""),
                "salary": "",
                "url": item.get("hostedUrl", ""),
                "description": clean_html("\n".join(desc_parts)),
                "remote_type": categories.get("commitment", "Unknown"),
                "posted_at": "",
            }
            jobs.append(job)
    return jobs


def fetch_greenhouse(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config["sources"].get("greenhouse"):
        return []
    jobs = []
    for slug in config.get("greenhouse_companies", []):
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            data = r.json().get("jobs", [])
        except Exception as e:
            print(f"Greenhouse error for {slug}: {e}")
            continue
        for item in data:
            loc = item.get("location", {}) or {}
            job = {
                "source": "Greenhouse",
                "title": item.get("title", ""),
                "company": slug,
                "location": loc.get("name", ""),
                "salary": "",
                "url": item.get("absolute_url", ""),
                "description": clean_html(item.get("content", "")),
                "remote_type": "Unknown",
                "posted_at": item.get("updated_at", ""),
            }
            jobs.append(job)
    return jobs


GENERIC_LINK_TEXT = {
    "apply", "apply now", "view job", "view jobs", "see job", "see jobs", "learn more",
    "ver empleo", "ver empleos", "postularme", "postular", "aplicar", "solicitar",
    "view details", "details", "more", "más", "ver oferta", "ver vacante"
}

BAD_LINK_FRAGMENTS = (
    "unsubscribe", "preferences", "settings", "privacy", "terms", "help", "support",
    "login", "signin", "signup", "share", "trk=", "utm_campaign=unsubscribe"
)


def decode_mime_header(value: str) -> str:
    if not value:
        return ""
    decoded_parts = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts).strip()


def get_message_body(msg) -> Tuple[str, str]:
    plain_parts: List[str] = []
    html_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", "")).lower()
            if "attachment" in content_disposition:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
            if content_type == "text/plain":
                plain_parts.append(text)
            elif content_type == "text/html":
                html_parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)

    return "\n".join(plain_parts), "\n".join(html_parts)


def html_body_to_text(html_body: str) -> str:
    if not html_body:
        return ""
    soup = BeautifulSoup(html_body, "html.parser")
    return soup.get_text(" ", strip=True)


def clean_tracking_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url).strip().strip("<>()[]{}.,;\"'")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    # Many email links wrap the real target as url=, q=, u=, or redirectUrl=.
    for key in ("url", "q", "u", "redirectUrl", "target", "to"):
        if key in query and query[key]:
            candidate = unquote(query[key][0])
            if candidate.startswith("http"):
                return clean_tracking_url(candidate)
    return url


def detect_gmail_source(sender: str, subject: str, url: str, config: Dict[str, Any]) -> str:
    blob = normalize_text(f"{sender} {subject} {url}")
    for source, rules in (config.get("gmail_alert_sources") or {}).items():
        domains = rules.get("domains", []) or []
        if source.lower() in blob or any(domain.lower() in blob for domain in domains):
            return source
    return "Job Alert"


def is_probable_job_link(url: str, config: Dict[str, Any]) -> bool:
    lowered = url.lower()
    if not lowered.startswith("http"):
        return False
    if any(bad in lowered for bad in BAD_LINK_FRAGMENTS):
        return False

    for rules in (config.get("gmail_alert_sources") or {}).values():
        patterns = [p.lower() for p in (rules.get("link_patterns", []) or [])]
        domains = [d.lower() for d in (rules.get("domains", []) or [])]
        if any(pattern in lowered for pattern in patterns):
            return True
        # Allow platform URLs if they look job-related, even when the exact path changes.
        if any(domain in lowered for domain in domains) and any(term in lowered for term in ("job", "empleo", "vacante", "oferta")):
            return True
    return False


def extract_job_links(plain_body: str, html_body: str, config: Dict[str, Any]) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    seen = set()

    if html_body:
        soup = BeautifulSoup(html_body, "html.parser")
        for a in soup.find_all("a", href=True):
            href = clean_tracking_url(a.get("href", ""))
            text = clean_html(a.get_text(" ", strip=True))
            if not text or normalize_text(text) in GENERIC_LINK_TEXT:
                text = ""
            if href and is_probable_job_link(href, config) and href not in seen:
                seen.add(href)
                candidates.append((href, text))

    combined_text = f"{plain_body}\n{html_body}"
    for match in re.finditer(r"https?://[^\s<>\"']+", combined_text):
        href = clean_tracking_url(match.group(0))
        if href and is_probable_job_link(href, config) and href not in seen:
            seen.add(href)
            candidates.append((href, ""))

    return candidates[:15]


def make_title_from_email(subject: str, anchor_text: str, source: str) -> str:
    anchor = clean_html(anchor_text or "")
    subject_clean = clean_html(subject or "")
    if anchor and len(anchor) >= 8 and normalize_text(anchor) not in GENERIC_LINK_TEXT:
        return anchor[:180]
    if subject_clean:
        return subject_clean[:180]
    return f"{source} job alert"


def fetch_imap_alerts(
    config: Dict[str, Any],
    provider: str,
    host: str,
    user: str,
    app_password: str,
    mailbox: str,
) -> List[Dict[str, Any]]:
    if not user or not app_password:
        print(f"{provider} env vars missing. Skipping {provider} job alerts.")
        return []

    jobs: List[Dict[str, Any]] = []
    lookback_days = int(config.get("filters", {}).get("gmail_lookback_days", 7))
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")

    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, app_password)

        status, _ = mail.select(f'"{mailbox}"')
        if status != "OK":
            print(f"{provider} mailbox '{mailbox}' not found. Falling back to INBOX.")
            mail.select("INBOX")

        status, data = mail.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            print(f"{provider} search returned no usable result.")
            mail.logout()
            return []

        msg_ids = data[0].split()[-80:]
        for msg_id in msg_ids:
            status, fetched = mail.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue

            msg = email_lib.message_from_bytes(fetched[0][1])
            subject = decode_mime_header(msg.get("Subject", ""))
            sender = decode_mime_header(msg.get("From", ""))
            subject_blob = normalize_text(f"{subject} {sender}")
            if any(bad in subject_blob for bad in EMAIL_NEGATIVE_KEYWORDS):
                continue
            if not any(signal in subject_blob for signal in EMAIL_JOB_SIGNAL_KEYWORDS):
                # Avoid treating generic LinkedIn/security/newsletter emails as job alerts.
                continue
            plain_body, html_body = get_message_body(msg)
            body_text = clean_html(plain_body or html_body_to_text(html_body))

            source_guess = detect_gmail_source(sender, subject, "", config)
            links = extract_job_links(plain_body, html_body, config)

            if not links:
                # Keep one digest record only if it contains relevant keywords.
                digest_blob = f"{subject} {sender} {body_text}"
                if not contains_any(digest_blob, config.get("filters", {}).get("include_keywords", [])):
                    continue
                jobs.append({
                    "source": f"{provider} Alert - {source_guess}",
                    "title": make_title_from_email(subject, "", source_guess),
                    "company": source_guess,
                    "location": "",
                    "salary": "",
                    "url": "",
                    "description": clean_html(f"Email from: {sender}\nSubject: {subject}\n\n{body_text}")[:5000],
                    "remote_type": "Unknown",
                    "posted_at": "",
                })
                continue

            for href, anchor_text in links:
                source = detect_gmail_source(sender, subject, href, config)
                title = make_title_from_email(subject, anchor_text, source)
                jobs.append({
                    "source": f"{provider} Alert - {source}",
                    "title": title,
                    "company": source,
                    "location": "",
                    "salary": "",
                    "url": href,
                    "description": clean_html(f"Email from: {sender}\nSubject: {subject}\nLink text: {anchor_text}\n\n{body_text}")[:5000],
                    "remote_type": "Unknown",
                    "posted_at": "",
                })

        mail.close()
        mail.logout()
    except Exception as e:
        print(f"{provider} alerts error: {e}")

    return jobs[: config.get("filters", {}).get("max_jobs_per_source", 80)]


def fetch_gmail_alerts(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config.get("sources", {}).get("gmail_alerts"):
        return []
    return fetch_imap_alerts(
        config, "Gmail", "imap.gmail.com", GMAIL_USER, GMAIL_APP_PASSWORD, GMAIL_LABEL
    )


def fetch_icloud_alerts(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config.get("sources", {}).get("icloud_alerts"):
        return []
    return fetch_imap_alerts(
        config, "iCloud", "imap.mail.me.com", ICLOUD_USER, ICLOUD_APP_PASSWORD, ICLOUD_MAILBOX
    )


def filter_relevant(jobs: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    include = config["filters"].get("include_keywords", [])
    exclude = config["filters"].get("exclude_keywords", [])
    filtered = []
    seen = set()
    for job in jobs:
        blob = f"{job.get('title','')} {job.get('description','')} {job.get('company','')} {job.get('location','')}"
        if exclude and contains_any(blob, exclude):
            continue
        if include and not contains_any(blob, include):
            continue
        h = job_hash(job)
        if h in seen:
            continue
        job["hash"] = h
        seen.add(h)
        filtered.append(job)
    return filtered


def notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def notion_get_schema() -> Dict[str, Any]:
    """Return Notion database properties. This makes the script tolerant to databases
    where the title property is named Name, Vacante, Puesto, etc. instead of Title.
    """
    global NOTION_SCHEMA_CACHE
    if NOTION_SCHEMA_CACHE is not None:
        return NOTION_SCHEMA_CACHE
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        NOTION_SCHEMA_CACHE = {}
        return NOTION_SCHEMA_CACHE

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}"
    try:
        r = requests.get(url, headers=notion_headers(), timeout=25)
        if r.status_code >= 400:
            print("Notion schema error:", r.status_code, r.text[:800])
        r.raise_for_status()
        NOTION_SCHEMA_CACHE = r.json().get("properties", {})
        title_prop = notion_title_property(NOTION_SCHEMA_CACHE)
        print(f"Notion title property detected: {title_prop or 'MISSING'}")
        return NOTION_SCHEMA_CACHE
    except Exception as e:
        print(f"Notion schema error: {e}")
        NOTION_SCHEMA_CACHE = {}
        return NOTION_SCHEMA_CACHE


def notion_title_property(schema: Dict[str, Any]) -> Optional[str]:
    for prop_name, meta in schema.items():
        if meta.get("type") == "title":
            return prop_name
    return None


def notion_prop_exists(schema: Dict[str, Any], prop_name: str, expected_type: Optional[str] = None) -> bool:
    if prop_name not in schema:
        return False
    if expected_type is None:
        return True
    return schema[prop_name].get("type") == expected_type


def notion_find_by_hash(h: str) -> Optional[str]:
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        return None
    schema = notion_get_schema()
    if not notion_prop_exists(schema, "Job Hash", "rich_text"):
        print("Notion duplicate check skipped: 'Job Hash' rich_text property not found.")
        return None
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"filter": {"property": "Job Hash", "rich_text": {"equals": h}}}
    try:
        r = requests.post(url, headers=notion_headers(), json=payload, timeout=25)
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            return results[0].get("id")
    except Exception as e:
        print(f"Notion query error: {e}")
    return None


def notion_create_job(job: Dict[str, Any], analysis: Dict[str, Any]) -> Optional[str]:
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Notion env vars missing. Skipping Notion write.")
        return None

    url = "https://api.notion.com/v1/pages"
    now_date = datetime.now(timezone.utc).date().isoformat()
    top_skills = [{"name": s[:100]} for s in analysis.get("top_matching_skills", [])[:10]]
    missing_skills = [{"name": s[:100]} for s in analysis.get("missing_skills", [])[:8]]

    title = job.get("title", "Untitled Job")[:180]
    schema = notion_get_schema()
    title_prop = notion_title_property(schema)
    if not title_prop:
        print("Notion create skipped: no title property found in database.")
        return None

    desired_properties = {
        title_prop: ("title", {"title": [{"text": {"content": title}}]}),
        "Company": ("rich_text", {"rich_text": [{"text": {"content": str(job.get("company", ""))[:180]}}]}),
        "Status": ("select", {"select": {"name": "Nueva"}}),
        "Match %": ("number", {"number": analysis.get("overall_match", 0)}),
        "Technical Match %": ("number", {"number": analysis.get("technical_match", 0)}),
        "ATS Match %": ("number", {"number": analysis.get("ats_match", 0)}),
        "Priority": ("select", {"select": {"name": analysis.get("priority", "Review")[:100]}}),
        "Source": ("select", {"select": {"name": str(job.get("source", "Unknown"))[:100]}}),
        "Location": ("rich_text", {"rich_text": [{"text": {"content": str(job.get("location", ""))[:180]}}]}),
        "Remote Type": ("select", {"select": {"name": str(job.get("remote_type", "Unknown"))[:100]}}),
        "Salary": ("rich_text", {"rich_text": [{"text": {"content": str(job.get("salary", ""))[:180]}}]}),
        "URL": ("url", {"url": job.get("url") or None}),
        "Date Found": ("date", {"date": {"start": now_date}}),
        "Job Hash": ("rich_text", {"rich_text": [{"text": {"content": job.get("hash", "")}}]}),
        "Top Skills": ("multi_select", {"multi_select": top_skills}),
        "Missing Skills": ("multi_select", {"multi_select": missing_skills}),
        "Recommendation": ("rich_text", {"rich_text": [{"text": {"content": analysis.get("recommendation", "")[:1900]}}]}),
        "Recruiter Message": ("rich_text", {"rich_text": [{"text": {"content": analysis.get("recruiter_message", "")[:1900]}}]}),
    }

    properties = {}
    skipped_props = []
    for prop_name, (expected_type, value) in desired_properties.items():
        if notion_prop_exists(schema, prop_name, expected_type):
            properties[prop_name] = value
        else:
            skipped_props.append(prop_name)
    if skipped_props:
        print("Notion properties skipped because they are missing or have a different type:", ", ".join(skipped_props))
    children = [
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "AI Analysis"}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": analysis.get("recommendation", "")[:1900]}}]}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Job Description"}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": (job.get("description", "") or "")[:1900]}}]}},
    ]
    payload = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties, "children": children}
    try:
        r = requests.post(url, headers=notion_headers(), json=payload, timeout=25)
        if r.status_code >= 400:
            print("Notion create error:", r.status_code, r.text[:800])
        r.raise_for_status()
        return r.json().get("url")
    except Exception as e:
        print(f"Notion create error: {e}")
        return None


def send_telegram(job: Dict[str, Any], analysis: Dict[str, Any], notion_url: Optional[str] = None) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env vars missing. Skipping notification.")
        return
    text = (
        "🚨 NUEVA VACANTE COMPATIBLE\n\n"
        f"Empresa: {job.get('company','')}\n"
        f"Puesto: {job.get('title','')}\n"
        f"Ubicación: {job.get('location','')}\n"
        f"Modalidad: {job.get('remote_type','Unknown')}\n"
        f"Fuente: {job.get('source','')}\n\n"
        f"Match general: {analysis.get('overall_match')}%\n"
        f"Match técnico: {analysis.get('technical_match')}%\n"
        f"ATS Match: {analysis.get('ats_match')}%\n"
        f"Prioridad: {analysis.get('priority')}\n\n"
        f"Skills fuertes: {', '.join(analysis.get('top_matching_skills', [])[:8])}\n"
        f"Gaps: {', '.join(analysis.get('missing_skills', [])) or 'No críticos detectados'}\n\n"
        f"Link: {job.get('url','')}\n"
        f"Notion: {notion_url or 'Guardado sin URL'}"
    )
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(api_url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text[:3900]}, timeout=20)
        if r.status_code >= 400:
            print("Telegram error:", r.status_code, r.text[:500])
        r.raise_for_status()
    except Exception as e:
        print(f"Telegram error: {e}")


def main() -> None:
    config = load_config()

    print("Environment check:")
    print(f"- NOTION_TOKEN: {'OK' if NOTION_TOKEN else 'MISSING'}")
    print(f"- NOTION_DATABASE_ID: {'OK' if NOTION_DATABASE_ID else 'MISSING'}")
    print(f"- TELEGRAM_BOT_TOKEN: {'OK' if TELEGRAM_BOT_TOKEN else 'MISSING'}")
    print(f"- TELEGRAM_CHAT_ID: {'OK' if TELEGRAM_CHAT_ID else 'MISSING'}")
    print(f"- GMAIL_USER: {'OK' if GMAIL_USER else 'MISSING'}")
    print(f"- GMAIL_APP_PASSWORD: {'OK' if GMAIL_APP_PASSWORD else 'MISSING'}")
    print(f"- GMAIL_LABEL: {GMAIL_LABEL or 'MISSING'}")
    print(f"- ICLOUD_USER: {'OK' if ICLOUD_USER else 'MISSING'}")
    print(f"- ICLOUD_APP_PASSWORD: {'OK' if ICLOUD_APP_PASSWORD else 'MISSING'}")
    print(f"- ICLOUD_MAILBOX: {ICLOUD_MAILBOX or 'MISSING'}")

    remoteok_jobs = fetch_remoteok(config)
    arbeitnow_jobs = fetch_arbeitnow(config)
    lever_jobs = fetch_lever(config)
    greenhouse_jobs = fetch_greenhouse(config)
    gmail_jobs = fetch_gmail_alerts(config)
    icloud_jobs = fetch_icloud_alerts(config)

    print("Source counts:")
    print(f"- RemoteOK: {len(remoteok_jobs)}")
    print(f"- Arbeitnow: {len(arbeitnow_jobs)}")
    print(f"- Lever: {len(lever_jobs)}")
    print(f"- Greenhouse: {len(greenhouse_jobs)}")
    print(f"- Gmail alerts: {len(gmail_jobs)}")
    print(f"- iCloud alerts: {len(icloud_jobs)}")

    all_jobs = []
    all_jobs.extend(remoteok_jobs)
    all_jobs.extend(arbeitnow_jobs)
    all_jobs.extend(lever_jobs)
    all_jobs.extend(greenhouse_jobs)
    all_jobs.extend(gmail_jobs)
    all_jobs.extend(icloud_jobs)

    jobs = filter_relevant(all_jobs, config)
    print(f"Fetched: {len(all_jobs)} | Relevant after filters: {len(jobs)}")

    notify_min = int(config["filters"].get("notify_match_min", 80))
    store_min = int(config["filters"].get("store_match_min", 55))

    scored_jobs = []
    for job in jobs:
        analysis = score_job(job, config)
        scored_jobs.append((analysis["overall_match"], job, analysis))
    scored_jobs.sort(key=lambda x: x[0], reverse=True)

    print("Top scored jobs:")
    for score, job, analysis in scored_jobs[:10]:
        print(f"- {score}% | {job.get('source','')} | {job.get('company','')} | {job.get('title','')[:120]} | {job.get('url','')[:120]}")

    created = 0
    notified = 0
    duplicates = 0
    below_store = 0
    notion_failures = 0

    for score, job, analysis in scored_jobs:
        h = job.get("hash") or job_hash(job)
        job["hash"] = h
        if notion_find_by_hash(h):
            duplicates += 1
            continue

        if analysis["overall_match"] < store_min:
            below_store += 1
            continue

        notion_url = notion_create_job(job, analysis)
        if notion_url:
            created += 1
        else:
            notion_failures += 1

        if analysis["overall_match"] >= notify_min:
            send_telegram(job, analysis, notion_url)
            notified += 1

    print(f"Below store threshold: {below_store} | Duplicates: {duplicates} | Notion write failures: {notion_failures}")
    print(f"Created in Notion: {created} | Telegram notifications: {notified}")


if __name__ == "__main__":
    main()
