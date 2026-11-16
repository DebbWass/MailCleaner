# MailCleaner — Privacy Policy / מדיניות פרטיות

_Last updated: 2026-11-16_

## English

MailCleaner is a **personal, self-hosted tool** that helps a single user organize
their own Gmail inbox. It is run locally by the user on their own computer.

**Data access.** MailCleaner uses the Gmail API to read email metadata (sender,
subject, date, labels) and to move messages between labels/folders in the user's
own Gmail account. It requests the scopes `gmail.readonly`, `gmail.modify`, and
`gmail.labels`.

**Data storage.** All data is stored **locally on the user's own machine** (in the
project's `logs/` folder) and in the user's own Gmail account. The application:

- Does **not** send email contents to any third-party server.
- Does **not** share, sell, or transmit personal data to anyone.
- Does **not** permanently delete email — it only moves messages into folders; the
  user alone performs any deletion.
- Stores OAuth tokens (`token.json`) locally and never transmits them elsewhere.

**Weekly summary email.** If enabled by the user, the tool sends a summary report
**only to the user's own email address**, from the user's own account.

**Contact.** For questions about this tool, contact: sendit2dorit@gmail.com

---

## עברית

MailCleaner הוא **כלי אישי שרץ מקומית** ועוזר למשתמש יחיד לארגן את תיבת ה-Gmail
שלו עצמו. הכלי מופעל על ידי המשתמש במחשב שלו.

**גישה לנתונים.** הכלי משתמש ב-Gmail API כדי לקרוא מטא-דאטה של מיילים (שולח, נושא,
תאריך, תוויות) ולהעביר הודעות בין תיקיות/תוויות בחשבון ה-Gmail של המשתמש עצמו.

**שמירת נתונים.** כל המידע נשמר **מקומית במחשב של המשתמש** (בתיקיית `logs/`) ובחשבון
ה-Gmail של המשתמש. הכלי:

- **אינו** שולח את תוכן המיילים לשום שרת חיצוני.
- **אינו** משתף, מוכר או מעביר מידע אישי לאף גורם.
- **אינו** מוחק מיילים לצמיתות — רק מעביר אותם לתיקיות; המחיקה בפועל נעשית על ידי
  המשתמש בלבד.
- שומר את טוקני ה-OAuth (`token.json`) מקומית בלבד ואינו מעביר אותם לשום מקום.

**דוח סיכום שבועי.** אם המשתמש מפעיל זאת, הכלי שולח דוח סיכום **רק לכתובת המייל של
המשתמש עצמו**, מהחשבון של המשתמש.

**יצירת קשר:** sendit2dorit@gmail.com
