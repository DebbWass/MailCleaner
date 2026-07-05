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
                     f"<td>{esc(r.get('account', 'כל החשבונות'))}</td>"
                     f"<td>{r.get('total_scanned',0)}</td>"
                     f"<td>{r.get('receipts',0)}</td>"
                     f"<td>{r.get('newsletters',0)}</td>"
                     f"<td>{r.get('deletion_candidates',0)}</td>"
                     f"<td>{ok}</td></tr>")
        runs_html = f"""<h3>🏃 ריצות השבוע ({len(runs)})</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse;font-size:14px">
<tr style="background:#f0f0f0"><th>מתי</th><th>חשבון</th><th>נסרקו</th><th>קבלות</th>
<th>ניוזלטרים</th><th>מועמדים חדשים</th><th>סטטוס</th></tr>
{rows}</table>"""
        scanned = sum(r.get("total_scanned", 0) for r in runs)
        new_cand = sum(r.get("deletion_candidates", 0) for r in runs)
        totals_html = (f"<p>סה\"כ השבוע: נסרקו <b>{scanned}</b> מיילים, "
                       f"<b>{new_cand}</b> מועמדים חדשים למחיקה, "
                       f"<b>{deletions}</b> מחיקות שביצעת נקלטו ללמידה.</p>")
    else:
        runs_html = ("<h3>🏃 ריצות השבוע</h3>"
                     "<p>לא נרשמו ריצות ב-run_history השבוע. אם הסטטוס למעלה ✅ — "
                     "הריצה עבדה אבל כל המיילים כבר נסרקו בעבר (תקין). "
                     "אחרת — כדאי לבדוק את logs\\weekly_run.log.</p>")
        totals_html = ""

    # --- שגיאות ---
    if errors or warnings:
        samples = "".join(f"<li style='font-family:monospace;font-size:12px'>{esc(e[:160])}</li>"
                          for e in errors[-5:])
        err_html = f"""<h3 style="color:#c00">🚨 שגיאות ואזהרות השבוע</h3>
<p>{len(errors)} שגיאות, {len(warnings)} אזהרות. אחרונות:</p>
<ul>{samples or '<li>(רק אזהרות — ללא שגיאות)</li>'}</ul>
<p style="font-size:13px;color:#666">הפירוט המלא ב-logs\\cleaner.log</p>"""
    else:
        err_html = "<h3>🚨 שגיאות</h3><p>אין! שבוע נקי לגמרי. 🎉</p>"

    html = f"""<div dir="rtl" style="font-family:Arial,sans-serif;max-width:640px">
<h2>{emoji} MailCleaner — דוח שבועי ({today})</h2>
<p style="font-size:16px"><b>{headline}</b></p>
{runs_html}
{totals_html}
<h3>🗑️ ממתין לך</h3>
<p><b>{cand_count}</b> מועמדים למחיקה ממתינים לאישורך בתיקיית המועמדים
(נכון ל-{esc(cand_when)}). המחיקה תמיד בידיים שלך — פתחי את הדשבורד לסקירה.</p>
{err_html}
<hr>
<p style="color:#666;font-size:12px">נשלח אוטומטית ע"י MailCleaner — הריצה הבאה: יום ראשון הבא.</p>
</div>"""
    subject = f"{emoji} MailCleaner — דוח שבועי {today}"
    return subject, html


def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    acc = cfg["accounts"][0]  # sendit2dorit
    address = acc["address"]
    app_password = acc["imap"]["app_password"].replace(" ", "")

    subject, html = build_report()

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = "sendit2dorit@gmail.com"

    if "--test" in sys.argv:
        print(f"[TEST] נושא: {subject}\n")
        print(html)
        return

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(address, app_password)
        smtp.send_message(msg)
    print("הדוח נשלח בהצלחה אל sendit2dorit@gmail.com")


if __name__ == "__main__":
    main()
