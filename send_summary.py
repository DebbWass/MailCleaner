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


def _config():
    try:
        return yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _data_dirs():
    """
    כל תיקיות הנתונים שמהן יש לאסוף — תיקייה לכל חשבון (logs/<כתובת>/)
    וגם logs/ עצמה לתאימות לאחור.
    הנתונים נכתבים per-account, ולכן קריאה מ-logs/ בלבד הייתה מפספסת ריצות.
    """
    dirs = []
    try:
        sys.path.insert(0, str(BASE))
        from account_config import load_accounts
        for acc in load_accounts(_config()):
            d = LOGS / acc["address"]
            if d.exists():
                dirs.append(d)
    except Exception:
        pass
    if (LOGS / "run_history.jsonl").exists() and LOGS not in dirs:
        dirs.append(LOGS)   # נתוני שורש ישנים
    return dirs or [LOGS]


def load_runs():
    """ריצות מהשבוע האחרון מכל החשבונות (run_history.jsonl per-account)"""
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    runs = []
    for d in _data_dirs():
        for line in _read(d / "run_history.jsonl").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if datetime.fromisoformat(r["timestamp"]) >= cutoff:
                    runs.append(r)
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    runs.sort(key=lambda r: r.get("timestamp", ""))
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
    """כמה מועמדים למחיקה ממתינים (סכום כל החשבונות), ומתי נבדק לאחרונה"""
    total = 0
    latest_ts = ""
    for d in _data_dirs():
        try:
            snap = json.loads(_read(d / "candidates_snapshot.json") or "{}")
        except json.JSONDecodeError:
            continue
        total += snap.get("count", 0)
        ts = snap.get("timestamp", "")
        if ts > latest_ts:
            latest_ts = ts
    when = latest_ts[:16].replace("T", " ") if latest_ts else "לא ידוע"
    return total, when


def deletions_this_week():
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    n = 0
    for d in _data_dirs():
        for line in _read(d / "deletions.jsonl").splitlines():
            try:
                rec = json.loads(line)
                if datetime.fromisoformat(rec["deleted_at"]) >= cutoff:
                    n += 1
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return n


def connection_warnings():
    """
    בודק את מצב החיבור ל-Gmail לכל חשבון (ללא פתיחת דפדפן).
    מחזיר רשימת אזהרות: חשבונות שצריך לחדש להם חיבור או שמתקרבים לפקיעה.
    """
    warnings = []
    try:
        sys.path.insert(0, str(BASE))
        from account_config import load_accounts
        from gmail_api import GmailAPIClient
    except Exception:
        return warnings

    for acc in load_accounts(_config()):
        try:
            st = GmailAPIClient(token_file=acc.get("token_file")).get_connection_status()
        except Exception:
            continue
        addr = acc.get("address", "")
        if st.get("needs_reauth") or not st.get("connected"):
            warnings.append((addr, "need", st.get("message", "נדרש חיבור מחדש")))
        else:
            dsa = st.get("days_since_authorized")
            if isinstance(dsa, int) and dsa >= 6:
                warnings.append((addr, "soon", f"החיבור עלול לפוג בקרוב (חובר לפני {dsa} ימים)"))
    return warnings


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_report():
    runs = load_runs()
    status = current_run_status()
    errors, warnings = week_errors()
    cand_count, cand_when = pending_candidates()
    deletions = deletions_this_week()
    conn_warn = connection_warnings()
    today = datetime.now().strftime("%d/%m/%Y")

    # --- אזהרת חיבור ל-Gmail ---
    if conn_warn:
        items = ""
        for addr, kind, msg in conn_warn:
            icon = "🔴" if kind == "need" else "🟠"
            items += f"<li>{icon} <b>{esc(addr)}</b> — {esc(msg)}</li>"
        conn_html = f"""<div style="border:2px solid #e67e22;background:#fff6ec;border-radius:8px;
padding:10px 14px;margin:12px 0">
<h3 style="margin:0 0 6px;color:#c0620a">🔗 תשומת לב — חיבור ל-Gmail</h3>
<ul style="margin:4px 0">{items}</ul>
<p style="font-size:13px;color:#666;margin:4px 0 0">
פתחי את הדשבורד ולחצי <b>"התחבר מחדש"</b> — אין צורך למחוק קבצים.</p>
</div>"""
    else:
        conn_html = ""

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
{conn_html}
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
