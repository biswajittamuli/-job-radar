"""Alerts. Every channel is optional and switched on by environment variables:

  Telegram : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Email    : SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, EMAIL_TO
  GitHub   : GITHUB_STEP_SUMMARY (set automatically inside Actions)
"""
from __future__ import annotations

import html
import os
import smtplib
from datetime import date
from email.mime.text import MIMEText

import requests

from .models import best_first

LEVEL_ICON = {"entry": "🟢", "open": "🔵", "intern": "🟣"}


def posted_label(posted_at, today=None) -> str:
    if not posted_at:
        return ""
    try:
        d = ((today or date.today()) - date.fromisoformat(posted_at[:10])).days
    except ValueError:
        return ""
    return "posted today" if d <= 0 else "posted yesterday" if d == 1 else f"posted {d} days ago"


def _lines(jobs, max_items):
    out = []
    # best fit for you first, then newest, whatever order the caller passed
    for j in sorted(jobs, key=lambda j: best_first(getattr(j, "fit", 0), j.posted_at, j.score))[:max_items]:
        why = getattr(j, "why", None) or []
        sub = " · ".join(x for x in (j.location, ", ".join(why) if why else ", ".join(j.skills),
                                     posted_label(j.posted_at)) if x)
        star = "⭐ " if getattr(j, "fit", 0) >= 70 else ""
        out.append((j, f"{star}{LEVEL_ICON.get(j.level, '•')} {j.company} — {j.title}", sub))
    return out


def build_text(new_jobs, broken, dashboard_url, max_items):
    lines = [f"Job Radar: {len(new_jobs)} new role{'s' if len(new_jobs) != 1 else ''}"]
    for j, head, sub in _lines(new_jobs, max_items):
        lines += [head, f"   {sub}", f"   {j.url}"]
    if len(new_jobs) > max_items:
        lines.append(f"…and {len(new_jobs) - max_items} more")
    if broken:
        lines.append(f"\n⚠ {len(broken)} board(s) failing: " + ", ".join(broken))
    if dashboard_url:
        lines.append(f"\nDashboard: {dashboard_url}")
    return "\n".join(lines)


def build_html(new_jobs, broken, dashboard_url, max_items, stats=""):
    e = html.escape
    if not new_jobs:
        parts = ["<b>🛰 Job Radar — no new fresher jobs this run</b>"]
        if stats:
            parts.append(f"<i>{e(stats)}</i>")
    else:
        parts = [f"<b>🛰 Job Radar — {len(new_jobs)} new</b>"]
    for j, head, sub in _lines(new_jobs, max_items):
        parts.append(f'{"⭐ " if getattr(j, "fit", 0) >= 70 else ""}{LEVEL_ICON.get(j.level, "•")} <b>{e(j.company)}</b> — '
                     f'<a href="{e(j.url)}">{e(j.title)}</a>\n<i>{e(sub)}</i>')
    if len(new_jobs) > max_items:
        parts.append(f"…and {len(new_jobs) - max_items} more on the dashboard")
    if broken:
        parts.append(f"⚠ Failing boards: {e(', '.join(broken))}")
    if dashboard_url:
        parts.append(f'<a href="{e(dashboard_url)}">Open dashboard</a>')
    return "\n\n".join(parts)


class TelegramError(RuntimeError):
    """Telegram refused a request. The message is Telegram's own error text."""


def warn(title: str, msg: str):
    """Print a GitHub Actions warning annotation (also readable in a plain terminal)."""
    esc = lambda x: str(x).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::warning title={esc(title).replace(':', '%3A').replace(',', '%2C')}::{esc(msg)}", flush=True)


def telegram_creds() -> tuple[str, str]:
    """Read and clean the secrets. Values pasted into GitHub's secret box often end in a
    newline; left in, it becomes '%0A' inside the API URL and Telegram answers 404."""
    raw_token, raw_chat = os.getenv("TELEGRAM_BOT_TOKEN") or "", os.getenv("TELEGRAM_CHAT_ID") or ""
    token, chat = raw_token.strip(), raw_chat.strip()
    for name, raw, clean in (("TELEGRAM_BOT_TOKEN", raw_token, token), ("TELEGRAM_CHAT_ID", raw_chat, chat)):
        if raw != clean:
            print(f"[notify] {name} had leading/trailing whitespace or a newline; stripped it. "
                  f"Re-save the secret without it to silence this.")
    return token, chat


def missing_telegram_secrets() -> list[str]:
    return [n for n in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not (os.getenv(n) or "").strip()]


