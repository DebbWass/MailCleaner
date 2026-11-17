#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_handover.py — אורז את כל פרויקט MailCleaner לשני קבצים בודדים להעברה:

    dist/MailCleaner_Setup.py   ← מתקין Python שמרכיב את עצמו (לא צריך Claude)
    dist/MailCleaner_SKILL.md   ← קובץ SKILL בודד שנותנים ל-Claude והוא בונה

מריצים:  python make_handover.py
הקוד נקרא מהקבצים האמיתיים של הפרויקט, כך שהעותק זהה למקור — בלי טעויות העתקה.
הריצי שוב בכל פעם שהפרויקט משתנה כדי לרענן את קבצי ההעברה.

⚠️  סודות (credentials.json, token.json, config.yaml, logs/, tokens/) לעולם
    אינם נכללים. כל מי שמקבל מגדיר Google Cloud וחשבון Gmail משלו.
"""

import base64
import datetime
import sys
from pathlib import Path

# קונסולת Windows ברירת-מחדל (cp1252) לא יודעת להדפיס עברית — מכריחים UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).parent
DIST = BASE / "dist"

# קבצים אמיתיים שכן נכללים (glob ברמה העליונה בלבד — הפרויקט שטוח)
INCLUDE_GLOBS = ["*.py", "*.html", "*.txt", "*.yaml", "*.md", "*.bat", ".gitignore"]

# לעולם לא לכלול — סודות / אישי / פנימי / נוצר-אוטומטית
EXCLUDE_NAMES = {
    "credentials.json", "token.json", "config.yaml",  # סודות
    "NEXT_STEPS.md",                                   # הערות פיתוח פנימיות
    "make_handover.py",                                # הסקריפט הזה
    "MailCleaner_Setup.py", "MailCleaner_SKILL.md",    # פלטים (ליתר ביטחון)
}
EXCLUDE_GLOBS = ["*.jsonl", "*.log", "*.docx", "*.zip", "*.msi", "*.pyc"]

# רמז שפה לגוש קוד לפי סיומת (עבור ה-SKILL.md)
LANG = {
    ".py": "python", ".html": "html", ".yaml": "yaml", ".yml": "yaml",
    ".txt": "text", ".md": "markdown", ".bat": "bat",
}

SETUP_GUIDE = r"""
============================================================
  הצעדים הבאים (חד-פעמי אצל כל מי שמקבל)
============================================================

1) להיכנס לתיקייה ולהתקין חבילות:
       cd MailCleaner
       pip install -r requirements.txt

2) Google Cloud (פעם אחת):
   • console.cloud.google.com → פרויקט חדש → הפעלת "Gmail API"
   • OAuth 2.0 Credentials מסוג "Desktop app" → הורדה כ-credentials.json
   • לשמור את credentials.json בתוך תיקיית MailCleaner
   • כדי שהחיבור לא יפוג כל שבוע: במסך ההסכמה (OAuth consent screen)
     לפרסם את האפליקציה ל-"Production" (ראו PRIVACY.md).

3) הגדרות אישיות:
       העתיקו config.example.yaml  →  config.yaml
       וערכו את השדה address לכתובת ה-Gmail שלכם.

4) הרצה:
       python dashboard.py            → דשבורד בכתובת http://localhost:5000
   או סריקה יבשה ללא שינויים:
       python mail_cleaner.py --dry-run

   בהרצה הראשונה ייפתח דפדפן — מתחברים עם ה-Gmail שלכם ומאשרים.

🔒 הסוכן לעולם לא מוחק מיילים — רק ממיין וממליץ. המחיקה תמיד בידי המשתמש.
============================================================
"""


def collect_files() -> dict[str, bytes]:
    """אוסף את קבצי הפרויקט האמיתיים (ברמה העליונה), ללא סודות."""
    files: dict[str, bytes] = {}
    for pat in INCLUDE_GLOBS:
        for p in sorted(BASE.glob(pat)):
            if not p.is_file():
                continue
            if p.name in EXCLUDE_NAMES:
                continue
            if any(p.match(g) for g in EXCLUDE_GLOBS):
                continue
            files[p.name] = p.read_bytes()
    return files


def build_installer(files: dict[str, bytes], generated: str) -> str:
    """בונה מתקין Python בודד שמרכיב את עצמו (base64 → קבצים אמיתיים)."""
    entries = "\n".join(
        f"    {name!r}: {base64.b64encode(data).decode('ascii')!r},"
        for name, data in files.items()
    )
    return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MailCleaner — מתקין שמרכיב את עצמו (קובץ אחד = כל הפרויקט).
הרצה:   python MailCleaner_Setup.py
יוצר תיקיית ./MailCleaner עם כל הפרויקט, מוכן להגדרה.
לא דורש שום חבילה חיצונית כדי לפרוס (רק ספריית התקן של Python).
נוצר: {generated}
"""
import base64
import sys
from pathlib import Path

