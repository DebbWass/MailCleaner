---
name: mail-cleaner
description: >
  ניקוי, ארגון וניהול תיבת Gmail באופן חכם ובטוח.
  השתמש ב-Skill הזה בכל פעם שהמשתמש מזכיר:
  ניקוי מייל, ארגון תיבת דואר, מחיקת ספאם, הסרה מרשימות תפוצה,
  סיכום מיילים חשובים, ניהול Gmail, inbox cleanup, unsubscribe,
  הפעלה אוטומטית של ניקוי מייל, או כל בקשה שקשורה לתיבת הדואר.
  ⚠️ חשוב: אין למחוק מיילים ללא אישור מפורש של המשתמש.
compatibility:
  python: ">=3.9"
  packages:
    - google-auth-oauthlib
    - google-api-python-client
    - imaplib2
    - pyyaml
    - schedule
    - rich
  os: Windows / Mac / Linux
  folder: D:\AI_Agents\MailCleaner
---

# 📧 MailCleaner Skill

כלי חכם לניקוי וארגון Gmail — עם אישור משתמש לפני כל פעולה הרסנית.

---

## 🗂️ מבנה הפרויקט

```
D:\AI_Agents\MailCleaner\
├── SKILL.md              ← המסמך הזה
├── config.yaml           ← הגדרות אישיות (כתובת מייל, פילטרים, לוח זמנים)
├── requirements.txt      ← חבילות Python
├── credentials.json      ← מפתח Gmail API (לא להעלות ל-Git!)
├── token.json            ← טוקן גישה (נוצר אוטומטית)
│
├── gmail_api.py          ← התחברות דרך Gmail API (ראשי)
├── imap_client.py        ← התחברות דרך IMAP (גיבוי)
├── mail_cleaner.py       ← לוגיקה ראשית: סיווג, ארגון, סיכום
├── scheduler.py          ← הרצה אוטומטית לפי לוח זמנים
├── learning_engine.py    ← מנוע למידה מהרגלי המחיקה של המשתמש
├── spam_reviewer.py      ← סריקת תיקיית SPAM לאיתור מיילים לגיטימיים
├── delete_review.py      ← ממשק בחירה ומחיקה מתיקיית "מועמדים למחיקה"
└── logs/
    ├── cleaner.log       ← לוג פעולות
    └── deletions.jsonl   ← היסטוריית מחיקות ללמידה
```

> 📂 **תיקיית "מועמדים למחיקה" ב-Gmail** — הסוכן מרכז שם את כל המיילים שלדעתו כדאי למחוק. המשתמש בוחר ידנית מה למחוק בפועל.

---

## ⚙️ הגדרות (config.yaml)

```yaml
gmail:
  address: "your@gmail.com"
  connection:
    primary: "gmail_api"      # gmail_api | imap
    fallback: "imap"

rules:
  spam_keywords: ["unsubscribe", "newsletter", "promotion", "offer", "deal"]
  important_senders: ["boss@company.com", "family@example.com"]
  folders:                    # תיקיות לארגון
    - name: "חשוב"
      filter: "from:important_senders"
    - name: "ניוזלטרים"
      filter: "unsubscribe in:body"
    - name: "קבלות"
      filter: "subject:(receipt OR invoice OR order)"

safety:
  require_approval_before_delete: true   # ⚠️ תמיד true!
  max_emails_per_run: 100
  dry_run: false                          # true = סימולציה בלבד

scheduler:
  enabled: true
  cron: "0 8 * * *"          # כל יום ב-08:00
  timezone: "Asia/Jerusalem"
```

---

## 🔌 התחברות ל-Gmail

### שיטה 1: Gmail API (מומלץ)

