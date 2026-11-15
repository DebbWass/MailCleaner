# mail_cleaner.py — לוגיקה ראשית של MailCleaner
# MailCleaner Project | D:\AI_Agents\MailCleaner

import argparse
from datetime import datetime
import json
import logging
import sys
import io
import time
from pathlib import Path

# תיקון קידוד Unicode עבור Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import yaml
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from gmail_api import GmailAPIClient
from imap_client import IMAPClient
from learning_engine import LearningEngine
from spam_reviewer import SpamReviewer
from receipt_organizer import ReceiptOrganizer
from deletion_tracker import DeletionTracker
from account_config import load_accounts, resolve_accounts, data_dir_for

# --- הגדרת לוג ---
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/cleaner.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
console = Console()

DELETION_CANDIDATES_FOLDER = "מועמדים למחיקה"
CONFIG_FILE = Path("config.yaml")
BATCH_SIZE  = 50


# ------------------------------------------------------------------ #
#  טעינת הגדרות                                                        #
# ------------------------------------------------------------------ #

def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------ #
#  התחברות per-account                                                 #
# ------------------------------------------------------------------ #

def connect_account(account_cfg: dict, interactive: bool = True):
    """
    מתחבר לחשבון Gmail ספציפי לפי הגדרות account_cfg.
    interactive=False (ריצה אוטומטית) → לא ייפתח דפדפן אם הטוקן פג.
    """
    primary = account_cfg.get("connection", {}).get("primary", "gmail_api")

    if primary == "gmail_api":
        client = GmailAPIClient(token_file=account_cfg.get("token_file"))
        if client.connect(interactive=interactive):
            return client, "gmail_api"
        else:
            console.print("[yellow]⚠️ Gmail API נכשל — עובר ל-IMAP...[/yellow]")

    imap_cfg = account_cfg.get("imap", {})
    client = IMAPClient(
        address=account_cfg["address"],
        app_password=imap_cfg.get("app_password", "")
    )
    if client.connect():
        return client, "imap"

    raise ConnectionError(f"❌ לא הצלחתי להתחבר לחשבון {account_cfg['address']}")


# ------------------------------------------------------------------ #
#  סיווג מיילים                                                        #
# ------------------------------------------------------------------ #

def classify_emails(emails: list[dict], config: dict, learner,
                    receipt_org=None, client=None,
                    protected_ids: set = None) -> dict:
    """
    מסווג מיילים בשני שלבים.
    protected_ids: מיילים שהמשתמש הוציא ידנית מהתיקייה — לא יסווגו כמועמדים.
    """
    from classifier import classify_email
    _protected = protected_ids or set()

    classified = {
        "important": [], "danger": [], "warning": [],
        "newsletters": [], "receipts": [], "old_emails": [],
        "deletion_candidates": [], "other": [],
    }

    need_body = []

    # שלב א: metadata
    for email in emails:
        if email.get("id") in _protected:
            classified["other"].append(email)
            continue
        cat, reason = classify_email(email, config, learner, receipt_org)
        if cat in ("danger", "warning", "important", "receipt", "old_email"):
            email["_reason"] = reason
            key = {"danger": "danger", "warning": "warning", "important": "important",
                   "receipt": "receipts", "old_email": "old_emails"}[cat]
            classified[key].append(email)
        elif cat == "deletion_candidate":
            email["_delete_reason"] = reason
            classified["deletion_candidates"].append(email)
        elif cat == "newsletter":
            classified["newsletters"].append(email)
        else:
            need_body.append(email)

    # שלב ב: גוף למיילים שנשארו
    if need_body and client and hasattr(client, "get_body"):
        console.print(f"[dim]טוען גוף ל-{len(need_body)} מיילים...[/dim]")
        for email in need_body:
            client.get_body(email)
        for email in need_body:
            if email.get("id") in _protected:
                classified["other"].append(email)
                continue
            cat, reason = classify_email(email, config, learner, receipt_org)
            if cat in ("danger", "warning"):
                email["_reason"] = reason
                classified[cat].append(email)
            elif cat == "deletion_candidate":
                email["_delete_reason"] = reason
                classified["deletion_candidates"].append(email)
            elif cat == "newsletter":
                classified["newsletters"].append(email)
            else:
                classified["other"].append(email)
    else:
        classified["other"].extend(need_body)

    return classified


# ------------------------------------------------------------------ #
#  הצגת סיכום                                                          #
# ------------------------------------------------------------------ #

