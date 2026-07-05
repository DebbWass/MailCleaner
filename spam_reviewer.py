# spam_reviewer.py — זיהוי מיילים לגיטימיים שנכנסו לספאם בטעות
# MailCleaner Project | D:\AI_Agents\MailCleaner

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

logger = logging.getLogger(__name__)
console = Console()

# Legacy constant — kept for backward compat
REVIEW_LOG = Path("logs/spam_review.jsonl")

# ------------------------------------------------------------------ #
#  סימנים שמייל כנראה לגיטימי (לא ספאם אמיתי)                         #
# ------------------------------------------------------------------ #

LEGIT_SIGNALS = {

    # כתובות שמרמזות על אדם אמיתי (לא רובוט/מערכת)
    "personal_patterns": [
        r"^[\w.+-]+@gmail\.com$",
        r"^[\w.+-]+@yahoo\.com$",
        r"^[\w.+-]+@hotmail\.com$",
        r"^[\w.+-]+@walla\.co\.il$",
        r"^[\w.+-]+@bezeqint\.net$",
    ],

    # דומיינים של חברות/ארגונים מוכרים שלא אמורים להיות ספאם
    "trusted_domains": [
        "gov.il", "ac.il", "org.il",          # ממשלה / אקדמיה / עמותות ישראל
        "google.com", "microsoft.com",          # ענקיות טכנולוגיה
        "paypal.com", "amazon.com",             # מסחר מוכר
        "bank", "leumi", "hapoalim", "discount", "mizrahi",  # בנקים ישראליים
        "maccabi", "clalit", "meuhedet",        # קופות חולים
        "kupat", "bituhleumi",                  # ביטוח לאומי
    ],

    # מילות מפתח בנושא שמרמזות על תוכן אמיתי
    "legit_subject_keywords": [
        # עברית
        "חשבונית", "קבלה", "אישור", "הזמנה", "פגישה", "תזכורת",
        "סיכום", "דוח", "בדיקה", "תוצאות", "מסמך", "חוזה",
        "תשלום", "העברה", "יתרה", "חשבון", "הצעת מחיר",
        # אנגלית
        "invoice", "receipt", "confirmation", "appointment",
        "reminder", "report", "document", "contract", "statement",
        "payment", "transfer", "balance", "quote", "meeting",
        "your order", "booking", "reservation",
    ],

    # מילות מפתח שמרמזות על תגובה לשיחה קיימת
    "reply_indicators": [
        "re:", "fwd:", "fw:", "השב:", "העבר:",
    ],
}

# ------------------------------------------------------------------ #
#  מחלקת הסורק                                                         #
# ------------------------------------------------------------------ #

