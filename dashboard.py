# dashboard.py — דשבורד MailCleaner (תמיכה multi-account)
# הרצה: python dashboard.py | גישה: http://localhost:5000

import json, shutil, subprocess, sys, re, threading, queue, signal
from pathlib import Path
import yaml
from flask import Flask, jsonify, render_template, request, Response

app  = Flask(__name__, template_folder=".")
LOGS = Path("logs")
LOGS.mkdir(exist_ok=True)

# Global log file — shared across all accounts
CLEANER_LOG = LOGS / "cleaner.log"

_MIGRATION_FILES = [
    "patterns.json", "deletions.jsonl", "never_learn.json",
    "sender_rules.json", "spam_blacklist.json", "spam_review.jsonl",
    "run_history.jsonl", "candidates_snapshot.json",
    "protected_emails.json", "scanned_ids.json", "domain_names.json",
]

def _migrate_root_data_if_needed():
    """העברה חד-פעמית: אם logs/ שורש מכיל נתונים ותיקיית החשבון ריקה — מעתיק."""
    if not any((LOGS / f).exists() for f in _MIGRATION_FILES):
        return  # אין נתוני שורש — כלום לא צריך
    try:
        accounts = _get_all_accounts()
    except Exception:
        return
    for acc in accounts:
        token_path = Path(acc.get("token_file", ""))
        if not token_path.exists():
            continue  # חשבון ללא טוקן — לא הגדרת המקור
        acc_dir = LOGS / acc["address"]
        if any((acc_dir / f).exists() for f in _MIGRATION_FILES):
            continue  # לחשבון כבר יש נתונים
        acc_dir.mkdir(parents=True, exist_ok=True)
        for fname in _MIGRATION_FILES:
            src = LOGS / fname
            if src.exists():
                shutil.copy2(str(src), str(acc_dir / fname))
        print(f"[MailCleaner] נתונים הועברו מ-logs/ ל-logs/{acc['address']}/", flush=True)
        break  # מספיק להעביר לחשבון הראשון המתאים

CANDIDATES_FOLDER = "מועמדים למחיקה"

# תהליך נוכחי (לעצירה)
_current_proc = None
_proc_lock    = threading.Lock()

# SSE
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

def _push(data: dict):
    msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try: q.put_nowait(msg)
            except queue.Full: dead.append(q)
        for q in dead: _sse_clients.remove(q)


# ------------------------------------------------------------------ #
#  עזר multi-account                                                   #
# ------------------------------------------------------------------ #

def _get_account_addr(req) -> str:
    """מחלץ כתובת חשבון מ-query param ?account= או מגוף ה-JSON."""
    addr = req.args.get("account", "").strip()
    if not addr and req.method in ("POST", "PUT"):
        try:
            body = req.get_json(silent=True) or {}
            addr = body.get("account", "").strip()
        except Exception:
            pass
    return addr


def _resolve_data_dir(req) -> Path:
    """
    מחזיר תיקיית נתונים לחשבון הנבחר.
    אם לא צוין חשבון — מחזיר logs/ (תאימות לאחור).
    """
    addr = _get_account_addr(req)
    if addr:
        d = LOGS / addr
        d.mkdir(parents=True, exist_ok=True)
        return d
    return LOGS


def _load_config():
    """טוען config.yaml."""
    p = Path("config.yaml")
    if p.exists():
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


