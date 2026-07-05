# deletion_tracker.py — מעקב אחרי מה המשתמש מחק בפועל מתיקיית המועמדים
# MailCleaner Project | D:\AI_Agents\MailCleaner
#
# איך זה עובד:
# 1. לפני כל ריצה — שומר snapshot של תיקיית "מועמדים למחיקה" (ID + פרטים)
# 2. בסוף ריצה — משווה snapshot חדש לישן
# 3. מה שנעלם = המשתמש מחק → שומר ללמידה
# 4. מה שנשאר = המשתמש לא מחק → לא לומד מזה

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CANDIDATES_FOLDER  = "מועמדים למחיקה"

# Legacy module-level constants — kept for backward compat with any external code
SNAPSHOT_FILE  = Path("logs/candidates_snapshot.json")
DELETIONS_LOG  = Path("logs/deletions.jsonl")
HISTORY_FILE   = Path("logs/run_history.jsonl")
PROTECTED_FILE = Path("logs/protected_emails.json")


class DeletionTracker:
    """
    עוקב אחרי מה המשתמש מחק בפועל מתיקיית המועמדים ב-Gmail.
    משתמש בטכניקת snapshot: משווה מצב לפני ואחרי.
    data_dir: תיקיית נתונים ייחודית לחשבון. ברירת מחדל: logs/ (תאימות לאחור).
    """

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path("logs")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_file  = self._data_dir / "candidates_snapshot.json"
        self._deletions_log  = self._data_dir / "deletions.jsonl"
        self._history_file   = self._data_dir / "run_history.jsonl"
        self._protected_file = self._data_dir / "protected_emails.json"

    # ------------------------------------------------------------------ #
    #  Snapshot — צילום מצב תיקייה                                         #
    # ------------------------------------------------------------------ #

    def save_snapshot(self, client) -> int:
        """
        שומר snapshot של תיקיית המועמדים.
        מחזיר כמה מיילים נמצאו.
        קורא לפונקציה זו בתחילת כל ריצה.
        """
        emails = self._fetch_candidates(client)
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "count": len(emails),
            "emails": {e["id"]: {
                "from": e.get("from", ""),
                "subject": e.get("subject", ""),
                "date": e.get("date", ""),
            } for e in emails}
        }
        with open(self._snapshot_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        logger.info(f"📸 Snapshot נשמר: {len(emails)} מיילים בתיקיית מועמדים")
        return len(emails)

    def detect_deletions(self, client) -> list[dict]:
        """
        משווה snapshot ישן למצב נוכחי.
        מבדיל בין:
        - נמחק: מייל שנעלם מהתיקייה ולא קיים ב-Gmail → למידה
        - הוצא ידנית: מייל שנעלם מהתיקייה אך עדיין קיים → נוסף לרשימת מוגנים
        """
        if not self._snapshot_file.exists():
            logger.info("אין snapshot קודם — זו ריצה ראשונה")
            return []

        with open(self._snapshot_file, "r", encoding="utf-8") as f:
            old_snapshot = json.load(f)

        old_ids    = set(old_snapshot.get("emails", {}).keys())
        old_emails = old_snapshot.get("emails", {})

        current_emails = self._fetch_candidates(client)
        current_ids    = {e["id"] for e in current_emails}

        disappeared_ids = old_ids - current_ids
        if not disappeared_ids:
            logger.info("לא זוהו שינויים בתיקיית מועמדים")
            return []

        # בדוק איזה מיילים עדיין קיימים ב-Gmail (הוצאו ידנית)
        truly_deleted = []
        manually_removed = []

        for mid in disappeared_ids:
            email_data = {**old_emails.get(mid, {}), "id": mid,
                          "deleted_at": datetime.now().isoformat()}
            if self._email_still_exists(client, mid):
                # עדיין קיים ב-Gmail — המשתמש הוציא אותו ידנית
                manually_removed.append(email_data)
            else:
                # לא קיים — נמחק
                truly_deleted.append(email_data)

        # מיילים שהוצאו ידנית → שמור כמוגנים
        if manually_removed:
            self._add_to_protected([e["id"] for e in manually_removed])
            logger.info(f"✋ {len(manually_removed)} מיילים הוצאו ידנית מהתיקייה — מוגנים מסריקה עתידית")
            for e in manually_removed:
                logger.info(f"   מוגן: {e.get('subject','')[:50]} | {e.get('from','')[:40]}")

        # מיילים שנמחקו → שמור ללמידה
        if truly_deleted:
            logger.info(f"🗑️ זוהו {len(truly_deleted)} מחיקות אמיתיות")
            self._log_deletions(truly_deleted)

        return truly_deleted

    def _email_still_exists(self, client, msg_id: str) -> bool:
        """בודק אם מייל עדיין קיים ב-Gmail (לא נמחק לצמיתות)."""
        try:
            if hasattr(client, "service"):
                client.service.users().messages().get(
                    userId="me", id=msg_id, format="minimal",
                    fields="id"
                ).execute()
                return True
            return False
        except Exception:
            return False  # 404 = נמחק

    def _add_to_protected(self, ids: list[str]):
        """מוסיף IDs לרשימת המוגנים."""
        protected = self._load_protected()
        added = 0
        for mid in ids:
            if mid not in protected["ids"]:
                protected["ids"].append(mid)
                added += 1
        protected["last_updated"] = datetime.now().isoformat()
        self._protected_file.parent.mkdir(parents=True, exist_ok=True)
        self._protected_file.write_text(json.dumps(protected, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        if added:
            total = len(protected["ids"])
            logger.info(f"נוספו {added} למוגנים (סהכ: {total})")

    def get_protected_ids(self) -> set:
        """מחזיר סט של IDs מוגנים — לא יחזרו למועמדים."""
        return set(self._load_protected().get("ids", []))

    def _load_protected(self) -> dict:
        if self._protected_file.exists():
            try:
                return json.loads(self._protected_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ids": [], "last_updated": None}


    def log_run(self, stats: dict):
        """שומר סיכום ריצה להיסטוריה — תמיד, גם אם לא הושלמה."""
        now   = datetime.now()
        entry = {
            "timestamp": now.isoformat(),
            "date":      now.strftime("%Y-%m-%d"),
            "time":      now.strftime("%H:%M"),
            "completed": stats.get("completed", True),
        }
        for k, v in stats.items():
            entry[k] = v

        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        status = "הושלמה" if entry["completed"] else "לא הושלמה"
        logger.info(f"ריצה נרשמה ({status}) — {stats.get('total_scanned',0)} מיילים, {stats.get('num_batches',0)} באצ'ים")


    def get_history(self, last_n: int = 30) -> list[dict]:
        """מחזיר היסטוריית ריצות אחרונות."""
        if not self._history_file.exists():
            return []
        entries = []
        with open(self._history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        return list(reversed(entries[-last_n:]))

    def get_deletion_stats(self) -> dict:
        """סטטיסטיקות מחיקות כלליות."""
        if not self._deletions_log.exists():
            return {"total": 0, "top_domains": [], "top_keywords": []}

        from collections import Counter
        import re

        deletions = []
        with open(self._deletions_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        deletions.append(json.loads(line))
                    except Exception:
                        pass

        domains = []
        for d in deletions:
            match = re.search(r"@([\w.-]+)", d.get("from", ""))
            if match:
                domains.append(match.group(1))

        domain_counts = Counter(domains).most_common(5)
        return {
            "total": len(deletions),
            "top_domains": [{"domain": d, "count": c} for d, c in domain_counts],
        }

    # ------------------------------------------------------------------ #
    #  עזר פנימי                                                           #
    # ------------------------------------------------------------------ #

    def _fetch_candidates(self, client) -> list[dict]:
        """
        קורא מיילים מתיקיית המועמדים עם metadata מלא —
        כך שנוכל לשמור from/subject ללמידה.
        """
        try:
            if hasattr(client, "get_emails"):
                return client.get_emails(
                    max_results=200,
                    query=f'label:"{CANDIDATES_FOLDER}"'
                )
            else:
                return client.get_emails(max_results=100, folder=CANDIDATES_FOLDER)
        except Exception as e:
            logger.error(f"שגיאה בקריאת תיקיית מועמדים: {e}")
            return []

    def _log_deletions(self, deleted: list[dict]):
        """שומר מחיקות לקובץ הלמידה."""
        with open(self._deletions_log, "a", encoding="utf-8") as f:
            for d in deleted:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        logger.info(f"💾 {len(deleted)} מחיקות נשמרו ל-deletions.jsonl")