def show_summary(classified: dict, dry_run: bool = False):
    console.print("\n")
    console.rule("[bold blue]MailCleaner — סיכום ריצה[/bold blue]")
    if dry_run:
        console.print("[yellow]מצב סימולציה — לא מבוצעות פעולות[/yellow]\n")

    cats = [
        ("danger",             "סכנה/פישינג",       "bold red"),
        ("warning",            "חשוד",               "red"),
        ("important",          "חשובים",             "green"),
        ("receipts",           "קבלות",              "yellow"),
        ("newsletters",        "ניוזלטרים",          "dim"),
        ("old_emails",         "מיילים ישנים (2+ שנים)", "dim"),
        ("deletion_candidates","מועמדים למחיקה",     "red"),
        ("other",              "אחר",                "dim"),
    ]
    for key, label, color in cats:
        count = len(classified.get(key, []))
        if count > 0:
            console.print(f"  [{color}]{label}:[/{color}] {count}")

    dangers = classified.get("danger", []) + classified.get("warning", [])
    if dangers:
        console.print("\n[bold red]⚠ מיילים מסוכנים/חשודים:[/bold red]")
        for e in dangers[:10]:
            console.print(f"  • {e.get('from','')[:40]} | {e.get('subject','')[:40]}")
            console.print(f"    [red]{e.get('_reason','')}[/red]")
    console.print()


# ------------------------------------------------------------------ #
#  ביצוע פעולות                                                        #
# ------------------------------------------------------------------ #

def execute_actions(client, classified: dict, dry_run: bool = False,
                    source_folders: list[str] = None):
    actions = {
        "newsletters":         "ניוזלטרים",
        "deletion_candidates": DELETION_CANDIDATES_FOLDER,
        "old_emails":          "מיילים ישנים",
        "danger":              "מסוכנים/פישינג",
        "warning":             "חשודים",
    }
    for category, folder_name in actions.items():
        emails = classified.get(category, [])
        if not emails:
            continue
        msg_ids = [e["id"] for e in emails]
        if dry_run:
            logger.info(f"[SIM] {len(msg_ids)} → '{folder_name}'")
        else:
            if hasattr(client, "batch_move_to_label_from"):
                client.batch_move_to_label_from(msg_ids, folder_name, source_folders or [])
            elif hasattr(client, "batch_move_to_label"):
                client.batch_move_to_label(msg_ids, folder_name)
            else:
                for e in emails:
                    client.move_to_folder(e["id"], folder_name)

    if not dry_run:
        counts = {k: len(classified.get(k,[])) for k in actions}
        total = sum(counts.values())
        if total:
            console.print(f"  [green]{total} מיילים מוינו לתיקיות[/green]")
        if counts.get("danger", 0):
            console.print(f"  [bold red]{counts['danger']} מיילים מסוכנים → 'מסוכנים/פישינג'[/bold red]")


# ------------------------------------------------------------------ #
#  פעולת למידה לאחר מחיקה                                             #
# ------------------------------------------------------------------ #

def post_deletion_learn(learner: LearningEngine):
    console.print("\n[bold cyan]🧠 מנוע למידה מנתח מחיקות...[/bold cyan]")
    result = learner.analyze_and_learn()
    new_learned = result.get("new_learned", [])

    if new_learned:
        console.print("[green]✨ נלמדו דפוסים חדשים:[/green]")
        for item in new_learned:
            type_label = {"address": "כתובת", "domain": "דומיין", "keyword": "מילת מפתח"}.get(item["type"], item["type"])
            console.print(f"  • {type_label}: [yellow]{item['value']}[/yellow] (הופיע {item['count']} פעמים)")
        console.print("\n[dim]בריצות הבאות, מיילים דומים יסווגו אוטומטית כמועמדים למחיקה.[/dim]")
    else:
        console.print("[dim]לא נלמדו דפוסים חדשים הפעם.[/dim]")

    console.print(f"\n{learner.get_summary()}")


# ------------------------------------------------------------------ #
#  scanned IDs — per-account                                           #
# ------------------------------------------------------------------ #

def _load_scanned_ids(path: Path) -> set:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def _save_scanned_ids(path: Path, ids: set):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


# ------------------------------------------------------------------ #
#  עיבוד באצ'                                                          #
# ------------------------------------------------------------------ #