def _get_all_accounts() -> list[dict]:
    """מחזיר רשימת חשבונות מקונפיג."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from account_config import load_accounts
        config = _load_config()
        return load_accounts(config)
    except Exception:
        return []


_migrate_root_data_if_needed()


def _get_account_cfg(req) -> dict | None:
    """מחזיר dict הגדרות לחשבון הנבחר (ה-token_file וכו')."""
    addr = _get_account_addr(req)
    accounts = _get_all_accounts()
    if not accounts:
        return None
    if addr:
        for acc in accounts:
            if acc["address"].lower() == addr.lower():
                return acc
    return accounts[0]  # ברירת מחדל: חשבון ראשון


def _make_gmail_client(req):
    """יוצר GmailAPIClient עם ה-token_file הנכון לחשבון."""
    from gmail_api import GmailAPIClient
    acc = _get_account_cfg(req)
    if acc:
        return GmailAPIClient(token_file=acc.get("token_file"))
    return GmailAPIClient()


def _make_learner(req):
    """יוצר LearningEngine עם data_dir הנכון לחשבון."""
    from learning_engine import LearningEngine
    data_dir = _resolve_data_dir(req)
    return LearningEngine(data_dir=data_dir)


def _make_spam_reviewer(req):
    """יוצר SpamReviewer עם data_dir הנכון לחשבון."""
    from spam_reviewer import SpamReviewer
    data_dir = _resolve_data_dir(req)
    return SpamReviewer(config={}, important_senders=[], data_dir=data_dir)


# ------------------------------------------------------------------ #
#  Routes
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/events")
def sse_stream():
    q = queue.Queue(maxsize=100)
    with _sse_lock: _sse_clients.append(q)
    def generate():
        yield 'data: {"type":"connected"}\n\n'
        try:
            while True:
                try: yield q.get(timeout=25)
                except queue.Empty: yield 'data: {"type":"ping"}\n\n'
        except GeneratorExit:
            with _sse_lock:
                if q in _sse_clients: _sse_clients.remove(q)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


# ------------------------------------------------------------------ #
#  חשבונות                                                             #
# ------------------------------------------------------------------ #

@app.route("/api/accounts")
def list_accounts():
    """מחזיר את כל החשבונות המוגדרים ב-config.yaml."""
    accounts = _get_all_accounts()
    return jsonify([
        {"address": a["address"], "name": a.get("name", a["address"])}
        for a in accounts
    ])


# ------------------------------------------------------------------ #
#  מצב חיבור ל-Gmail + התחברות מחדש                                   #
# ------------------------------------------------------------------ #

@app.route("/api/connection-status")
def connection_status():
    """
    מחזיר את מצב החיבור ל-Gmail לחשבון הנבחר — בלי לפתוח דפדפן אף פעם.
    משמש את פס-המצב בראש הדשבורד.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        client = _make_gmail_client(request)
        st = client.get_connection_status()
    except Exception as e:
        return jsonify({"connected": False, "needs_reauth": True,
                        "message": f"שגיאה בבדיקת חיבור: {e}"})

    # הערכת ימים שנותרו עד שהחיבור יפוג (רלוונטי לאפליקציה במצב Testing — 7 ימים)
    days_left = None
    dsa = st.get("days_since_authorized")
    if isinstance(dsa, int):
        days_left = max(0, 7 - dsa)
    st["estimated_days_left"] = days_left
    return jsonify(st)


@app.route("/api/reconnect", methods=["POST"])
def reconnect_gmail():
    """
    מריץ חיבור מחדש מלא (פותח דפדפן במחשב המקומי) — מחליף את הצורך למחוק token.json ידנית.
    רץ ברקע ומדווח דרך SSE.
    """
    # מחשבים את ה-token_file בתוך בקשת ה-HTTP (יש כאן request תקף) ומעבירים ל-thread
    acc = _get_account_cfg(request)
    token_file = acc.get("token_file") if acc else None

    def _do_reconnect(tok):
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from gmail_api import GmailAPIClient
            client = GmailAPIClient(token_file=tok)
            _push({"type": "reconnect_started",
                   "message": "נפתח חלון דפדפן לאישור הגישה ל-Gmail..."})
            ok = client.force_reauth()
            if ok:
                _push({"type": "reconnect_done", "success": True,
                       "message": "✅ החיבור ל-Gmail חודש בהצלחה"})
            else:
                _push({"type": "reconnect_done", "success": False,
                       "message": "❌ חידוש החיבור נכשל — בדוק/י ש-credentials.json קיים"})
        except Exception as e:
            _push({"type": "reconnect_done", "success": False,
                   "message": f"❌ שגיאה בחידוש חיבור: {e}"})

    threading.Thread(target=_do_reconnect, args=(token_file,), daemon=True).start()
    return jsonify({"success": True, "message": "חידוש החיבור התחיל — עקוב/י אחרי חלון הדפדפן"})


# ------------------------------------------------------------------ #
#  סטטיסטיקות                                                          #
# ------------------------------------------------------------------ #

@app.route("/api/stats")
def stats():
    d = _resolve_data_dir(request)
    dels  = _load_jsonl(d / "deletions.jsonl")
    spam  = _load_jsonl(d / "spam_review.jsonl")
    pat   = _load_json(d / "patterns.json")
    return jsonify({
        "total_deletions":   len(dels),
        "learned_addresses": len(pat.get("auto_candidates",[])),
        "learned_domains":   len(pat.get("blocked_domains",[])),
        "learned_keywords":  len(pat.get("learned_keywords",[])),
        "moved_to_inbox":    sum(1 for r in spam if r.get("decision")=="moved_to_inbox"),
        "confirmed_spam":    sum(1 for r in spam if r.get("decision")=="confirmed_spam"),
    })

@app.route("/api/recent-deletions")
def recent_deletions():
    d = _resolve_data_dir(request)
    return jsonify(list(reversed(_load_jsonl(d / "deletions.jsonl")[-30:])))

@app.route("/api/spam-reviews")
def spam_reviews():
    d = _resolve_data_dir(request)
    return jsonify(list(reversed(_load_jsonl(d / "spam_review.jsonl")[-20:])))

@app.route("/api/patterns")
def patterns():
    d = _resolve_data_dir(request)
    p = _load_json(d / "patterns.json")
    p["summary"] = (
        f"כתובות: {len(p.get('auto_candidates',[]))} | "
        f"דומיינים: {len(p.get('blocked_domains',[]))} | "
        f"מילות מפתח: {len(p.get('learned_keywords',[]))}"
    )
    return jsonify(p)

@app.route("/api/history")
def run_history():
    d = _resolve_data_dir(request)
    return jsonify(list(reversed(_load_jsonl(d / "run_history.jsonl")[-30:])))

@app.route("/api/log")
def get_log():
    # לוג גלובלי — משותף לכל החשבונות
    try:
        lines = CLEANER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({"lines": list(reversed(lines[-80:]))})
    except FileNotFoundError:
        return jsonify({"lines": []})

@app.route("/api/scanned-ids")
def scanned_ids():
    d = _resolve_data_dir(request)
    try:
        ids = json.loads((d / "scanned_ids.json").read_text(encoding="utf-8"))
        return jsonify({"count": len(ids)})
    except:
        return jsonify({"count": 0})


# ------------------------------------------------------------------ #
#  תיקיות                                                              #
# ------------------------------------------------------------------ #

@app.route("/api/folders")
def get_folders():
    """כל התיקיות כולל מערכת + תיקיות משתמש."""
    system = [
        {"id":"INBOX",     "name":"Inbox",    "type":"system"},
        {"id":"SPAM",      "name":"Spam",     "type":"system"},
        {"id":"SENT",      "name":"Sent",     "type":"system"},
        {"id":"TRASH",     "name":"Trash",    "type":"system"},
        {"id":"STARRED",   "name":"Starred",  "type":"system"},
        {"id":"IMPORTANT", "name":"Important","type":"system"},
    ]
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        client = _make_gmail_client(request)
        if client.connect():
            user = []
            for l in client.get_labels():
                if l.get("type") != "user":
                    continue
                user.append({"id": l["id"], "name": l["name"], "type": "user"})
            user.sort(key=lambda x: x["name"])
            return jsonify(system + user)
    except Exception as e:
        app.logger.error(f"folders: {e}")
    return jsonify(system)


# ------------------------------------------------------------------ #
#  דומיינים                                                             #
# ------------------------------------------------------------------ #

@app.route("/api/domain-names", methods=["GET"])
def domain_names():
    d = _resolve_data_dir(request)
    return jsonify(_load_json(d / "domain_names.json"))


@app.route("/api/protected-emails")
def protected_emails():
    d = _resolve_data_dir(request)
    data = _load_json(d / "protected_emails.json")
    return jsonify({
        "count":        len(data.get("ids", [])),
        "last_updated": data.get("last_updated"),
    })


@app.route("/api/protected-emails/clear", methods=["POST"])
def clear_protected():
    d = _resolve_data_dir(request)
    p = d / "protected_emails.json"
    p.write_text(json.dumps({"ids": [], "last_updated": None}, ensure_ascii=False), encoding="utf-8")
    return jsonify({"success": True})


@app.route("/api/never-learn")
def never_learn():
    d = _resolve_data_dir(request)
    return jsonify(_load_json(d / "never_learn.json"))


@app.route("/api/sender-rules")
def sender_rules():
    d = _resolve_data_dir(request)
    data = _load_json(d / "sender_rules.json")
    summary = []
    for domain, rules in data.items():
        summary.append({
            "domain":    domain,
            "important": rules.get("important_patterns",[]),
            "spam":      rules.get("spam_patterns",[]),
            "count":     rules.get("count",0),
        })
    summary.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(summary)


@app.route("/api/spam-blacklist")
def spam_blacklist():
    d = _resolve_data_dir(request)
    return jsonify(_load_json(d / "spam_blacklist.json"))


@app.route("/api/domain-names", methods=["POST"])
def update_domain_name():
    body = request.json or {}
    if not body.get("domain") or not body.get("new_name"):
        return jsonify({"success": False})
    d = _resolve_data_dir(request)
    p = d / "domain_names.json"
    m = _load_json(p)
    m[body["domain"]] = body["new_name"]
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"success": True})


# ------------------------------------------------------------------ #
#  ניהול דפוסי למידה — מחיקה                                           #
# ------------------------------------------------------------------ #

@app.route("/api/patterns/delete", methods=["POST"])
def delete_pattern():
    body     = request.json or {}
    pat_type = body.get("type")
    value    = body.get("value","").strip()
    if not pat_type or not value:
        return jsonify({"success": False, "error": "חסרים שדות"})
    d        = _resolve_data_dir(request)
    pf       = d / "patterns.json"
    patterns = _load_json(pf)
    lst      = patterns.get(pat_type, [])
    if value in lst:
        lst.remove(value)
        patterns[pat_type] = lst
        pf.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        _make_learner(request).add_to_never_learn(pat_type, value)
    except Exception as e:
        app.logger.error(f"never_learn error: {e}")
    return jsonify({"success": True, "removed": value})


@app.route("/api/patterns/delete-bulk", methods=["POST"])
def delete_patterns_bulk():
    body     = request.json or {}
    pat_type = body.get("type")
    values   = body.get("values", [])
    if not pat_type or not values:
        return jsonify({"success": False, "error": "חסרים שדות"})
    d        = _resolve_data_dir(request)
    pf       = d / "patterns.json"
    patterns = _load_json(pf)
    lst      = patterns.get(pat_type, [])
    removed  = 0
    for v in values:
        v = v.strip()
        if v in lst:
            lst.remove(v)
            removed += 1
    patterns[pat_type] = lst
    pf.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        learner = _make_learner(request)
        learner.add_bulk_to_never_learn(pat_type, [v.strip() for v in values])
    except Exception as e:
        app.logger.error(f"never_learn error: {e}")
    return jsonify({"success": True, "removed": removed})


# ------------------------------------------------------------------ #
#  הרצה ועצירה                                                          #
# ------------------------------------------------------------------ #

@app.route("/api/run", methods=["POST"])
def run_cleaner():
    global _current_proc
    d          = request.json or {}
    folders    = d.get("folders",["INBOX"])
    order      = d.get("order","newest")
    rescan     = d.get("rescan",False)
    dry_run    = d.get("dry_run",False)
    scan_all   = d.get("scan_all", False)
    max_emails = -1 if scan_all else d.get("max_emails", 50)
    read_filter= d.get("read_filter","all")
    account    = d.get("account", "all")   # חשבון לריצה

    cmd = [sys.executable, "mail_cleaner.py",
           "--max",      str(max_emails),
           "--order",    order,
           "--folders",  ",".join(folders),
           "--skip-spam",
           "--read-filter", read_filter,
           "--accounts", account]
    if dry_run:   cmd.append("--dry-run")
    if rescan:    cmd.append("--rescan")
    if scan_all:  cmd.append("--all")

    _push({"type":"run_started","message":f"סריקה התחילה — {len(folders)} תיקיות, {max_emails} מיילים"})

    def run_in_thread():
        global _current_proc
        try:
            proc = subprocess.Popen(cmd, cwd=Path(__file__).parent,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            with _proc_lock: _current_proc = proc
            for line in proc.stdout:
                _push({"type":"log_line","line":line.rstrip()})
            proc.wait()
            _push({"type":"run_complete","message":"הסריקה הסתיימה" if proc.returncode==0 else "הסריקה הופסקה"})
        except Exception as e:
            _push({"type":"run_error","message":str(e)})
        finally:
            with _proc_lock: _current_proc = None

    t = threading.Thread(target=run_in_thread, daemon=True)
    t.start()
    return jsonify({"success":True, "message":"הסריקה התחילה ברקע"})


@app.route("/api/stop", methods=["POST"])
def stop_cleaner():
    global _current_proc
    with _proc_lock:
        if _current_proc:
            _current_proc.terminate()
            _push({"type":"run_complete","message":"הסריקה הופסקה"})
            return jsonify({"success":True})
    return jsonify({"success":False, "message":"אין תהליך פעיל"})


@app.route("/api/run-learn", methods=["POST"])
def run_learn():
    account = (request.json or {}).get("account", "all")
    _push({"type":"run_started","message":"מפעיל ניתוח למידה..."})
    try:
        r = subprocess.run(
            [sys.executable, "mail_cleaner.py", "--learn", "--accounts", account],
            cwd=Path(__file__).parent,
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
        output = r.stdout + r.stderr
        _push({"type":"run_complete","message":"למידה הסתיימה"})
        return jsonify({"success":True,"output":output})
    except Exception as e:
        return jsonify({"success":False,"output":str(e)})


# ------------------------------------------------------------------ #
#  למידה מתיקיית המועמדים                                              #
# ------------------------------------------------------------------ #

@app.route("/api/learn-from-folder", methods=["POST"])
def learn_from_folder():
    try:
        sys.path.insert(0, str(Path(__file__).parent))

        client = _make_gmail_client(request)
        if not client.connect():
            return jsonify({"success":False,"output":"לא הצלחתי להתחבר ל-Gmail"})

        emails = []
        queries = [
            f'label:"{CANDIDATES_FOLDER}"',
            f'in:"{CANDIDATES_FOLDER}"',
            f'label:מועמדים-למחיקה',
        ]
        for q in queries:
            emails = client.get_emails(max_results=200, query=q)
            if emails:
                app.logger.info(f"Found {len(emails)} emails with query: {q}")
                break

        if not emails:
            labels = client.get_labels()
            cand_label = None
            for l in labels:
                if "מועמד" in l["name"] or "מחיקה" in l["name"]:
                    cand_label = l["id"]
                    break
            if cand_label:
                emails = client.get_emails(max_results=200, query=f"label:{cand_label}")

        if not emails:
            labels = client.get_labels()
            label_names = [l["name"] for l in labels if l.get("type") != "system"]
            return jsonify({
                "success":True,
                "output": "לא נמצאו מיילים. תיקיות קיימות:\n" + "\n".join(label_names[:20]),
                "count": 0
            })

        learner = _make_learner(request)
        learner.record_bulk_deletions(emails)
        result  = learner.analyze_and_learn()
        new_l   = result.get("new_learned",[])

        lines = [f"נקראו {len(emails)} מיילים מתיקיית המועמדים"]
        if new_l:
            lines.append(f"נלמדו {len(new_l)} דפוסים חדשים:")
            for item in new_l:
                t = {"address":"כתובת","domain":"דומיין","keyword":"מילה"}.get(item["type"],item["type"])
                lines.append(f"  • {t}: {item['value']} ({item['count']} פעמים)")
        else:
            lines.append(f"דפוסים קיימים: {learner.get_summary()}")
            lines.append("(צריך ≥2 מיילים מאותו מקור ללמידה חדשה)")

        _push({"type":"run_complete","message":lines[0]})
        return jsonify({"success":True,"output":"\n".join(lines),"count":len(emails)})
    except Exception as e:
        import traceback
        return jsonify({"success":False,"output":f"שגיאה: {e}\n{traceback.format_exc()}"})


# ------------------------------------------------------------------ #
#  סריקת SPAM ואינטראקציה דרך הדשבורד                                  #
# ------------------------------------------------------------------ #

@app.route("/api/spam-scan", methods=["POST"])
def spam_scan():
    try:
        sys.path.insert(0, str(Path(__file__).parent))

        client = _make_gmail_client(request)
        if not client.connect():
            return jsonify({"success": False, "error": "לא הצלחתי להתחבר"})

        reviewer   = _make_spam_reviewer(request)
        suspicious = reviewer.scan_spam_folder(client, max_results=100)

        result = []
        for email in suspicious:
            result.append({
                "id":      email.get("id"),
                "from":    email.get("from",""),
                "subject": email.get("subject",""),
                "date":    email.get("date",""),
                "snippet": email.get("snippet",""),
                "score":   email.get("_legit_score", 0),
                "reasons": email.get("_legit_reasons", []),
            })

        return jsonify({"success": True, "emails": result, "count": len(result)})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "error": str(e), "trace": traceback.format_exc()})


@app.route("/api/spam-decision", methods=["POST"])
def spam_decision():
    try:
        sys.path.insert(0, str(Path(__file__).parent))

        data      = request.json or {}
        email_id  = data.get("id")
        decision  = data.get("decision")
        email_obj = data.get("email", {})

        if not email_id or not decision:
            return jsonify({"success": False, "error": "חסרים שדות"})

        client = _make_gmail_client(request)
        if not client.connect():
            return jsonify({"success": False, "error": "לא הצלחתי להתחבר"})

        reviewer = _make_spam_reviewer(request)
        learner  = _make_learner(request)

        if decision == "moved_to_inbox":
            reviewer._move_to_inbox(client, {"id": email_id})
            learner.learn_sender_rule(
                from_addr=email_obj.get("from",""),
                subject=email_obj.get("subject",""),
                is_important=True
            )
        elif decision == "confirmed_spam":
            client.mark_as_spam(email_id)
            reviewer.add_to_blacklist(email_obj)
            learner.learn_sender_rule(
                from_addr=email_obj.get("from",""),
                subject=email_obj.get("subject",""),
                is_important=False
            )

        reviewer._log_review(email_obj, decision)
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "error": str(e), "trace": traceback.format_exc()})


# ------------------------------------------------------------------ #
#  עזר                                                                 #
# ------------------------------------------------------------------ #

def _load_jsonl(path: Path) -> list:
    if not path.exists(): return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except: pass
    return out

def _load_json(path: Path) -> dict:
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except: return {}


if __name__ == "__main__":
    print("MailCleaner Dashboard — http://localhost:5000")
    app.run(debug=False, port=5000, threaded=True)
