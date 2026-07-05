#!/usr/bin/env python3
"""
MailCleaner — סקריפט התקנה
=================================
הרץ: python install.py
"""

import sys
import os
import subprocess
import shutil
import platform
from pathlib import Path

# ── צבעים לטרמינל ────────────────────────────────────
class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"
    # Windows לא תמיד תומך בצבעים
    if platform.system() == "Windows":
        GREEN = YELLOW = RED = CYAN = BOLD = RESET = ""

def ok(msg):    print(f"{C.GREEN}  ✓ {msg}{C.RESET}")
def info(msg):  print(f"{C.CYAN}  → {msg}{C.RESET}")
def warn(msg):  print(f"{C.YELLOW}  ⚠ {msg}{C.RESET}")
def err(msg):   print(f"{C.RED}  ✗ {msg}{C.RESET}")
def title(msg): print(f"\n{C.BOLD}{C.CYAN}{msg}{C.RESET}")
def hr():       print("─" * 55)

# ── קבועים ───────────────────────────────────────────
INSTALL_DIR   = Path.home() / "AI_Agents" / "MailCleaner"
REQUIRED_PY   = (3, 9)
PACKAGES_FILE = Path(__file__).parent / "requirements.txt"
CONFIG_FILE   = Path(__file__).parent / "config.yaml"
SOURCE_DIR    = Path(__file__).parent


def check_python():
    title("1. בדיקת גרסת Python")
    v = sys.version_info
    info(f"Python {v.major}.{v.minor}.{v.micro}")
    if (v.major, v.minor) < REQUIRED_PY:
        err(f"נדרשת גרסה {REQUIRED_PY[0]}.{REQUIRED_PY[1]}+")
        err("הורד מ-https://python.org/downloads")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor} — תקין")


def create_install_dir():
    title("2. יצירת תיקיית התקנה")
    if INSTALL_DIR.exists():
        warn(f"תיקייה קיימת: {INSTALL_DIR}")
        ans = input("     להחליף? (y/n): ").strip().lower()
        if ans != "y":
            info("ביטול — ההתקנה הקיימת נשמרת")
            return False
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    (INSTALL_DIR / "logs").mkdir(exist_ok=True)
    (INSTALL_DIR / "docs").mkdir(exist_ok=True)
    ok(f"תיקייה נוצרה: {INSTALL_DIR}")
    return True


def copy_files():
    title("3. העתקת קבצי הפרויקט")
    
    # קבצים להעתקה (ללא קבצים אישיים)
    skip = {"credentials.json", "token.json", ".gitignore", "install.py",
            "__pycache__", ".git", "logs", ".DS_Store"}
    
    source = SOURCE_DIR
    copied = 0
    
    for item in source.rglob("*"):
        # דלג על קבצים שלא צריך להעתיק
        if any(s in item.parts for s in skip):
            continue
        if item.name.startswith("."):
            continue
        if item.suffix in (".pyc", ".pyo"):
            continue
            
        rel = item.relative_to(source)
        dest = INSTALL_DIR / rel
        
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            info(f"  {rel}")
            copied += 1
    
    ok(f"{copied} קבצים הועתקו")


def install_packages():
    title("4. התקנת חבילות Python")
    
    if not PACKAGES_FILE.exists():
        warn("requirements.txt לא נמצא — מדלג")
        return
    
    info("מתקין חבילות (עשוי לקחת כמה דקות)...")
    
    cmd = [sys.executable, "-m", "pip", "install", "-r",
           str(INSTALL_DIR / "requirements.txt"), "--quiet"]
    
    # Windows — הוסף --break-system-packages אם צריך
    if platform.system() != "Windows":
        cmd.append("--break-system-packages")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        warn("שגיאה בהתקנת חבילות:")
        print(result.stderr[:500])
        info("נסה להריץ ידנית: pip install -r requirements.txt")
    else:
        ok("כל החבילות הותקנו בהצלחה")


def configure_email():
    title("5. הגדרת כתובת Gmail")
    
    config_path = INSTALL_DIR / "config.yaml"
    if not config_path.exists():
        warn("config.yaml לא נמצא")
        return
    
    content = config_path.read_text(encoding="utf-8")
    
    if "YOUR_EMAIL@gmail.com" in content:
        print(f"\n  הכניסי את כתובת Gmail שלך:")
        email = input("  Gmail: ").strip()
        if "@gmail.com" in email or "@" in email:
            content = content.replace("YOUR_EMAIL@gmail.com", email)
            config_path.write_text(content, encoding="utf-8")
            ok(f"כתובת הוגדרה: {email}")
        else:
            warn("כתובת לא תקינה — ערכי ידנית ב-config.yaml")
    else:
        ok("config.yaml כבר מוגדר")


