# scheduler.py — הרצה אוטומטית של MailCleaner לפי לוח זמנים
# MailCleaner Project | D:\AI_Agents\MailCleaner

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time
import yaml
from rich.console import Console

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/cleaner.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
console = Console()

CONFIG_FILE = Path("config.yaml")


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_cleaner(accounts: str = "all"):
    """מריץ את mail_cleaner.py בתהליך נפרד."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    console.print(f"\n[bold blue]⏰ {now} — מתחיל ריצה אוטומטית[/bold blue]")
    logger.info(f"Scheduled run started at {now} (accounts: {accounts})")

    cmd = [sys.executable, "mail_cleaner.py", "--mode", "auto", "--accounts", accounts]

    try:
        result = subprocess.run(
            cmd,
            capture_output=False,
            text=True,
            cwd=Path(__file__).parent,
        )
        if result.returncode == 0:
            logger.info("✅ ריצה אוטומטית הסתיימה בהצלחה")
        else:
            logger.error(f"❌ ריצה אוטומטית נכשלה (קוד: {result.returncode})")
    except Exception as e:
        logger.error(f"❌ שגיאה בהרצה אוטומטית: {e}")


def setup_schedule(config: dict):
    """מגדיר את לוח הזמנים לפי config.yaml."""
    sched_cfg = config.get("scheduler", {})

    if not sched_cfg.get("enabled", False):
        console.print("[yellow]⚠️ Scheduler מושבת ב-config.yaml[/yellow]")
        return False

    run_time = sched_cfg.get("time", "08:00")
    days = sched_cfg.get("days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Sunday"])
    accounts = str(sched_cfg.get("accounts", "all"))

    day_map = {
        "Sunday": schedule.every().sunday,
        "Monday": schedule.every().monday,
        "Tuesday": schedule.every().tuesday,
        "Wednesday": schedule.every().wednesday,
        "Thursday": schedule.every().thursday,
        "Friday": schedule.every().friday,
        "Saturday": schedule.every().saturday,
    }

    for day in days:
        if day in day_map:
            day_map[day].at(run_time).do(run_cleaner, accounts=accounts)
            logger.info(f"📅 תוזמן: כל {day} ב-{run_time} (accounts: {accounts})")

    console.print(f"[green]✅ Scheduler פעיל — ריצה ב-{run_time} בימים: {', '.join(days)}[/green]")
    if accounts != "all":
        console.print(f"[dim]חשבונות: {accounts}[/dim]")
    return True


def main():
    console.rule("[bold blue]📧 MailCleaner Scheduler[/bold blue]")

    config = load_config()
    active = setup_schedule(config)

    if not active:
        console.print("[dim]כדי להפעיל, שנה scheduler.enabled ל-true ב-config.yaml[/dim]")
        return

    console.print("[dim]Scheduler רץ ברקע. לעצירה: Ctrl+C[/dim]\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # בדיקה כל 30 שניות
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler הופסק.[/yellow]")


if __name__ == "__main__":
    main()