# קונסולת Windows ברירת-מחדל (cp1252) לא יודעת להדפיס עברית — מכריחים UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# שם-קובץ → תוכן מקודד base64 (הקוד האמיתי והבדוק של הפרויקט)
FILES = {{
{entries}
}}

SETUP_GUIDE = {SETUP_GUIDE!r}


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    target = Path(args[0]) if args else Path.cwd() / "MailCleaner"
    target.mkdir(parents=True, exist_ok=True)

    existing = [n for n in FILES if (target / n).exists()]
    if existing and not force:
        print("⚠️  בתיקיית היעד כבר יש קבצים:", ", ".join(existing[:5]),
              "..." if len(existing) > 5 else "")
        print("   להרצה עם דריסה:  python MailCleaner_Setup.py --force")
        print("   או לתיקייה אחרת:  python MailCleaner_Setup.py <folder>")
        return 1

    print("פורס את MailCleaner אל:", target)
    for name, b64 in FILES.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(b64))
        print("  ✔", name)

    print()
    print("✅ הפרויקט נפרס בהצלחה.")
    print(SETUP_GUIDE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_skill(files: dict[str, bytes], generated: str) -> str:
    """בונה קובץ SKILL.md בודד שמכיל את כל הקוד + הוראות ל-Claude."""
    fence = "`" * 5  # גדר בת 5 תווים — בטוחה (הרצף המרבי בקבצים הוא 3)
    parts = [f'''---
name: mailcleaner-installer
description: >
  מתקין מלא של MailCleaner — סוכן AI לניקוי וארגון Gmail. כשמשתמש נותן את
  הקובץ הזה ומבקש "תתקין", "תבנה את הפרויקט" או "setup MailCleaner",
  יש ליצור את כל הקבצים שמופיעים למטה — בדיוק כפי שהם — ואז להדריך את
  המשתמש בהגדרה (Google Cloud, config.yaml, הרצה ראשונה).
---

# 📦 MailCleaner — חבילת התקנה בקובץ אחד

הקובץ הזה מכיל את **כל הקוד** של פרויקט MailCleaner. אפשר להעביר אותו לכל
אחד; מי שמקבל נותן אותו ל-Claude ומבקש להתקין, ו-Claude בונה את הפרויקט.

> 🔒 הקובץ מכיל קוד בלבד — **לא** credentials.json, לא טוקנים ולא הגדרות
> אישיות. כל מי שמקבל מגדיר Google Cloud וחשבון Gmail משלו (ראו "הגדרה" בסוף).

נוצר: {generated}

---

## 🤖 הוראות ל-Claude (קרא לפני התקנה)

כשהמשתמש מבקש להתקין/לבנות את MailCleaner מהקובץ הזה:

1. צור תיקייה בשם `MailCleaner`.
2. צור בתוכה כל אחד מהקבצים ב"קבצי הפרויקט" למטה — **תוכן מדויק, ללא שינוי**
   (שם הקובץ מופיע ככותרת מעל כל גוש קוד).
3. אל תמציא קבצים נוספים ואל תשנה את הקוד.
4. לאחר היצירה — הדרך את המשתמש לפי החלק "⚙️ הגדרה" בסוף: התקנת חבילות,
   הקמת credentials.json מ-Google Cloud, יצירת config.yaml, והרצה ראשונה.
5. ⚠️ כלל בטיחות של הפרויקט: הסוכן לעולם לא מוחק מיילים — רק ממיין וממליץ.

---

## 📂 קבצי הפרויקט
''']

    for name, data in files.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # לא אמור לקרות (כל הקבצים טקסט) — דילוג בטוח
            continue
        lang = LANG.get(Path(name).suffix.lower(), "text")
        if not text.endswith("\n"):
            text += "\n"
        parts.append(f"\n### `{name}`\n\n{fence}{lang}\n{text}{fence}\n")

    parts.append("\n---\n\n## ⚙️ הגדרה\n```\n" + SETUP_GUIDE.strip() + "\n```\n")
    return "".join(parts)


def main() -> int:
    DIST.mkdir(exist_ok=True)
    files = collect_files()
    generated = datetime.date.today().isoformat()

    installer = build_installer(files, generated)
    skill = build_skill(files, generated)

    (DIST / "MailCleaner_Setup.py").write_text(installer, encoding="utf-8")
    (DIST / "MailCleaner_SKILL.md").write_text(skill, encoding="utf-8")

    print(f"נארזו {len(files)} קבצים:")
    for n in files:
        print("  •", n)
    print()
    print("נוצר:")
    print("  dist/MailCleaner_Setup.py  ({:,} bytes)".format(
        (DIST / "MailCleaner_Setup.py").stat().st_size))
    print("  dist/MailCleaner_SKILL.md  ({:,} bytes)".format(
        (DIST / "MailCleaner_SKILL.md").stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