def check_credentials():
    title("6. בדיקת credentials.json")
    
    cred_in_source = SOURCE_DIR / "credentials.json"
    cred_in_dest   = INSTALL_DIR / "credentials.json"
    
    if cred_in_dest.exists():
        ok("credentials.json קיים")
        return
    
    if cred_in_source.exists():
        shutil.copy2(cred_in_source, cred_in_dest)
        ok("credentials.json הועתק")
        return
    
    warn("credentials.json לא נמצא!")
    print("""
  כדי לקבל אותו:
  1. היכנסי ל-https://console.cloud.google.com
  2. צרי פרויקט → הפעילי Gmail API
  3. צרי OAuth 2.0 Credentials (Desktop app)
  4. הורידי את הקובץ כ-credentials.json
  5. שמרי ב: """ + str(INSTALL_DIR))


def create_shortcuts():
    title("7. יצירת קיצורי דרך")
    
    system = platform.system()
    
    if system == "Windows":
        # צור bat files
        run_bat = INSTALL_DIR / "run_dashboard.bat"
        run_bat.write_text(
            f'@echo off\ncd /d "{INSTALL_DIR}"\n'
            f'echo Starting MailCleaner Dashboard...\n'
            f'python dashboard.py\npause\n',
            encoding="utf-8"
        )
        ok(f"נוצר: run_dashboard.bat")
        
        scan_bat = INSTALL_DIR / "run_scan.bat"
        scan_bat.write_text(
            f'@echo off\ncd /d "{INSTALL_DIR}"\n'
            f'echo Running MailCleaner scan...\n'
            f'python mail_cleaner.py --max 50\npause\n',
            encoding="utf-8"
        )
        ok(f"נוצר: run_scan.bat")
        
    elif system == "Darwin":  # macOS
        sh = INSTALL_DIR / "run_dashboard.sh"
        sh.write_text(
            f'#!/bin/bash\ncd "{INSTALL_DIR}"\n'
            f'open http://localhost:5000\npython3 dashboard.py\n'
        )
        sh.chmod(0o755)
        ok(f"נוצר: run_dashboard.sh")
        
    else:  # Linux
        sh = INSTALL_DIR / "run_dashboard.sh"
        sh.write_text(
            f'#!/bin/bash\ncd "{INSTALL_DIR}"\n'
            f'xdg-open http://localhost:5000 2>/dev/null &\n'
            f'python3 dashboard.py\n'
        )
        sh.chmod(0o755)
        ok(f"נוצר: run_dashboard.sh")


def print_summary():
    title("✅ MailCleaner הותקן בהצלחה!")
    hr()
    print(f"""
  📁 תיקיית התקנה: {INSTALL_DIR}

  🚀 להפעלת הדשבורד:""")
    
    if platform.system() == "Windows":
        print(f"     לחצי פעמיים על: run_dashboard.bat")
        print(f"     או הריצי:  cd \"{INSTALL_DIR}\" && python dashboard.py")
    else:
        print(f"     ./run_dashboard.sh")
        print(f"     או: cd \"{INSTALL_DIR}\" && python3 dashboard.py")
    
    print(f"""
  🌐 כתובת הדשבורד: http://localhost:5000

  📖 מדריך הגדרת Google:
     {INSTALL_DIR}/docs/setup_google.md
""")
    
    if not (INSTALL_DIR / "credentials.json").exists():
        print(f"  ⚠️  אל תשכחי להוסיף credentials.json!\n")
    
    hr()


def main():
    print(f"""
{C.BOLD}{C.CYAN}
  ╔══════════════════════════════════════╗
  ║     📧  MailCleaner Installer       ║
  ║     סוכן AI לניקוי Gmail            ║
  ╚══════════════════════════════════════╝
{C.RESET}""")
    
    try:
        check_python()
        should_copy = create_install_dir()
        if should_copy is not False:
            copy_files()
        install_packages()
        configure_email()
        check_credentials()
        create_shortcuts()
        print_summary()
        
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}  ← ביטול על ידי המשתמש{C.RESET}\n")
        sys.exit(0)
    except Exception as e:
        err(f"שגיאה לא צפויה: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
