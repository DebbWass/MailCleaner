# learning_engine.py — מנוע למידה משופר
# MailCleaner Project | D:\AI_Agents\MailCleaner
#
# שיפורים:
# 1. never_learn_list — מה שנמחק לא חוזר לרשימה
# 2. per_sender learning — לומד מה חשוב ומה לא לפי שולח
# 3. spam_blacklist — ספאם מאושר נכנס לרשימה שחורה קבועה

import json, logging, re
from collections import Counter
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Legacy module-level constants — kept for backward compat
DELETIONS_LOG     = Path("logs/deletions.jsonl")
PATTERNS_FILE     = Path("logs/patterns.json")
NEVER_LEARN_FILE  = Path("logs/never_learn.json")
SENDER_RULES_FILE = Path("logs/sender_rules.json")

LEARNING_THRESHOLD = 2

STOP_WORDS = {
    "re", "fwd", "fw", "the", "a", "an", "is", "in", "on", "at", "to",
    "של", "עם", "אל", "מ", "אני", "את", "הוא", "היא", "לך", "לי",
    "your", "our", "this", "that", "from", "with", "have", "will",
    "just", "get", "new", "now", "here", "hello", "dear", "hi",
}


class LearningEngine:

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = Path("logs")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._deletions_log    = self._data_dir / "deletions.jsonl"
        self._patterns_file    = self._data_dir / "patterns.json"
        self._never_learn_file = self._data_dir / "never_learn.json"
        self._sender_rules_file = self._data_dir / "sender_rules.json"

        self.patterns     = self._load_patterns()
        self.never_learn  = self._load_never_learn()
        self.sender_rules = self._load_sender_rules()

    # ------------------------------------------------------------------ #
    #  רישום מחיקות                                                         #
    # ------------------------------------------------------------------ #

    def record_deletion(self, email: dict):
        from_addr = email.get("from", "")
        subject   = email.get("subject", "")
        domain    = self._extract_domain(from_addr)
        keywords  = self._extract_keywords(subject + " " + (email.get("snippet") or ""))

        entry = {
            "timestamp": datetime.now().isoformat(),
            "from":      from_addr,
            "domain":    domain,
            "subject":   subject,
            "keywords":  keywords,
        }
        with open(self._deletions_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_bulk_deletions(self, emails: list[dict]):
        for e in emails:
            self.record_deletion(e)
        logger.info(f"נרשמו {len(emails)} מחיקות")

    # ------------------------------------------------------------------ #
    #  ניתוח ולמידה — עם never_learn                                        #
    # ------------------------------------------------------------------ #

    def analyze_and_learn(self) -> dict:
        if not self._deletions_log.exists():
            return {"new_learned": []}

        deletions = self._load_deletions()
        if not deletions:
            return {"new_learned": []}

        new_learned = []

        # כתובות — דלג על never_learn
        addr_counts = Counter(d["from"] for d in deletions if d.get("from"))
        for addr, cnt in addr_counts.items():
            if cnt >= LEARNING_THRESHOLD \
               and addr not in self.patterns["auto_candidates"] \
               and addr not in self.never_learn.get("addresses", []):
                self.patterns["auto_candidates"].append(addr)
                new_learned.append({"type": "address", "value": addr, "count": cnt})

        # דומיינים — דלג על never_learn + בדוק שאין כלל שולח-ספציפי
        domain_counts = Counter(d["domain"] for d in deletions if d.get("domain"))
        for domain, cnt in domain_counts.items():
            if cnt >= LEARNING_THRESHOLD \
               and domain not in self.patterns["blocked_domains"] \
               and domain not in self.never_learn.get("domains", []):
                if not self._has_important_rules(domain):
                    self.patterns["blocked_domains"].append(domain)
                    new_learned.append({"type": "domain", "value": domain, "count": cnt})

        # מילות מפתח — דלג על never_learn
        all_kws = []
        for d in deletions:
            all_kws.extend(d.get("keywords", []))
        kw_counts = Counter(all_kws)
        for kw, cnt in kw_counts.items():
            if cnt >= 3 \
               and kw not in self.patterns["learned_keywords"] \
               and kw not in self.never_learn.get("keywords", []) \
               and len(kw) >= 4:
                self.patterns["learned_keywords"].append(kw)
                new_learned.append({"type": "keyword", "value": kw, "count": cnt})

        self.patterns["last_updated"] = datetime.now().isoformat()
        self.patterns["total_deletions_analyzed"] = len(deletions)
        self._save_patterns()
        return {"new_learned": new_learned}

    # ------------------------------------------------------------------ #
    #  Never Learn — מחיקה שלא תחזור                                        #
    # ------------------------------------------------------------------ #

    def add_to_never_learn(self, pat_type: str, value: str):
        """
        מוסיף ערך לרשימת "לא ללמוד שוב".
        נקרא כאשר המשתמש מוחק דפוס מהדשבורד.
        pat_type: 'addresses' | 'domains' | 'keywords'
        """
        mapping = {
            "auto_candidates":  "addresses",
            "blocked_domains":  "domains",
            "learned_keywords": "keywords",
        }
        key = mapping.get(pat_type, pat_type)
        if key not in self.never_learn:
            self.never_learn[key] = []
        if value not in self.never_learn[key]:
            self.never_learn[key].append(value)
            self._save_never_learn()
            logger.info(f"נוסף ל-never_learn [{key}]: {value}")

    def add_bulk_to_never_learn(self, pat_type: str, values: list[str]):
        for v in values:
            self.add_to_never_learn(pat_type, v)

    def get_never_learn(self) -> dict:
        return dict(self.never_learn)

    # ------------------------------------------------------------------ #
    #  Sender Rules — למידה לפי שולח                                        #
    # ------------------------------------------------------------------ #

    def learn_sender_rule(self, from_addr: str, subject: str, is_important: bool):
        """
        לומד מה חשוב ומה לא לפי שולח + מאפייני נושא.
        is_important=True  → מייל ממקור זה עם נושא דומה הוא חשוב
        is_important=False → מייל ממקור זה עם נושא דומה הוא ספאם/פרסומת
        """
        domain   = self._extract_domain(from_addr.lower())
        keywords = self._extract_keywords(subject)

        if domain not in self.sender_rules:
            self.sender_rules[domain] = {"important_patterns": [], "spam_patterns": [], "count": 0}

        self.sender_rules[domain]["count"] += 1
        key = "important_patterns" if is_important else "spam_patterns"
        for kw in keywords:
            if kw not in self.sender_rules[domain][key]:
                self.sender_rules[domain][key].append(kw)

        self._save_sender_rules()
        logger.info(f"נלמד כלל שולח [{domain}]: {'חשוב' if is_important else 'ספאם'} — {keywords}")

    def classify_by_sender(self, email: dict) -> str | None:
        """
        מסווג מייל לפי כללי שולח שנלמדו.
        מחזיר: 'important' | 'spam' | None (אין כלל)
        """
        domain  = self._extract_domain((email.get("from") or "").lower())
        subject = (email.get("subject") or "").lower()

        if domain not in self.sender_rules:
            return None

        rules = self.sender_rules[domain]
        imp_score  = sum(1 for kw in rules.get("important_patterns",[]) if kw in subject)
        spam_score = sum(1 for kw in rules.get("spam_patterns",[])     if kw in subject)

        if imp_score > spam_score:
            return "important"
        if spam_score > imp_score:
            return "spam"
        return None

    def _has_important_rules(self, domain: str) -> bool:
        """בדוק אם לדומיין יש כללי 'חשוב'."""
        return bool(self.sender_rules.get(domain, {}).get("important_patterns"))

    # ------------------------------------------------------------------ #
    #  בדיקת מועמד למחיקה                                                   #
    # ------------------------------------------------------------------ #

    def is_deletion_candidate(self, email: dict) -> tuple[bool, str]:
        from_addr = (email.get("from") or "").lower()
        domain    = self._extract_domain(from_addr)
        subject   = (email.get("subject") or "").lower()

        sender_class = self.classify_by_sender(email)
        if sender_class == "important":
            return False, ""
        if sender_class == "spam":
            return True, f"דפוס ספאם מ-{domain}"

        for addr in self.patterns["auto_candidates"]:
            if addr.lower() in from_addr:
                return True, f"כתובת ידועה: {addr}"

        for blocked in self.patterns["blocked_domains"]:
            if blocked.lower() == domain:
                return True, f"דומיין חסום: {blocked}"

        for kw in self.patterns["learned_keywords"]:
            if kw.lower() in subject:
                return True, f"מילת מפתח: '{kw}'"

        return False, ""

    def get_summary(self) -> str:
        p  = self.patterns
        nl = self.never_learn
        sr = self.sender_rules
        return (
            f"כתובות: {len(p['auto_candidates'])} | "
            f"דומיינים: {len(p['blocked_domains'])} | "
            f"מילות מפתח: {len(p['learned_keywords'])} | "
            f"never-learn: {sum(len(v) for v in nl.values() if isinstance(v,list))} | "
            f"כללי שולח: {len(sr)}"
        )

    # ------------------------------------------------------------------ #
    #  עזר פנימי                                                             #
    # ------------------------------------------------------------------ #

    def _extract_domain(self, addr: str) -> str:
        m = re.search(r"@([\w.-]+)", addr)
        return m.group(1).lower() if m else ""

    def _extract_keywords(self, text: str) -> list[str]:
        words = re.findall(r"\b[\wא-ת]{4,}\b", text.lower())
        return [w for w in words if w not in STOP_WORDS][:6]

    def _load_deletions(self) -> list[dict]:
        out = []
        try:
            for line in self._deletions_log.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try: out.append(json.loads(line))
                    except: pass
        except Exception as e:
            logger.error(f"שגיאה בטעינת היסטוריה: {e}")
        return out

    def _load_patterns(self) -> dict:
        if self._patterns_file.exists():
            try: return json.loads(self._patterns_file.read_text(encoding="utf-8"))
            except: pass
        return {"auto_candidates": [], "blocked_domains": [], "learned_keywords": [],
                "last_updated": None, "total_deletions_analyzed": 0}

    def _save_patterns(self):
        self._patterns_file.parent.mkdir(parents=True, exist_ok=True)
        self._patterns_file.write_text(json.dumps(self.patterns, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_never_learn(self) -> dict:
        if self._never_learn_file.exists():
            try: return json.loads(self._never_learn_file.read_text(encoding="utf-8"))
            except: pass
        return {"addresses": [], "domains": [], "keywords": []}

    def _save_never_learn(self):
        self._never_learn_file.parent.mkdir(parents=True, exist_ok=True)
        self._never_learn_file.write_text(json.dumps(self.never_learn, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_sender_rules(self) -> dict:
        if self._sender_rules_file.exists():
            try: return json.loads(self._sender_rules_file.read_text(encoding="utf-8"))
            except: pass
        return {}

    def _save_sender_rules(self):
        self._sender_rules_file.parent.mkdir(parents=True, exist_ok=True)
        self._sender_rules_file.write_text(json.dumps(self.sender_rules, ensure_ascii=False, indent=2), encoding="utf-8")
