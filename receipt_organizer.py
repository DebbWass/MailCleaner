# receipt_organizer.py — ארגון קבלות לתת-תיקיות לפי דומיין שולח
# MailCleaner Project | D:\AI_Agents\MailCleaner
#
# לוגיקה:
# 1. מחלץ דומיין מכתובת השולח (למשל: noreply@hot.co.il → hot.co.il)
# 2. בודק אם יש שם מותאם אישית לדומיין הזה (מקובץ domain_names.json)
# 3. אם לא — משתמש בשם הדומיין עצמו
# 4. יוצר תת-תיקייה: קבלות/שם-הדומיין
# 5. אם המשתמש שינה שם תיקייה — שומר את הקישור לעתיד

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

RECEIPTS_FOLDER = "קבלות"
# Legacy constant — kept for backward compat
DOMAIN_NAMES_FILE = Path("logs/domain_names.json")

# מילות מפתח שמזהות מייל כקבלה
RECEIPT_KEYWORDS = {
    "subject": [
        # עברית
        "חשבונית", "קבלה", "אישור תשלום", "אישור הזמנה", "חשבון",
        "הזמנה", "מסמך", "חיוב", "תשלום", "העברה", "יתרה",
        # אנגלית
        "invoice", "receipt", "order confirmation", "payment confirmation",
        "your order", "order #", "purchase", "billing", "statement",
        "booking confirmation", "reservation", "subscription",
    ],
    "body": [
        "total", "amount due", "סה\"כ לתשלום", "מספר הזמנה",
        "order number", "transaction id", "reference number",
    ]
}