1. היכנס ל-[Google Cloud Console](https://console.cloud.google.com/)
2. צור פרויקט חדש → הפעל **Gmail API**
3. צור **OAuth 2.0 credentials** → הורד כ-`credentials.json`
4. שמור את הקובץ בתיקיית `D:\AI_Agents\MailCleaner\`
5. בהרצה ראשונה — תיפתח חלון דפדפן לאישור גישה

### שיטה 2: IMAP (גיבוי)

1. ב-Gmail: Settings → Security → **Enable 2-Step Verification**
2. Settings → Security → **App Passwords** → צור סיסמת אפליקציה
3. הכנס את הסיסמה ב-`config.yaml` תחת `imap.app_password`

> ⚡ הקוד מנסה Gmail API קודם. אם נכשל — עובר אוטומטית ל-IMAP.

---

## 🚀 תהליך עבודה (Workflow)

### הרצה ידנית

```bash
cd D:\AI_Agents\MailCleaner
python mail_cleaner.py --mode manual
```

### הרצה אוטומטית (Scheduler)

```bash
python scheduler.py
```

### סימולציה (ללא שינויים אמיתיים)

```bash
python mail_cleaner.py --dry-run
```

---

## 🔄 שלבי הפעולה

```
1. התחברות (API → IMAP fallback)
         ↓
2. קריאת מיילים (לפי max_emails_per_run)
         ↓
3. סיווג חכם (כולל למידה מהיסטוריה):
   • ספאם / לא רצוי
   • ניוזלטרים (unsubscribe)
   • קבלות / חשבוניות
   • מיילים חשובים
   • מועמדים למחיקה (לפי דפוסים שנלמדו)
         ↓
4. ארגון אוטומטי לתיקיות (ללא אישור)
         ↓
5. העברת מועמדים למחיקה → תיקיית "🗑️ מועמדים למחיקה" ב-Gmail
         ↓
6. סריקת תיקיית SPAM — זיהוי False Positives:
   • מחשב ציון לגיטימיות לכל מייל בספאם
   • מציג רק מיילים עם ציון גבוה (שולח אמיתי / נושא לגיטימי / תגובה לשיחה)
   • המשתמש מחליט: החזר ל-Inbox / ספאם ודאי / דלג
         ↓
7. הצגת סיכום: כמה מיילים הועברו לתיקייה + כמה הוחזרו מספאם
         ↓
7. המשתמש פותח את התיקייה, בוחר ומוחק ידנית
         ↓
8. מנוע הלמידה מנתח את מה שנמחק → מעדכן patterns.json
         ↓
9. סיכום מיילים חשובים + כתיבה ל-log
```

---

## 🧠 מנוע הלמידה

הסוכן לומד מכל מחיקה שהמשתמש מבצע ומשפר את ההמלצות לאורך זמן.

**מה נלמד:**
- כתובות שחוזרות על עצמן במחיקות → נוספות לרשימת `auto_candidates`
- מילות מפתח בנושא/גוף שחוזרות → נוספות ל-`learned_keywords`
- דומיינים שנמחקים תמיד (כמו `@newsletters.com`) → מסומנים כ-`blocked_domains`

**סף ללמידה:** אחרי 3 מחיקות מאותו מקור — הסוכן מציין "למדתי שמיילים מ-X לא מעניינים אותך"

**קובץ הלמידה:** `logs/deletions.jsonl` — כל שורה היא אירוע מחיקה אחד:
```json
{"timestamp": "2025-01-15T08:00:00", "from": "promo@shop.com", "subject": "Sale!", "keywords": ["sale", "offer"], "domain": "shop.com"}
```

---

## 🛡️ כללי בטיחות (חובה!)

| פעולה | מי מבצע? | דורש אישור? |
|-------|----------|-------------|
| ארגון לתיקיות | סוכן | ❌ לא |
| העברה ל"מועמדים למחיקה" | סוכן | ❌ לא (רק ממיין, לא מוחק) |
| מחיקה בפועל | **המשתמש בלבד** | ✅ תמיד |
| סימון כ-spam | סוכן | ✅ כן |
| הסרה מרשימת תפוצה | סוכן | ✅ כן |

> 🔒 הסוכן **לעולם לא מוחק** — הוא רק ממליץ ומארגן. המחיקה היא תמיד בידי המשתמש.

---

## 📋 כשClaude משתמש ב-Skill הזה

1. **תמיד** לקרוא את `config.yaml` לפני כל פעולה
2. **תמיד** להציג סיכום של מה שהועבר ל"מועמדים למחיקה" ולמה
3. **לעולם לא** למחוק מיילים — רק להעביר לתיקיית ההמלצות
4. אחרי כל ריצה — להריץ `learning_engine.py` כדי לעדכן את הדפוסים
5. לדווח אם נלמד משהו חדש ("שמתי לב שמחקת 3 מיילים מ-X — רצית שאוסיף לרשימה האוטומטית?")
6. **תמיד** לסרוק את תיקיית SPAM ולהציג למשתמש מיילים עם ציון לגיטימיות גבוה בלבד
7. לשמור את החלטות המשתמש בנושא SPAM ב-`logs/spam_review.jsonl` ללמידה עתידית
8. אם Gmail API נכשל — לעבור ל-IMAP ולציין זאת למשתמש

---

## 🔧 פתרון בעיות נפוצות

| בעיה | פתרון |
|------|-------|
| `credentials.json` לא נמצא | הורד מ-Google Cloud Console |
| `Token expired` | מחק `token.json` והרץ מחדש |
| IMAP נכשל | ודא שסיסמת האפליקציה נכונה |
| `quota exceeded` | המתן 24 שעות (מגבלת Gmail API) |

---

## 📎 קבצים נוספים לקרוא

- `gmail_api.py` — לוגיקת Gmail API המלאה
- `imap_client.py` — לוגיקת IMAP המלאה
- `mail_cleaner.py` — הלוגיקה הראשית
- `scheduler.py` — הגדרות לוח זמנים
- `learning_engine.py` — מנוע הלמידה מהרגלי המחיקה
- `spam_reviewer.py` — סריקת SPAM וזיהוי False Positives
- `delete_review.py` — ממשק סקירה ומחיקה מתיקיית המועמדים
