# 📧 MailCleaner

**סוכן AI לניהול וניקוי תיבת Gmail — לומד מהרגלים שלך ומשתפר עם הזמן.**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![Gmail API](https://img.shields.io/badge/Gmail-API-red.svg)](https://developers.google.com/gmail)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## ✨ מה זה עושה?

- 🗂️ **מארגן** מיילים לתיקיות אוטומטית (קבלות, ניוזלטרים, חשובים)
- 🗑️ **מזהה** מועמדים למחיקה — ואת המחיקה עושה **המשתמש בלבד**
- 🧠 **לומד** מהרגלי המחיקה שלך ומשפר את הסינון לאורך זמן
- 🚨 **מזהה** פישינג, תרמיות ומיילים מסוכנים
- 📬 **סורק** תיקיית SPAM ומוצא מיילים לגיטימיים שנתפסו בטעות
- 📊 **דשבורד** Web נוח — הכל בלחיצת כפתור, ללא טרמינל

---

## 🚀 התקנה מהירה

```bash
# 1. שכפלי את הפרויקט
git clone https://github.com/YOUR_USERNAME/MailCleaner.git
cd MailCleaner

# 2. הרץ סקריפט התקנה
python install.py
```

> **Windows:** לחצי פעמיים על `install.py` או הרץ `python install.py`

---

## 📋 דרישות מקדימות

| דרישה | גרסה |
|-------|-------|
| Python | 3.9+ |
| חשבון Gmail | כלשהו |
| Google Cloud Console | [הגדרה — 5 דקות](docs/setup_google.md) |

---

## ⚙️ הגדרת Google Cloud (חובה)

1. היכנסי ל-[console.cloud.google.com](https://console.cloud.google.com)
2. צרי פרויקט חדש → הפעילי **Gmail API**
3. צרי **OAuth 2.0 Credentials** → הורידי `credentials.json`
4. שמרי את הקובץ בתיקיית הפרויקט
5. הריצי את הפרויקט — בפעם הראשונה יפתח דפדפן לאישור

> 📖 מדריך מפורט: [docs/setup_google.md](docs/setup_google.md)

---

## 🖥️ הפעלה

```bash
# הפעל את הדשבורד
python dashboard.py
# ➜ פתחי דפדפן בכתובת: http://localhost:5000

# או — סריקה ישירה מהטרמינל
python mail_cleaner.py --max 50 --dry-run
```

---

## 📁 מבנה הפרויקט

```
MailCleaner/
├── 📄 install.py              ← סקריפט התקנה
├── 📄 mail_cleaner.py         ← לוגיקה ראשית
├── 📄 dashboard.py            ← שרת Web
├── 📄 dashboard.html          ← ממשק משתמש
├── 📄 classifier.py           ← מנוע סיווג חכם
├── 📄 learning_engine.py      ← מנוע למידה
├── 📄 gmail_api.py            ← Gmail API
├── 📄 imap_client.py          ← IMAP (גיבוי)
├── 📄 receipt_organizer.py    ← ארגון קבלות
├── 📄 spam_reviewer.py        ← סקירת SPAM
├── 📄 deletion_tracker.py     ← מעקב מחיקות
├── 📄 scheduler.py            ← הרצה אוטומטית
├── 📄 config.yaml             ← הגדרות
├── 📄 requirements.txt        ← חבילות Python
├── 📄 SKILL.md                ← הגדרת Skill ל-Claude
└── 📁 logs/                   ← נוצר אוטומטית (לא ב-Git)
```

---

## 🛡️ אבטחה

- ✅ הסוכן **לעולם לא מוחק** מיילים — רק ממיין לתיקיות
- ✅ `credentials.json` ו-`token.json` **לא** מועלים ל-Git
- ✅ כל המידע האישי נשמר **מקומית בלבד**
- ✅ מצב Dry Run לבדיקה ללא שינויים

---

## 📖 תיעוד

- [מדריך התקנה מלא](docs/setup_google.md)
- [מסמך דרישות](MailCleaner_Requirements.docx)
- [שאלות נפוצות](docs/faq.md)

---

## 🤝 תרומה לפרויקט

Pull Requests מתקבלים בברכה! אנא קראי את [CONTRIBUTING.md](CONTRIBUTING.md) לפני.

---

## 📄 רישיון

MIT License — ראי [LICENSE](LICENSE)
