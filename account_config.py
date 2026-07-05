# account_config.py — helpers for multi-account config normalization
# MailCleaner Project | D:\AI_Agents\MailCleaner

from pathlib import Path

BASE_DIR = Path(__file__).parent


def load_accounts(config: dict) -> list[dict]:
    """
    Returns a normalized list of account config dicts.
    Handles both new `accounts:` format and legacy `gmail:` format transparently.
    Each returned dict has: address, token_file (absolute path), connection, imap, name.
    """
    if "accounts" in config:
        accounts = list(config["accounts"])
    elif "gmail" in config:
        g = config["gmail"]
        accounts = [{
            "name":       g.get("address", "default"),
            "address":    g["address"],
            "token_file": "token.json",
            "connection": g.get("connection", {"primary": "gmail_api", "fallback": "imap"}),
            "imap":       g.get("imap", {}),
        }]
    else:
        raise ValueError("config.yaml חייב להכיל 'accounts' או 'gmail'")

    for acc in accounts:
        acc["token_file"] = str(BASE_DIR / acc["token_file"])
        acc.setdefault("name", acc["address"])

    return accounts


def resolve_accounts(all_accounts: list[dict], selector) -> list[dict]:
    """
    Filters accounts based on --accounts CLI argument.
    selector=None or "all" → all accounts.
    selector="a@g.com,b@g.com" → matching accounts only.
    Raises ValueError if a specified address is not configured.
    """
    if selector is None or str(selector).strip().lower() == "all":
        return all_accounts

    requested = {s.strip().lower() for s in str(selector).split(",") if s.strip()}
    by_address = {acc["address"].lower(): acc for acc in all_accounts}

    missing = requested - set(by_address.keys())
    if missing:
        raise ValueError(
            f"חשבונות לא מוגדרים: {missing}\n"
            f"חשבונות קיימים: {list(by_address.keys())}"
        )

    return [by_address[addr] for addr in requested if addr in by_address]


def data_dir_for(account: dict) -> Path:
    """
    Returns the per-account data directory: logs/<address>/
    Creates it if it doesn't exist.
    """
    d = BASE_DIR / "logs" / account["address"]
    d.mkdir(parents=True, exist_ok=True)
    return d
