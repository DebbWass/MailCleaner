# classifier.py — מנוע סיווג חכם
# MailCleaner Project

import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

# ── מיילים ישנים ────────────────────────────────────────────────────
OLD_EMAIL_YEARS = 2

def is_old_email(email: dict) -> tuple[bool, str]:
    date_str = email.get("date", "")
    if not date_str:
        return False, ""
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        if age > timedelta(days=OLD_EMAIL_YEARS * 365):
            years = age.days // 365
            return True, f"מייל ישן ({years} שנים)"
    except Exception:
        pass
    return False, ""

# ── פישינג / תרמיות ─────────────────────────────────────────────────
PHISHING_PATTERNS = [
    r"urgent.{0,20}(action|verify|confirm|update)",
    r"(account|password).{0,20}(suspend|block|expir|verif)",
    r"(click|tap).{0,20}(here|link|below).{0,20}(now|immediately|urgent)",
    r"your.{0,15}account.{0,15}(has been|will be).{0,15}(suspend|terminat|block)",
    r"(congratulations|you.{0,5}won|you.{0,5}selected).{0,30}(prize|reward|gift|million|lottery)",
    r"(wire transfer|western union|bitcoin|crypto).{0,30}(send|transfer|payment)",
    r"(verify|confirm|update).{0,20}(credit card|bank|ssn|social security|password)",
]

FRAUD_KEYWORDS = [
    "wire transfer", "western union", "money gram", "gift card",
    "bitcoin payment", "nigerian prince", "lottery winner",
    "unclaimed funds", "guaranteed returns", "risk-free investment",
    "זכית בפרס", "העבר כסף", "כרטיס מתנה", "השקעה מובטחת",
]

def check_phishing(email: dict) -> tuple[bool, str, str]:
    subject = (email.get("subject") or "").lower()
    snippet = (email.get("snippet") or "").lower()
    body    = (email.get("body")    or "").lower()
    text    = subject + " " + snippet + " " + body

    for pattern in PHISHING_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"דפוס פישינג זוהה", "danger"
    for kw in FRAUD_KEYWORDS:
        if kw.lower() in text:
            return True, f"מילת תרמית: '{kw}'", "danger"
    return False, "", ""

# ── ספאם ────────────────────────────────────────────────────────────
SPAM_SUBJECT_PATTERNS = [
    r"\b(sale|offer|deal|discount)\b.{0,30}\d+%",
    r"\d+%.{0,20}(off|discount|sale)",
    r"(free|win|prize|reward).{0,20}(now|today|limited)",
    r"(don.t miss|last chance|ends (today|soon)|limited time)",
    r"(buy now|shop now|order now|click here)",
    r"(מבצע|הנחה|חינם|הצעה מיוחדת|לזמן מוגבל|קנה עכשיו)",
]

# סימני ניוזלטר / מייל שיווקי
MARKETING_INDICATORS = [
    "unsubscribe", "opt-out", "opt out", "manage preferences",
    "email preferences", "הסר מרשימה", "ביטול הרשמה",
    "view in browser", "view online",
    "you received this", "you are receiving this",
    "©", "all rights reserved",
]

# ── פונקציית סיווג ראשית ────────────────────────────────────────────
def classify_email(email: dict, config: dict, learner,
                   receipt_org=None) -> tuple[str, str]:
    """
    מסווג מייל בודד.
    מחזיר (category, reason).

    קטגוריות:
      important | danger | warning | receipt | newsletter |
      deletion_candidate | old_email | other
    """
    from_addr = (email.get("from")    or "").lower()
    subject   = (email.get("subject") or "").lower()
    body      = (email.get("body")    or "").lower()
    snippet   = (email.get("snippet") or "").lower()

    rules          = config.get("rules", {})
    important_snds = [s.lower() for s in rules.get("important_senders", [])]
    cfg_spam_kws   = [k.lower() for k in rules.get("spam_keywords", [])]

    # ── 1. שולח חשוב ────────────────────────────────────────────────
    if any(s in from_addr for s in important_snds):
        return "important", "שולח חשוב"

    # ── 2. מנוע למידה (כולל כלל שולח) ──────────────────────────────
    sender_class = learner.classify_by_sender(email)
    if sender_class == "important":
        return "important", "כלל שולח: חשוב"
    if sender_class == "spam":
        return "deletion_candidate", "כלל שולח: ספאם"

    is_cand, reason = learner.is_deletion_candidate(email)
    if is_cand:
        return "deletion_candidate", reason

    # ── 3. פישינג / תרמית ───────────────────────────────────────────
    is_phish, reason, severity = check_phishing(email)
    if is_phish:
        return severity, reason

    # ── 4. קבלות ────────────────────────────────────────────────────
    if receipt_org and receipt_org.is_receipt(email):
        return "receipt", "קבלה/אישור"
    receipt_kws = [
        "receipt", "invoice", "order", "confirmation", "booking",
        "חשבונית", "קבלה", "הזמנה", "אישור", "חיוב", "תשלום",
    ]
    if any(kw in subject for kw in receipt_kws):
        return "receipt", "קבלה/אישור"

    # ── 5. ספאם/פרסומת — נושא ───────────────────────────────────────
    for pattern in SPAM_SUBJECT_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            return "deletion_candidate", "דפוס ספאם בנושא"

    # ── 6. מילות ספאם מה-config (נושא + גוף + snippet) ─────────────
    search_text = subject + " " + snippet + " " + body
    for kw in cfg_spam_kws:
        if kw in search_text:
            return "deletion_candidate", f"מילת ספאם: '{kw}'"

    # ── 7. מיילים ישנים ─────────────────────────────────────────────
    is_old, reason = is_old_email(email)
    if is_old:
        return "old_email", reason

    # ── 8. ניוזלטר ──────────────────────────────────────────────────
    # בדוק ב-snippet קודם (מהיר), הגוף נטען בשלב ב' אם צריך
    check_text  = subject + " " + snippet + " " + body
    has_unsub   = any(m in check_text for m in MARKETING_INDICATORS)

    if has_unsub:
        return "newsletter", "ניוזלטר"

    return "other", ""