def process_batch(batch_num: int, emails: list[dict], config: dict,
                  client, learner, receipt_org, tracker, dry_run: bool,
                  protected_ids: set = None) -> dict:
    """מעבד באצ' אחד של מיילים ומחזיר סטטיסטיקות."""

    console.rule(f"[bold cyan]באצ' {batch_num} — {len(emails)} מיילים[/bold cyan]")

    classified = classify_emails(emails, config, learner, receipt_org, client,
                                 protected_ids=protected_ids or set())

    total_actions = sum(len(classified.get(k,[])) for k in
                        ["danger","warning","deletion_candidates","newsletters","old_emails","receipts"])
    console.print(
        f"  חשובים: [green]{len(classified.get('important',[]))}[/green]  |  "
        f"קבלות: [yellow]{len(classified.get('receipts',[]))}[/yellow]  |  "
        f"מועמדים: [red]{len(classified.get('deletion_candidates',[]))}[/red]  |  "
        f"ישנים: [dim]{len(classified.get('old_emails',[]))}[/dim]  |  "
        f"מסוכן: [bold red]{len(classified.get('danger',[]))}[/bold red]"
    )

    if classified.get("receipts"):
        receipt_summary = receipt_org.organize_receipts(
            classified["receipts"], client, dry_run=dry_run
        )
        for folder, count in receipt_summary.items():
            console.print(f"  [dim]קבלות → {folder}: {count}[/dim]")

    execute_actions(client, classified, dry_run=dry_run,
                   source_folders=getattr(process_batch, '_source_folders', None))

    return {
        "total_scanned":       len(emails),
        "important":           len(classified.get("important",           [])),
        "newsletters":         len(classified.get("newsletters",         [])),
        "receipts":            len(classified.get("receipts",            [])),
        "deletion_candidates": len(classified.get("deletion_candidates", [])),
        "old_emails":          len(classified.get("old_emails",          [])),
        "danger":              len(classified.get("danger",              [])),
        "warning":             len(classified.get("warning",             [])),
        "other":               len(classified.get("other",               [])),
    }


# ------------------------------------------------------------------ #
#  ריצה על חשבון בודד                                                  #
# ------------------------------------------------------------------ #

