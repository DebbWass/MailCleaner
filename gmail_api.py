# gmail_api.py — התחברות וניהול Gmail דרך Gmail API
# MailCleaner Project | D:\AI_Agents\MailCleaner
#
# אופטימיזציות:
# 1. Batch API  — עד 100 בקשות ב-HTTP אחד
# 2. metadata   — טוענים רק כותרות בשלב ראשון
# 3. lazy body  — גוף נטען רק כשצריך
# 4. label cache — מונע קריאות כפולות לרשימת תיקיות

import base64
import logging
import time
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

BASE_DIR         = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE       = BASE_DIR / "token.json"

# Gmail מאפשר batch אבל מגביל concurrent requests —
# 10 בקשות לבאצ' + המתנה קצרה בין באצ'ים = אמין + מהיר
BATCH_HTTP_SIZE  = 10
BATCH_DELAY_SEC  = 0.5   # המתנה בין באצ'ים למניעת 429
MAX_RETRIES      = 3     # ניסיונות חוזרים על כשל


class GmailAPIClient:

    def __init__(self, token_file=None):
        self.service   = None
        self.connected = False
        self._label_cache: dict[str, str] = {}
        self._token_file = Path(token_file) if token_file else TOKEN_FILE

    # ------------------------------------------------------------------ #
    #  התחברות                                                             #
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        try:
            creds = self._load_or_refresh_credentials()
            self.service = build("gmail", "v1", credentials=creds)
            self.connected = True
            logger.info("Gmail API: התחברות הצליחה")
            return True
        except FileNotFoundError:
            logger.error("credentials.json לא נמצא — הורד מ-Google Cloud Console")
            return False
        except Exception as e:
            # הדפס את הסיבה המלאה כדי לעזור באבחון
            logger.error(f"Gmail API נכשל: {type(e).__name__}: {e}")
            if "token" in str(e).lower() or "expired" in str(e).lower() or "invalid" in str(e).lower():
                logger.error("נראה שהטוקן פג תוקף — מחק את token.json והרץ מחדש")
            return False

    def _load_or_refresh_credentials(self) -> Credentials:
        creds = None
        if self._token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_FILE.exists():
                    raise FileNotFoundError(f"credentials.json לא נמצא ב-{BASE_DIR}")
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._token_file, "w") as f:
                f.write(creds.to_json())
        return creds

    # ------------------------------------------------------------------ #
    #  קריאת מיילים — Batch + Metadata                                     #
    # ------------------------------------------------------------------ #

    def get_emails(self, max_results: int = 100, query: str = "") -> list[dict]:
        """
        מחזיר עד max_results מיילים.
        max_results=-1 = כל המיילים בתיבה (ללא הגבלה).
        """
        if not self.connected:
            return []

        ids = list(self._iter_all_ids(query, limit=max_results))
        if not ids:
            return []
        logger.info(f"נמצאו {len(ids)} מיילים — טוען metadata...")
        return self._batch_fetch_metadata(ids)

    def iter_email_batches(self, query: str = "", batch_size: int = 50):
        """
        Generator — מחזיר באצ'ים של מיילים עד שגמרו הכל.
        משמש לסריקת כל התיבה ללא הגבלה.

        שימוש:
            for batch in client.iter_email_batches(query="in:inbox"):
                process(batch)
        """
        if not self.connected:
            return

        id_buffer = []
        for msg_id in self._iter_all_ids(query, limit=-1):
            id_buffer.append(msg_id)
            if len(id_buffer) >= batch_size:
                yield self._batch_fetch_metadata(id_buffer)
                id_buffer.clear()
                time.sleep(BATCH_DELAY_SEC)   # נשימה בין באצ'ים

        # שארית
        if id_buffer:
            yield self._batch_fetch_metadata(id_buffer)

    def _iter_all_ids(self, query: str = "", limit: int = -1):
        """
        Generator — מחזיר IDs של מיילים עמוד אחרי עמוד.
        limit=-1 = ללא הגבלה.
        """
        page_token = None
        fetched    = 0

        while True:
            remaining  = (limit - fetched) if limit > 0 else 500
            fetch_now  = min(500, remaining) if limit > 0 else 500
            if fetch_now <= 0:
                break

            params = {
                "userId":     "me",
                "maxResults": fetch_now,
                "q":          query,
                "fields":     "messages/id,nextPageToken",
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                result     = self.service.users().messages().list(**params).execute()
            except HttpError as e:
                logger.error(f"שגיאה בקריאת IDs: {e}")
                break

            for msg in result.get("messages", []):
                yield msg["id"]
                fetched += 1
                if limit > 0 and fetched >= limit:
                    return

            page_token = result.get("nextPageToken")
            if not page_token:
                break   # אין עמוד נוסף — סיימנו


    def _batch_fetch_metadata(self, msg_ids: list[str]) -> list[dict]:
        """
        טוען כותרות בבאצ'ים קטנים עם המתנה בין כל באצ'.
        BATCH_HTTP_SIZE=10 + BATCH_DELAY_SEC=0.5 → אמין, ללא 429.
        """
        results: dict[str, dict] = {}

        def _callback(request_id, response, exception):
            if exception:
                # 429 — לא נורא, המייל ייכשל בשקט ויידלג
                if hasattr(exception, 'status_code') and exception.status_code == 429:
                    logger.debug(f"Rate limit על {request_id} — ידולג")
                else:
                    logger.warning(f"מייל {request_id}: {exception}")
                return
            try:
                headers = {h["name"]: h["value"]
                           for h in response.get("payload", {}).get("headers", [])}
                label_ids = response.get("labelIds", [])
                results[request_id] = {
                    "id":      request_id,
                    "subject": headers.get("Subject", "(ללא נושא)"),
                    "from":    headers.get("From", ""),
                    "date":    headers.get("Date", ""),
                    "snippet": response.get("snippet", ""),
                    "labels":  label_ids,
                    "unread":  "UNREAD" in label_ids,
                    "body":    None,
                }
            except Exception as ex:
                logger.warning(f"שגיאה בעיבוד {request_id}: {ex}")

        total = len(msg_ids)
        for i in range(0, total, BATCH_HTTP_SIZE):
            chunk = msg_ids[i: i + BATCH_HTTP_SIZE]
            chunk_num = (i // BATCH_HTTP_SIZE) + 1
            total_chunks = (total + BATCH_HTTP_SIZE - 1) // BATCH_HTTP_SIZE

            # ניסיונות חוזרים על כשל
            for attempt in range(MAX_RETRIES):
                try:
                    batch = self.service.new_batch_http_request(callback=_callback)
                    for mid in chunk:
                        batch.add(
                            self.service.users().messages().get(
                                userId="me",
                                id=mid,
                                format="metadata",
                                metadataHeaders=["From", "Subject", "Date"],
                                fields="id,snippet,labelIds,payload/headers"
                            ),
                            request_id=mid
                        )
                    batch.execute()
                    logger.debug(f"באצ' {chunk_num}/{total_chunks} הושלם ({len(chunk)} מיילים)")
                    break  # הצליח — צא מלולאת הניסיונות
                except HttpError as e:
                    if e.status_code == 429:
                        wait = (attempt + 1) * 2  # המתן 2, 4, 6 שניות
                        logger.warning(f"429 על באצ' {chunk_num} — ממתין {wait}ש' (ניסיון {attempt+1})")
                        time.sleep(wait)
                    else:
                        logger.error(f"שגיאת API בבאצ' {chunk_num}: {e}")
                        break
                except Exception as e:
                    logger.error(f"שגיאה בבאצ' {chunk_num}: {e}")
                    break

            # המתנה קצרה בין כל באצ' — מונע 429
            if i + BATCH_HTTP_SIZE < total:
                time.sleep(BATCH_DELAY_SEC)

        # שמור סדר מקורי
        return [results[mid] for mid in msg_ids if mid in results]

    def get_body(self, email: dict) -> str:
        """
        Lazy loading — טוען גוף מייל רק כשנחוץ לסיווג.
        (unsubscribe, spam keywords בגוף וכו')
        """
        if email.get("body") is not None:
            return email["body"]
        try:
            msg = self.service.users().messages().get(
                userId="me", id=email["id"], format="full",
                fields="payload"
            ).execute()
            body = self._extract_body(msg["payload"])
            email["body"] = body
            return body
        except Exception as e:
            logger.warning(f"שגיאה בטעינת גוף {email['id']}: {e}")
            email["body"] = ""
            return ""

    def _extract_body(self, payload: dict) -> str:
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    if data:
                        body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        break
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return body[:2000]

    # ------------------------------------------------------------------ #
    #  פעולות — Batch לביצועים                                             #
    # ------------------------------------------------------------------ #

    def move_to_label(self, msg_id: str, label_name: str) -> bool:
        try:
            label_id = self._get_or_create_label(label_name)
            self.service.users().messages().modify(
                userId="me", id=msg_id,
                body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]}
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"שגיאה בהעברה: {e}")
            return False

    def batch_move_to_label_from(self, msg_ids: list[str], label_name: str,
                                  source_folders: list[str]) -> int:
        """
        מעביר מיילים לתיקייה ומסיר אותם מתיקיות המקור.
        פותר בעיה: מיילים שלא ב-INBOX לא נמחקו מהתיקייה המקורית.
        """
        if not msg_ids:
            return 0

        target_id    = self._get_or_create_label(label_name)
        # בנה רשימת label IDs להסרה: INBOX + תיקיות המקור
        remove_ids   = ["INBOX"]
        for folder in (source_folders or []):
            folder_up = folder.upper()
            if folder_up in ("INBOX","SPAM","SENT","TRASH","STARRED","IMPORTANT"):
                remove_ids.append(folder_up)
            else:
                # תיקיית משתמש — מצא את ה-ID שלה
                if folder in self._label_cache:
                    remove_ids.append(self._label_cache[folder])
                else:
                    # נסה לטעון
                    for lbl in self.get_labels():
                        if lbl["name"] == folder or lbl["id"] == folder:
                            remove_ids.append(lbl["id"])
                            break

        remove_ids = list(set(remove_ids))   # ללא כפילויות
        success    = 0

        def _cb(req_id, response, exception):
            nonlocal success
            if not exception:
                success += 1

        for i in range(0, len(msg_ids), BATCH_HTTP_SIZE):
            chunk = msg_ids[i: i + BATCH_HTTP_SIZE]
            for attempt in range(MAX_RETRIES):
                try:
                    batch = self.service.new_batch_http_request(callback=_cb)
                    for mid in chunk:
                        batch.add(
                            self.service.users().messages().modify(
                                userId="me", id=mid,
                                body={"addLabelIds": [target_id],
                                      "removeLabelIds": remove_ids}
                            ),
                            request_id=mid
                        )
                    batch.execute()
                    break
                except HttpError as e:
                    if e.status_code == 429:
                        time.sleep((attempt + 1) * 2)
                    else:
                        break
            if i + BATCH_HTTP_SIZE < len(msg_ids):
                time.sleep(BATCH_DELAY_SEC)

        logger.info(f"batch_move_from {source_folders}: {success}/{len(msg_ids)} → '{label_name}'")
        return success

    def batch_move_to_label(self, msg_ids: list[str], label_name: str) -> int:
        """מעביר מיילים לתיקייה בבאצ'ים עם rate limiting."""
        if not msg_ids:
            return 0
        label_id = self._get_or_create_label(label_name)
        success = 0

        def _cb(req_id, response, exception):
            nonlocal success
            if not exception:
                success += 1

        for i in range(0, len(msg_ids), BATCH_HTTP_SIZE):
            chunk = msg_ids[i: i + BATCH_HTTP_SIZE]
            for attempt in range(MAX_RETRIES):
                try:
                    batch = self.service.new_batch_http_request(callback=_cb)
                    for mid in chunk:
                        batch.add(
                            self.service.users().messages().modify(
                                userId="me", id=mid,
                                body={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]}
                            ),
                            request_id=mid
                        )
                    batch.execute()
                    break
                except HttpError as e:
                    if e.status_code == 429:
                        time.sleep((attempt + 1) * 2)
                    else:
                        break

            if i + BATCH_HTTP_SIZE < len(msg_ids):
                time.sleep(BATCH_DELAY_SEC)

        logger.info(f"Batch move: {success}/{len(msg_ids)} → '{label_name}'")
        return success

    def mark_as_spam(self, msg_id: str) -> bool:
        try:
            self.service.users().messages().modify(
                userId="me", id=msg_id,
                body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"שגיאה בסימון ספאם: {e}")
            return False

    def delete_email(self, msg_id: str) -> bool:
        """⚠️ לא לקרוא ללא אישור מפורש מהמשתמש!"""
        try:
            self.service.users().messages().trash(userId="me", id=msg_id).execute()
            return True
        except HttpError as e:
            logger.error(f"שגיאה במחיקה: {e}")
            return False

    def mark_as_read(self, msg_id: str) -> bool:
        try:
            self.service.users().messages().modify(
                userId="me", id=msg_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"שגיאה בסימון כנקרא: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Labels — עם cache                                                   #
    # ------------------------------------------------------------------ #

    def _get_or_create_label(self, label_name: str) -> str:
        if label_name in self._label_cache:
            return self._label_cache[label_name]
        try:
            result = self.service.users().labels().list(userId="me").execute()
            for label in result.get("labels", []):
                self._label_cache[label["name"]] = label["id"]
            if label_name in self._label_cache:
                return self._label_cache[label_name]
            new_label = self.service.users().labels().create(
                userId="me",
                body={"name": label_name, "labelListVisibility": "labelShow"}
            ).execute()
            self._label_cache[label_name] = new_label["id"]
            logger.info(f"תיקייה חדשה: '{label_name}'")
            return new_label["id"]
        except HttpError as e:
            logger.error(f"שגיאה בניהול labels: {e}")
            raise

    def get_labels(self) -> list[dict]:
        try:
            result = self.service.users().labels().list(userId="me").execute()
            labels = result.get("labels", [])
            for l in labels:
                self._label_cache[l["name"]] = l["id"]
            return labels
        except HttpError as e:
            logger.error(f"שגיאה בקריאת labels: {e}")
            return []

    def get_profile(self) -> dict:
        try:
            return self.service.users().getProfile(userId="me").execute()
        except HttpError as e:
            return {}