class ReceiptOrganizer:
    """
    מארגן קבלות לתת-תיקיות לפי דומיין השולח.
    לומד שמות מותאמים אישית שהמשתמש קובע.
    """

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path("logs")
        self._domain_names_file = Path(data_dir) / "domain_names.json"
        self.domain_names = self._load_domain_names()

    # ------------------------------------------------------------------ #
    #  זיהוי קבלות                                                         #
    # ------------------------------------------------------------------ #

    def is_receipt(self, email: dict) -> bool:
        """בודק אם מייל הוא קבלה/אישור."""
        subject = (email.get("subject") or "").lower()
        body = (email.get("body") or "").lower()

        for kw in RECEIPT_KEYWORDS["subject"]:
            if kw.lower() in subject:
                return True

        for kw in RECEIPT_KEYWORDS["body"]:
            if kw.lower() in body:
                return True

        return False

    # ------------------------------------------------------------------ #
    #  קביעת שם תיקייה                                                     #
    # ------------------------------------------------------------------ #

    def get_folder_for_email(self, email: dict) -> str:
        """
        מחזיר את נתיב תת-התיקייה המתאים למייל.
        פורמט: קבלות/שם-דומיין
        """
        domain = self._extract_domain(email.get("from", ""))
        folder_name = self._resolve_folder_name(domain)
        return f"{RECEIPTS_FOLDER}/{folder_name}"

    def _resolve_folder_name(self, domain: str) -> str:
        """
        מחזיר שם תיקייה לדומיין.
        אם יש שם מותאם אישית — מחזיר אותו.
        אחרת — מחזיר את הדומיין עצמו (נקי).
        """
        if domain in self.domain_names:
            return self.domain_names[domain]

        # נקה את הדומיין לשם תיקייה נאה
        clean = domain.replace("www.", "")
        # הסר סיומות נפוצות לשם קצר יותר
        for suffix in [".co.il", ".com", ".net", ".org", ".il"]:
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
                break

        return clean or domain

    # ------------------------------------------------------------------ #
    #  למידת שמות מותאמים אישית                                            #
    # ------------------------------------------------------------------ #

    def learn_rename(self, domain: str, new_name: str):
        """
        שומר קישור בין דומיין לשם תיקייה שהמשתמש בחר.
        נקרא כאשר המשתמש משנה שם של תיקיית קבלות.
        """
        old_name = self.domain_names.get(domain, domain)
        self.domain_names[domain] = new_name
        self._save_domain_names()
        logger.info(f"🧠 נלמד: דומיין '{domain}' → תיקייה '{new_name}' (היה: '{old_name}')")

    def scan_renamed_folders(self, client) -> int:
        """
        סורק את תיקיית הקבלות ב-Gmail ומחפש שמות שהשתנו.
        אם תיקייה קיימת עם שם שונה מהדומיין — שומר את הקישור.
        מחזיר כמה שינויי שם נמצאו.
        """
        if not hasattr(client, "get_labels"):
            return 0

        labels = client.get_labels()
        learned = 0

        for label in labels:
            name = label.get("name", "")
            # חפש תיקיות שהן תת-תיקיות של קבלות
            if name.startswith(f"{RECEIPTS_FOLDER}/"):
                subfolder = name[len(f"{RECEIPTS_FOLDER}/"):]
                # בדוק אם יש דומיין שמוביל לשם אחר
                for domain, mapped_name in self.domain_names.items():
                    if mapped_name != subfolder and self._resolve_folder_name(domain) == subfolder:
                        # השם השתנה — עדכן
                        self.learn_rename(domain, subfolder)
                        learned += 1

        return learned

    def get_all_mappings(self) -> dict:
        """מחזיר את כל הקישורים דומיין → שם תיקייה."""
        return dict(self.domain_names)

    # ------------------------------------------------------------------ #
    #  ביצוע ארגון                                                         #
    # ------------------------------------------------------------------ #

    def organize_receipts(self, receipt_emails: list[dict], client, dry_run: bool = False) -> dict:
        """
        מעביר קבלות לתת-תיקיות לפי דומיין.
        מחזיר סיכום { folder_name: count }.
        """
        summary = {}

        # סרוק שמות שהשתנו לפני הארגון
        renamed = self.scan_renamed_folders(client)
        if renamed > 0:
            logger.info(f"🔄 נמצאו {renamed} שינויי שם בתיקיות קבלות")

        # קבץ לפי תיקייה לביצוע batch
        folder_groups: dict[str, list[str]] = {}
        for email in receipt_emails:
            folder = self.get_folder_for_email(email)
            domain = self._extract_domain(email.get("from", ""))

            if dry_run:
                logger.info(f"[SIM] '{email['subject'][:40]}' → '{folder}'")
            else:
                if folder not in folder_groups:
                    folder_groups[folder] = []
                folder_groups[folder].append(email["id"])

            summary[folder] = summary.get(folder, 0) + 1

            # שמור מיפוי דומיין → שם תיקייה
            folder_name_only = folder.split("/")[-1]
            if domain and domain not in self.domain_names:
                self.domain_names[domain] = folder_name_only
                self._save_domain_names()

        # בצע batch move לכל תיקייה
        if not dry_run:
            for folder, msg_ids in folder_groups.items():
                if hasattr(client, "batch_move_to_label"):
                    client.batch_move_to_label(msg_ids, folder)
                elif hasattr(client, "move_to_label"):
                    for mid in msg_ids:
                        client.move_to_label(mid, folder)
                else:
                    for mid in msg_ids:
                        client.move_to_folder(mid, folder)
                logger.info(f"קבלות → '{folder}': {len(msg_ids)} מיילים")

        return summary

    # ------------------------------------------------------------------ #
    #  עזר פנימי                                                           #
    # ------------------------------------------------------------------ #

    def _extract_domain(self, from_addr: str) -> str:
        """מחלץ דומיין מכתובת מייל."""
        # תמיכה בפורמט "שם" <email@domain.com>
        match = re.search(r"<(.+?)>", from_addr)
        addr = match.group(1) if match else from_addr
        domain_match = re.search(r"@([\w.-]+)", addr)
        return domain_match.group(1).lower() if domain_match else "אחר"

    def _load_domain_names(self) -> dict:
        """טוען קישורי דומיין → שם מותאם."""
        if self._domain_names_file.exists():
            try:
                with open(self._domain_names_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_domain_names(self):
        """שומר קישורי דומיין → שם מותאם."""
        self._domain_names_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._domain_names_file, "w", encoding="utf-8") as f:
            json.dump(self.domain_names, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 מיפויי דומיינים נשמרו ({len(self.domain_names)} רשומות)")