def run_account(account_cfg: dict, global_config: dict, args) -> dict:
    """
    מריץ את מחזור הסריקה המלא לחשבון אחד.
    מחזיר dict עם סיכום: account, totals, success.
    """
    address  = account_cfg["address"]
    data_dir = data_dir_for(account_cfg)

    console.rule(f"[bold blue]חשבון: {address}[/bold blue]")

    # instances per-account — כל נתוניהם בתיקיית data_dir
    learner     = LearningEngine(data_dir=data_dir)
    receipt_org = ReceiptOrganizer(data_dir=data_dir)
    tracker     = DeletionTracker(data_dir=data_dir)

    # config ממוזג: כללים גלובליים + נתוני חשבון
    merged_config = {**global_config, "gmail": account_cfg}

    if args.learn:
        post_deletion_learn(learner)
        return {"account": address, "action": "learn", "success": True}

    method = "unknown"
    try:
        # ריצה אוטומטית (scheduler/weekly) לא פותחת דפדפן; ריצה ידנית כן
        interactive = getattr(args, "mode", "manual") != "auto"
        client, method = connect_account(account_cfg, interactive=interactive)
        console.print(f"[green]מחובר דרך: {method}[/green]")
    except ConnectionError as e:
        console.print(f"[red]{e}[/red]")
        return {"account": address, "error": str(e), "success": False}

    # זיהוי מחיקות מריצה קודמת
    console.print("[dim]בודק מה נמחק מאז הריצה הקודמת...[/dim]")
    deleted_since_last = tracker.detect_deletions(client)
    if deleted_since_last:
        console.print(f"[green]נמצאו {len(deleted_since_last)} מחיקות — מעביר ללמידה...[/green]")
        result = learner.analyze_and_learn()
        for item in result.get("new_learned", []):
            t = {"address": "כתובת", "domain": "דומיין", "keyword": "מילת מפתח"}.get(item["type"], item["type"])
            console.print(f"  נלמד {t}: [yellow]{item['value']}[/yellow]")

    candidates_before = tracker.save_snapshot(client)

    protected_ids = tracker.get_protected_ids()
    if protected_ids:
        console.print(f"[dim]{len(protected_ids)} מיילים מוגנים — לא יסווגו שוב כמועמדים[/dim]")

    # scanned IDs — per-account
    scanned_ids_file = data_dir / "scanned_ids.json"
    if scanned_ids_file.exists() and not args.rescan:
        age_sec = time.time() - scanned_ids_file.stat().st_mtime
        if age_sec > 3600:
            scanned_ids_file.unlink()
            scanned_ids = set()
        else:
            scanned_ids = _load_scanned_ids(scanned_ids_file)
            if scanned_ids:
                console.print(f"[dim]{len(scanned_ids)} מיילים נסרקו בריצה זו — ממשיך מאיפה שנעצר[/dim]")
    else:
        scanned_ids = set()
        if scanned_ids_file.exists():
            scanned_ids_file.unlink()
        if args.rescan:
            console.print("[cyan]מצב סריקה חוזרת — כל המיילים יסווגו מחדש[/cyan]")

    # פילטר קריאה
    read_query = ""
    if args.read_filter == "read":   read_query = " is:read"
    if args.read_filter == "unread": read_query = " is:unread"
    if read_query:
        console.print(f"[dim]פילטר: {args.read_filter}[/dim]")

    folders  = [f.strip() for f in args.folders.split(",") if f.strip()]
    scan_all = args.all or args.max == -1
    console.print(f"[cyan]תיקיות: {', '.join(folders)} | {'כל המיילים' if scan_all else f'עד {args.max}'}[/cyan]")

    totals = {"total_scanned": 0, "important": 0, "newsletters": 0,
              "receipts": 0, "deletion_candidates": 0,
              "old_emails": 0, "danger": 0, "warning": 0, "other": 0}
    new_scanned   = set()
    batch_num_ctr = 0
    run_completed = False
    run_start     = datetime.now().isoformat()

    try:
        for folder in folders:
            base_q = (f"in:{folder.lower()}"
                      if folder.upper() in ("INBOX","SPAM","SENT","TRASH","STARRED")
                      else f'label:"{folder}"')
            query = base_q + read_query

            if scan_all:
                console.print(f"[dim]סורק את כל {folder} (באצ'ים של {BATCH_SIZE})...[/dim]")
                email_source = client.iter_email_batches(query=query, batch_size=BATCH_SIZE)
            else:
                per_folder = max(BATCH_SIZE, args.max // len(folders))
                console.print(f"[dim]קורא עד {per_folder} מיילים מ-{folder}...[/dim]")
                fetched = client.get_emails(max_results=per_folder, query=query)
                console.print(f"[dim]  נמצאו {len(fetched)} מיילים[/dim]")
                if scanned_ids:
                    fetched = [e for e in fetched if e["id"] not in scanned_ids]
                if args.order == "oldest":
                    fetched = list(reversed(fetched))

                def _as_batches(lst, size=BATCH_SIZE):
                    for i in range(0, len(lst), size):
                        yield lst[i:i+size]
                email_source = _as_batches(fetched)

            for batch in email_source:
                if scanned_ids:
                    batch = [e for e in batch if e["id"] not in scanned_ids]
                if not batch:
                    continue
                if scan_all and args.order == "oldest":
                    batch = list(reversed(batch))

                batch_num_ctr += 1
                process_batch._source_folders = folders
                stats = process_batch(batch_num_ctr, batch, merged_config, client, learner,
                                      receipt_org, tracker, args.dry_run,
                                      protected_ids=protected_ids)
                for k in totals:
                    totals[k] += stats.get(k, 0)
                new_scanned.update(e["id"] for e in batch)
                _save_scanned_ids(scanned_ids_file, scanned_ids | new_scanned)

        if batch_num_ctr == 0:
            console.print("[yellow]לא נמצאו מיילים חדשים לסריקה.[/yellow]")

        run_completed = True

    except KeyboardInterrupt:
        console.print("[yellow]הסריקה הופסקה על ידי המשתמש[/yellow]")
        logger.warning(f"הסריקה הופסקה ידנית — {totals['total_scanned']} מיילים, {batch_num_ctr} באצ'ים")
    except Exception as scan_err:
        console.print(f"[red]שגיאה בסריקה: {scan_err}[/red]")
        logger.error(f"שגיאה בסריקה: {scan_err}", exc_info=True)
    finally:
        # רושם כל ריצה — גם אם לא נסרקו מיילים חדשים (חשוב לניטור)
        tracker.log_run({
                **totals,
                "account":                address,
                "deleted_since_last_run": len(deleted_since_last),
                "candidates_in_folder":   candidates_before,
                "num_batches":            batch_num_ctr,
                "folders":                folders,
                "order":                  args.order,
                "dry_run":                args.dry_run,
                "connection_method":      method,
                "completed":              run_completed,
                "run_start":              run_start,
            })

    if not run_completed:
        return {"account": address, "totals": totals, "success": False}

    # סיכום חשבון
    console.rule(f"[bold blue]סיכום: {address}[/bold blue]")
    console.print(
        f"  נסרקו: [white]{totals['total_scanned']}[/white]  |  "
        f"חשובים: [green]{totals['important']}[/green]  |  "
        f"קבלות: [yellow]{totals['receipts']}[/yellow]  |  "
        f"מועמדים למחיקה: [red]{totals['deletion_candidates']}[/red]"
    )

    learner.analyze_and_learn()

    # סריקת SPAM
    if not args.skip_spam and "SPAM" not in [f.upper() for f in folders]:
        console.print("\n")
        console.rule("[bold yellow]סורק תיקיית SPAM[/bold yellow]")
        important_senders = global_config.get("rules", {}).get("important_senders", [])
        reviewer  = SpamReviewer(config=merged_config, important_senders=important_senders,
                                 data_dir=data_dir)
        spam_max  = min(args.max if not scan_all else 50, 50)
        if not args.dry_run:
            suspicious = reviewer.scan_spam_folder(client, max_results=spam_max)
            if suspicious:
                reviewer.present_for_review(suspicious, client)
            else:
                console.print("[green]לא נמצאו מיילים לגיטימיים בתיקיית SPAM.[/green]")
        else:
            console.print("[dim][SIM] סריקת SPAM דולגת במצב סימולציה[/dim]")

    return {"account": address, "totals": totals, "success": True}


# ------------------------------------------------------------------ #
#  פונקציה ראשית — dispatcher                                          #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(description="MailCleaner — ניקוי Gmail חכם")
    parser.add_argument("--dry-run",     action="store_true")
    parser.add_argument("--learn",       action="store_true")
    parser.add_argument("--rescan",      action="store_true")
    parser.add_argument("--skip-spam",   action="store_true")
    parser.add_argument("--all",         action="store_true",
                        help="סרוק את כל המיילים ללא הגבלה")
    parser.add_argument("--mode",        choices=["manual", "auto"], default="manual")
    parser.add_argument("--max",         type=int, default=50)
    parser.add_argument("--order",       choices=["newest", "oldest"], default="newest")
    parser.add_argument("--folders",     type=str, default="INBOX")
    parser.add_argument("--read-filter", choices=["all", "read", "unread"], default="all")
    parser.add_argument("--accounts",    type=str, default=None,
                        help="חשבונות להרצה: 'all' או כתובות מייל מופרדות בפסיק. ברירת מחדל: כל החשבונות")
    args = parser.parse_args()

    console.rule("[bold blue]MailCleaner מתחיל[/bold blue]")

    config = load_config()

    # נרמול חשבונות + בחירה לפי --accounts
    all_accounts = load_accounts(config)
    try:
        selected = resolve_accounts(all_accounts, args.accounts)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if len(selected) > 1:
        console.print(f"[cyan]מריץ על {len(selected)} חשבונות: {[a['address'] for a in selected]}[/cyan]")
    else:
        console.print(f"[cyan]חשבון: {selected[0]['address']}[/cyan]")

    # config גלובלי — rules, safety וכו' (ללא gmail ספציפי לחשבון)
    global_config = {k: v for k, v in config.items() if k not in ("accounts", "gmail")}

    results = []
    for account_cfg in selected:
        result = run_account(account_cfg, global_config, args)
        results.append(result)

    # סיכום משולב (רק אם יותר מחשבון אחד)
    if len(selected) > 1:
        console.rule("[bold blue]סיכום כל החשבונות[/bold blue]")
        for r in results:
            if r.get("error"):
                console.print(f"  [red]{r['account']}: נכשל — {r['error']}[/red]")
            else:
                scanned = r.get("totals", {}).get("total_scanned", 0)
                cands   = r.get("totals", {}).get("deletion_candidates", 0)
                status  = "[green]הצליח[/green]" if r.get("success") else "[red]לא הושלם[/red]"
                console.print(f"  {r['account']}: {status} — {scanned} נסרקו, {cands} מועמדים למחיקה")

    console.rule("[bold blue]MailCleaner סיים[/bold blue]")


if __name__ == "__main__":
    main()