def telegram_send(token: str, chat: str, text: str, parse_mode: str | None = "HTML"):
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        body["parse_mode"] = parse_mode
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, json=body)
    except requests.RequestException as ex:
        # never let the URL (which contains the token) leak into logs
        raise TelegramError(f"network error talking to Telegram: {type(ex).__name__}") from None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code != 200 or not data.get("ok"):
        desc = data.get("description") or r.text[:200] or r.reason
        hint = ""
        if r.status_code == 404:
            hint = " (the bot token is wrong or malformed)"
        elif r.status_code == 401:
            hint = " (the bot token was revoked or is invalid)"
        elif "chat not found" in str(desc).lower():
            hint = " (check TELEGRAM_CHAT_ID, and send the bot a message first)"
        raise TelegramError(f"Telegram API {r.status_code}: {desc}{hint}")
    return data


def _chunks(body: str, limit: int = 3900) -> list[str]:
    # Telegram caps messages at 4096 chars: split on item boundaries
    chunks, cur = [], ""
    for block in body.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            chunks.append(cur)
            cur = ""
        cur += block + "\n\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def telegram(new_jobs, broken, dashboard_url, max_items, stats="") -> bool:
    token, chat = telegram_creds()
    if not (token and chat):
        return False
    for c in _chunks(build_html(new_jobs, broken, dashboard_url, max_items, stats)):
        telegram_send(token, chat, c)
    return True


def send_test_message() -> str:
    """Send a test message. Raises TelegramError with Telegram's exact error."""
    token, chat = telegram_creds()
    missing = missing_telegram_secrets()
    if missing:
        raise TelegramError(f"secret(s) not set: {', '.join(missing)}")
    data = telegram_send(token, chat, "🛰 Job Radar test message: Telegram alerts are working.", None)
    c = (data.get("result") or {}).get("chat") or {}
    return f"sent to chat {c.get('id', chat)} ({c.get('title') or c.get('username') or c.get('first_name') or 'unknown'})"


def email(new_jobs, broken, dashboard_url, max_items, stats="") -> bool:
    host, to = (os.getenv("SMTP_HOST") or "").strip(), (os.getenv("EMAIL_TO") or "").strip()
    if not (host and to):
        return False
    body = build_html(new_jobs, broken, dashboard_url, max_items, stats).replace("\n", "<br>")
    msg = MIMEText(body, "html")
    msg["Subject"] = f"Job Radar: {len(new_jobs)} new role(s)" if new_jobs else "Job Radar: no new jobs this run"
    msg["From"] = os.getenv("SMTP_USER", to)
    msg["To"] = to
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(os.getenv("SMTP_USER", ""), os.getenv("SMTP_PASS", ""))
        s.send_message(msg)
    return True


def github_summary(new_jobs, broken, stats):
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    rows = "\n".join(f"| {j.company} | [{j.title}]({j.url}) | {j.location} | {j.level} | "
                     f"{', '.join(j.skills)} |" for j in new_jobs[:100])
    with open(path, "a") as f:
        f.write(f"## Job Radar\n\n{stats}\n\n")
        if new_jobs:
            f.write("| Company | Role | Location | Level | Skills |\n|---|---|---|---|---|\n" + rows + "\n")
        if broken:
            f.write(f"\n**Failing boards:** {', '.join(broken)}\n")


def send_all(new_jobs, broken, dashboard_url, cfg, stats):
    ncfg = cfg.get("notify", {})
    wanted = set(ncfg.get("skills") or [])
    if wanted:
        new_jobs = [j for j in new_jobs if wanted & set(j.skills)]
    github_summary(new_jobs, broken, stats)
    missing = missing_telegram_secrets()
    if missing:
        print(f"[notify] telegram disabled: secret(s) not set: {', '.join(missing)}")
        if len(missing) == 1:   # one set, one not: almost certainly a mistake
            warn("Alert failed", f"telegram: {missing[0]} is not set (the other Telegram secret is)")
    if not new_jobs and not ncfg.get("send_when_empty") and not broken:
        return []
    sent = []
    for name, fn in (("telegram", telegram), ("email", email)):
        try:
            if fn(new_jobs, broken, dashboard_url, ncfg.get("max_items", 40), stats):
                sent.append(name)
        except Exception as ex:  # an alert failing must never kill the run
            msg = str(ex) if isinstance(ex, TelegramError) else f"{type(ex).__name__}: {ex}"
            print(f"[notify] {name} failed: {msg}")
            warn("Alert failed", f"{name}: {msg}")
    return sent
