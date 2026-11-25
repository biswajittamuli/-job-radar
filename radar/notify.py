"""Alerts. Every channel is optional and switched on by environment variables:

  Telegram : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  Email    : SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, EMAIL_TO
  GitHub   : GITHUB_STEP_SUMMARY (set automatically inside Actions)
"""
from __future__ import annotations

import html
import os
import smtplib
from email.mime.text import MIMEText

import requests

LEVEL_ICON = {"entry": "🟢", "open": "🔵", "intern": "🟣"}


def _lines(jobs, max_items):
    out = []
    for j in jobs[:max_items]:
        tags = ", ".join(j.skills)
        out.append((j, f"{LEVEL_ICON.get(j.level, '•')} {j.company} — {j.title}", f"{j.location} · {tags}"))
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


def build_html(new_jobs, broken, dashboard_url, max_items):
    e = html.escape
    parts = [f"<b>🛰 Job Radar — {len(new_jobs)} new</b>"]
    for j, head, sub in _lines(new_jobs, max_items):
        parts.append(f'{LEVEL_ICON.get(j.level, "•")} <b>{e(j.company)}</b> — '
                     f'<a href="{e(j.url)}">{e(j.title)}</a>\n<i>{e(sub)}</i>')
    if len(new_jobs) > max_items:
        parts.append(f"…and {len(new_jobs) - max_items} more on the dashboard")
    if broken:
        parts.append(f"⚠ Failing boards: {e(', '.join(broken))}")
    if dashboard_url:
        parts.append(f'<a href="{e(dashboard_url)}">Open dashboard</a>')
    return "\n\n".join(parts)


def telegram(new_jobs, broken, dashboard_url, max_items) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    body = build_html(new_jobs, broken, dashboard_url, max_items)
    # Telegram caps messages at 4096 chars: split on item boundaries
    chunks, cur = [], ""
    for block in body.split("\n\n"):
        if len(cur) + len(block) + 2 > 3900:
            chunks.append(cur)
            cur = ""
        cur += block + "\n\n"
    chunks.append(cur)
    for c in chunks:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20, json={
            "chat_id": chat, "text": c, "parse_mode": "HTML", "disable_web_page_preview": True})
        r.raise_for_status()
    return True


def email(new_jobs, broken, dashboard_url, max_items) -> bool:
    host, to = os.getenv("SMTP_HOST"), os.getenv("EMAIL_TO")
    if not (host and to):
        return False
    body = build_html(new_jobs, broken, dashboard_url, max_items).replace("\n", "<br>")
    msg = MIMEText(body, "html")
    msg["Subject"] = f"Job Radar: {len(new_jobs)} new role(s)"
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
    if not new_jobs and not ncfg.get("send_when_empty") and not broken:
        return []
    sent = []
    for name, fn in (("telegram", telegram), ("email", email)):
        try:
            if fn(new_jobs, broken, dashboard_url, ncfg.get("max_items", 40)):
                sent.append(name)
        except Exception as ex:  # an alert failing must never kill the run
            print(f"[notify] {name} failed: {ex}")
    return sent
