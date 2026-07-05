# -*- coding: utf-8 -*-
"""
send_summary.py — שולח דוח ניטור שבועי של MailCleaner למייל.
אוסף מידע מ: run_history.jsonl, weekly_run.log, cleaner.log,
candidates_snapshot.json, deletions.jsonl
שימוש:   python send_summary.py          ← שולח מייל
        python send_summary.py --test   ← רק מדפיס, בלי לשלוח
"""
import json
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import yaml

BASE = Path(__file__).parent
LOGS = BASE / "logs"
DAYS_BACK = 8


def _read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def load_runs():
    """ריצות מהשבוע האחרון מתוך run_history.jsonl"""
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    runs = []
    for line in _read(LOGS / "run_history.jsonl").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if datetime.fromisoformat(r["timestamp"]) >= cutoff:
                runs.append(r)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return runs


def current_run_status():
    """סטטוס הריצה הנוכחית מתוך הסימונים ב-weekly_run.log"""
    text = _read(LOGS / "weekly_run.log")
    if "==== Run started" not in text:
        return None
    block = text.rsplit("==== Run started", 1)[1]
    if "MailCleaner FAILED" in block:
        return "failed"
    if "MailCleaner OK" in block:
        return "ok"
    return "unknown"


def week_errors():
    """שורות ERROR/WARNING מהשבוע האחרון מתוך cleaner.log"""
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    errors, warnings = [], []
    for line in _read(LOGS / "cleaner.log").splitlines():
        try:
            ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if ts < cutoff:
            continue
        if "| ERROR |" in line:
            errors.append(line)
        elif "| WARNING |" in line:
            warnings.append(line)
    return errors, warnings


def pending_candidates():
    """כמה מועמדים למחיקה ממתינים, ומתי נבדק לאחרונה"""
    try:
        snap = json.loads(_read(LOGS / "candidates_snapshot.json") or "{}")
        ts = snap.get("timestamp", "")
        when = ts[:16].replace("T", " ") if ts else "לא ידוע"
        return snap.get("count", 0), when
    except json.JSONDecodeError:
        return 0, "לא ידוע"


def deletions_this_week():
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    n = 0
    for line in _read(LOGS / "deletions.jsonl").splitlines():
        try:
            d = json.loads(line)
            if datetime.fromisoformat(d["deleted_at"]) >= cutoff:
                n += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return n


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_report():
    runs = load_runs()
    status = current_run_status()
    errors, warnings = week_errors()
    cand_count, cand_when = pending_candidates()
    deletions = deletions_this_week()
    today = datetime.now().strftime("%d/%m/%Y")

    # --- סטטוס כללי ---
    if status == "failed":
        emoji, headline = "❌", "הריצה נכשלה — ראי פירוט שגיאות למטה"
    elif errors:
        emoji, headline = "⚠️", "הריצה הסתיימה, אבל נרשמו שגיאות השבוע"
    elif status == "ok" or runs:
        emoji, headline = "✅", "הכל תקין"
    else:
        emoji, headline = "⚠️", "לא זוהתה ריצה השבוע — ייתכן שהמשימה המתוזמנת לא פעלה"

    # --- טבלת ריצות ---
    if runs:
        rows = ""
        for r in runs:
            ok = "✅" if r.get("completed") else "❌ לא הושלמה"
            rows += (f"<tr><td>{esc(r.get('date',''))} {esc(r.get('time',''))}</td>"
                     f"<td>{esc(r.get('account', 'כ