class SpamReviewer:
    """
    סורק את תיקיית SPAM ב-Gmail ומזהה מיילים שעלולים להיות לגיטימיים.
    מעלה אותם להחלטת המשתמש — לא מבצע שום פעולה ללא אישור.
    """

    def __init__(self, config: dict, important_senders: list[str] = None, data_dir=None):
        self.config = config
        self.important_senders = [s.lower() for s in (important_senders or [])]
        if data_dir is None:
            data_dir = Path("logs")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._review_log = self._data_dir / "spam_review.jsonl"

    # ------------------------------------------------------------------ #
    #  סריקה וזיהוי                                                        #
    # ------------------------------------------------------------------ #

    def scan_spam_folder(self, client, max_results: int = 200) -> list[dict]:
        """
        סורק את תיקיית SPAM ומחזיר רשימת מיילים חשודים כלגיטימיים.
        """
        console.print("\n[bold cyan]🔍 סורק תיקיית SPAM לאיתור מיילים לגיטימיים...[/bold cyan]")

        # קריאת מיילים מתיקיית SPAM
        if hasattr(client, "get_emails"):
            # Gmail API — שולח query לתיקיית spam
            spam_emails = client.get_emails(max_results=max_results, query="in:spam")
        else:
            # IMAP — קורא מתיקיית Spam
            spam_emails = client.get_emails(max_results=max_results, folder="[Gmail]/Spam")

        if not spam_emails:
            console.print("[dim]תיקיית SPAM ריקה.[/dim]")
            return []

        console.print(f"[dim]נמצאו {len(spam_emails)} מיילים בתיקיית SPAM — מנתח...[/dim]")

        # סינון: רק מיילים שנראים לגיטימיים ולא ברשימה השחורה
        suspicious = []
        blacklisted_count = 0
        for email in spam_emails:
            if self.is_blacklisted(email):
                blacklisted_count += 1
                continue   # ← ברשימה שחורה — לא להעלות לסקירה
            score, reasons = self._calc_legit_score(email)
            if score > 0:
                email["_legit_score"] = score
                email["_legit_reasons"] = reasons
                suspicious.append(email)

        if blacklisted_count:
            console.print(f"[dim]{blacklisted_count} מיילים דולגו (רשימה שחורה)[/dim]")

        # מיון — הכי לגיטימי ראשון
        suspicious.sort(key=lambda e: e["_legit_score"], reverse=True)

        console.print(f"[yellow]⚠️ נמצאו {len(suspicious)} מיילים שעלולים להיות לגיטימיים[/yellow]")
        return suspicious

    def _calc_legit_score(self, email: dict) -> tuple[int, list[str]]:
        """
        מחשב ציון לגיטימיות למייל (0 = ספאם ודאי, גבוה יותר = יותר חשוד כלגיטימי).
        מחזיר (ציון, רשימת סיבות).
        """
        score = 0
        reasons = []

        from_addr = email.get("from", "").lower()
        subject = email.get("subject", "").lower()
        body = (email.get("body") or "").lower()
        domain = self._extract_domain(from_addr)

        # שולח חשוב (מרשימת המשתמש)
        if any(s in from_addr for s in self.important_senders):
            score += 10
            reasons.append("✉️ שולח מרשימת 'חשובים' שלך")

        # כתובת אישית (gmail, yahoo וכו')
        for pattern in LEGIT_SIGNALS["personal_patterns"]:
            clean_addr = re.search(r"<(.+?)>", from_addr)
            addr_to_check = clean_addr.group(1) if clean_addr else from_addr
            if re.match(pattern, addr_to_check):
                score += 4
                reasons.append("👤 נראה כתובת של אדם אמיתי")
                break

        # דומיין מוכר ומהימן
        for trusted in LEGIT_SIGNALS["trusted_domains"]:
            if trusted in domain:
                score += 5
                reasons.append(f"🏢 דומיין מהימן: {domain}")
                break

        # נושא שמרמז על תוכן אמיתי
        for kw in LEGIT_SIGNALS["legit_subject_keywords"]:
            if kw in subject:
                score += 3
                reasons.append(f"📋 נושא לגיטימי: '{kw}'")
                break

        # תגובה לשיחה קיימת
        for indicator in LEGIT_SIGNALS["reply_indicators"]:
            if subject.startswith(indicator):
                score += 6
                reasons.append("↩️ נראה כתגובה לשיחה קיימת")
                break

        # אין קישורי unsubscribe — סימן טוב
        if "unsubscribe" not in body and "הסר מרשימה" not in body:
            score += 2
            reasons.append("✅ אין קישור להסרה מרשימה")

        # אין מילות שיווק ברורות
        spam_marketing = ["click here", "buy now", "limited offer", "מבצע מיוחד", "לחץ כאן"]
        if not any(kw in body for kw in spam_marketing):
            score += 1
            reasons.append("✅ אין מילות שיווק")

        return score, reasons

    # ------------------------------------------------------------------ #
    #  הצגה ואינטראקציה עם המשתמש                                         #
    # ------------------------------------------------------------------ #

    def present_for_review(self, suspicious_emails: list[dict], client) -> dict:
        """
        מציג למשתמש את המיילים החשודים ומבקש החלטה על כל אחד.
        מחזיר סיכום פעולות שבוצעו.
        """
        if not suspicious_emails:
            console.print("[green]✅ לא נמצאו מיילים לגיטימיים בתיקיית SPAM.[/green]")
            return {"moved_to_inbox": 0, "confirmed_spam": 0}

        console.rule("[bold yellow]📬 מיילים חשודים כלגיטימיים — בקשת החלטה[/bold yellow]")
        console.print(f"[dim]נמצאו {len(suspicious_emails)} מיילים — תסקרי כל אחד ותחליטי:[/dim]\n")

        moved_to_inbox = []
        confirmed_spam = []

        for i, email in enumerate(suspicious_emails, 1):
            self._show_email_card(i, len(suspicious_emails), email)

            choice = Prompt.ask(
                "  [bold]מה לעשות?[/bold]",
                choices=["1", "2", "3"],
                default="3",
            )

            if choice == "1":
                # החזר ל-Inbox
                success = self._move_to_inbox(client, email)
                if success:
                    moved_to_inbox.append(email)
                    self._log_review(email, "moved_to_inbox")
                    console.print("  [green]✅ הועבר ל-Inbox[/green]\n")
            elif choice == "2":
                # ספאם ודאי — השאר
                confirmed_spam.append(email)
                self._log_review(email, "confirmed_spam")
                console.print("  [red]🚫 נשאר בספאם[/red]\n")
            else:
                # דלג
                console.print("  [dim]⏭️ דולג[/dim]\n")

        # סיכום
        self._show_review_summary(moved_to_inbox, confirmed_spam)
        return {
            "moved_to_inbox": len(moved_to_inbox),
            "confirmed_spam": len(confirmed_spam),
        }

    def _show_email_card(self, index: int, total: int, email: dict):
        """מציג כרטיס מידע על מייל אחד."""
        score = email.get("_legit_score", 0)
        reasons = email.get("_legit_reasons", [])

        # צבע לפי ציון
        score_color = "green" if score >= 8 else "yellow" if score >= 4 else "white"

        console.print(f"[bold]── מייל {index}/{total} ──────────────────────────────[/bold]")
        console.print(f"  📤 [cyan]מאת:[/cyan]    {email.get('from', '')}")
        console.print(f"  📌 [cyan]נושא:[/cyan]   {email.get('subject', '')}")
        console.print(f"  📅 [cyan]תאריך:[/cyan]  {email.get('date', '')}")
        console.print(f"  🔍 [cyan]תקציר:[/cyan]  {email.get('snippet', '')[:120]}...")
        console.print(f"  ⭐ [cyan]ציון לגיטימיות:[/cyan] [{score_color}]{score}[/{score_color}]")

        if reasons:
            console.print(f"  💡 [cyan]סיבות:[/cyan]")
            for r in reasons:
                console.print(f"     {r}")

        console.print()
        console.print("  [bold green]1[/bold green] = החזר ל-Inbox  |  [bold red]2[/bold red] = ספאם ודאי  |  [bold dim]3[/bold dim] = דלג")

    def _show_review_summary(self, moved: list, confirmed: list):
        """מציג סיכום סקירת הספאם."""
        console.rule("[bold blue]📊 סיכום סקירת SPAM[/bold blue]")
        console.print(f"  ✅ הוחזרו ל-Inbox:  [green]{len(moved)}[/green] מיילים")
        console.print(f"  🚫 אושרו כספאם:    [red]{len(confirmed)}[/red] מיילים")

        if moved:
            console.print("\n  [bold]הוחזרו ל-Inbox:[/bold]")
            for email in moved:
                console.print(f"    • {email.get('from', '')} | {email.get('subject', '')}")
        console.print()

    # ------------------------------------------------------------------ #
    #  פעולות                                                              #
    # ------------------------------------------------------------------ #

    def _move_to_inbox(self, client, email: dict) -> bool:
        """מחזיר מייל מספאם ל-Inbox."""
        try:
            msg_id = email["id"]
            if hasattr(client, "service"):
                # Gmail API
                client.service.users().messages().modify(
                    userId="me",
                    id=msg_id,
                    body={"removeLabelIds": ["SPAM"], "addLabelIds": ["INBOX"]}
                ).execute()
            else:
                # IMAP
                client.move_to_folder(msg_id, "INBOX")
            logger.info(f"📥 מייל '{email.get('subject', '')}' הוחזר ל-Inbox")
            return True
        except Exception as e:
            logger.error(f"❌ שגיאה בהחזרה ל-Inbox: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  לוג                                                                 #
    # ------------------------------------------------------------------ #

    def _log_review(self, email: dict, decision: str):
        """שומר החלטת סקירה לקובץ לוג."""
        entry = {
            "timestamp":    datetime.now().isoformat(),
            "from":         email.get("from", ""),
            "subject":      email.get("subject", ""),
            "legit_score":  email.get("_legit_score", 0),
            "legit_reasons":email.get("_legit_reasons", []),
            "decision":     decision,
        }
        with open(self._review_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def add_to_blacklist(self, email: dict):
        """מוסיף שולח לרשימה שחורה קבועה — לא יעלה שוב לסקירה."""
        from_addr = email.get("from", "")
        domain    = self._extract_domain(from_addr)
        bl        = self._load_blacklist()
        if from_addr and from_addr not in bl["addresses"]:
            bl["addresses"].append(from_addr)
        if domain and domain not in bl["domains"]:
            bl["domains"].append(domain)
        bl["last_updated"] = datetime.now().isoformat()
        self._save_blacklist(bl)
        logger.info(f"רשימה שחורה: {from_addr}")

    def is_blacklisted(self, email: dict) -> bool:
        """בודק אם שולח ברשימה השחורה."""
        from_addr = (email.get("from") or "").lower()
        domain    = self._extract_domain(from_addr)
        bl        = self._load_blacklist()
        if any(b.lower() in from_addr for b in bl.get("addresses",[])):
            return True
        if domain in [d.lower() for d in bl.get("domains",[])]:
            return True
        return False

    def _load_blacklist(self) -> dict:
        p = self._data_dir / "spam_blacklist.json"
        if p.exists():
            try: return json.loads(p.read_text(encoding="utf-8"))
            except: pass
        return {"addresses":[], "domains":[], "last_updated":None}

    def _save_blacklist(self, bl: dict):
        p = self._data_dir / "spam_blacklist.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")


    # ------------------------------------------------------------------ #
    #  עזר                                                                 #
    # ------------------------------------------------------------------ #

    def _extract_domain(self, from_addr: str) -> str:
        match = re.search(r"@([\w.-]+)", from_addr)
        return match.group(1).lower() if match else ""
