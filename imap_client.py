# imap_client.py — התחברות גיבוי ל-Gmail דרך IMAP
# MailCleaner Project | D:\AI_Agents\MailCleaner

import imaplib
import email
import logging
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


class IMAPClient:
    """לקוח IMAP — גיבוי כאשר Gmail API אינו זמין"""

    def __init__(self, address: str, app_password: str):
        self.address = address
        self.app_password = app_password
        self.connection = None
        self.connected = False

    # ------------------------------------------------------------------ #
    #  התחברות                                                             #
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """התחברות ל-Gmail דרך IMAP. מחזיר True אם הצליח."""
        try:
            self.connection = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            self.connection.login(self.address, self.app_password)
            self.connected = True
            logger.info("✅ IMAP: התחברות הצליחה (מצב גיבוי)")
            return True
        except imaplib.IMAP4.error as e:
            logger.error(f"❌ IMAP: שגיאת התחברות — {e}")
            logger.error("💡 ודאי שסיסמת האפליקציה נכונה ו-IMAP מופעל ב-Gmail")
            return False
        except Exception as e:
            logger.error(f"❌ IMAP: שגיאה לא צפויה — {e}")
            return False

    def disconnect(self):
        """ניתוק מהשרת."""
        if self.connection:
            try:
                self.connection.logout()
                logger.info("🔌 IMAP: נותק בהצלחה")
            except Exception:
                pass
        self.connected = False

    # ------------------------------------------------------------------ #
    #  קריאת מיילים                                                        #
    # ------------------------------------------------------------------ #

    def get_emails(self, max_results: int = 100, folder: str = "INBOX", query: str = "") -> list[dict]:
        """מחזיר רשימת מיילים מהתיבה."""
        if not self.connected:
            logger.error("לא מחובר ל-IMAP")
            return []

        try:
            self.connection.select(folder)
            _, msg_ids = self.connection.search(None, "ALL")
            all_ids = msg_ids[0].split()

            # לוקח את המיילים האחרונים
            recent_ids = all_ids[-max_results:] if len(all_ids) > max_results else all_ids
            recent_ids = list(reversed(recent_ids))  # מהחדש לישן

            emails = []
            for msg_id in recent_ids:
                email_data = self._fetch_email(msg_id)
                if email_data:
                    emails.append(email_data)

            logger.info(f"📬 IMAP: נקראו {len(emails)} מיילים")
            return emails

        except Exception as e:
            logger.error(f"❌ IMAP: שגיאה בקריאת מיילים — {e}")
            return []

    def iter_email_batches(self, query: str = "", batch_size: int = 50):
        """Yield batches of emails; query is ignored in IMAP fallback mode."""
        emails = self.get_emails(max_results=batch_size * 10)
        for i in range(0, max(len(emails), 1), batch_size):
            yield emails[i : i + batch_size]

    def _fetch_email(self, msg_id: bytes) -> Optional[dict]:
        """מחזיר פרטי מייל לפי ID."""
        try:
            _, msg_data = self.connection.fetch(msg_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = self._decode_header(msg.get("Subject", "(ללא נושא)"))
            from_addr = self._decode_header(msg.get("From", ""))
            date = msg.get("Date", "")
            body = self._extract_body(msg)

            return {
                "id": msg_id.decode(),
                "subject": subject,
                "from": from_addr,
                "date": date,
                "snippet": body[:200],
                "body": body[:2000],
                "labels": [],
                "unread": False,
            }
        except Exception as e:
            logger.warning(f"⚠️ IMAP: לא הצלחתי לקרוא מייל {msg_id}: {e}")
            return None

    def _decode_header(self, value) -> str:
        """מפענח כותרות מייל עם קידוד מיוחד."""
        try:
            parts = decode_header(str(value))
            decoded = []
            for part, encoding in parts:
                if isinstance(part, bytes):
                    decoded.append(part.decode(encoding or "utf-8", errors="ignore"))
                else:
                    decoded.append(str(part))
            return " ".join(decoded)
        except Exception:
            return str(value)

    def _extract_body(self, msg) -> str:
        """מחלץ טקסט מגוף המייל."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
                    except Exception:
                        continue
        else:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            except Exception:
                body = ""
        return body

    # ------------------------------------------------------------------ #
    #  פעולות על מיילים (מוגבלות ב-IMAP)                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode_folder_name(name: str) -> str:
        """Encode folder name to IMAP modified UTF-7 (RFC 3501)."""
        import base64
        res = bytearray()
        buf: list[str] = []

        def _flush(buf: list, res: bytearray) -> None:
            if buf:
                b64 = base64.b64encode("".join(buf).encode("utf-16-be"))
                res += b"&" + b64.replace(b"/", b",") + b"-"
                buf.clear()

        for ch in name:
            if 0x20 <= ord(ch) <= 0x7e and ch != "&":
                _flush(buf, res)
                res.append(ord(ch))
            elif ch == "&":
                _flush(buf, res)
                res += b"&-"
            else:
                buf.append(ch)
        _flush(buf, res)
        return res.decode("ascii")

    def _ensure_connected(self) -> bool:
        """בודק שהחיבור חי ומתחבר מחדש אם לא."""
        try:
            self.connection.noop()
            return True
        except Exception:
            logger.warning("⚠️ IMAP: חיבור אבד — מתחבר מחדש...")
            return self.connect()

    def move_to_folder(self, msg_id: str, folder_name: str) -> bool:
        """מעתיק מייל לתיקייה ומוחק מהמקור."""
        encoded = self._encode_folder_name(folder_name)

        for attempt in range(2):
            try:
                try:
                    self.connection.create(encoded)
                except Exception:
                    pass  # תיקייה כבר קיימת

                self.connection.select("INBOX")
                result = self.connection.copy(msg_id.encode(), encoded)
                if result[0] == "OK":
                    self.connection.store(msg_id.encode(), "+FLAGS", "\\Deleted")
                    self.connection.expunge()
                    logger.info(f"📁 IMAP: מייל {msg_id} הועבר ל-'{folder_name}'")
                    return True
                return False
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"⚠️ IMAP: שגיאת חיבור, מנסה מחדש — {e}")
                    if not self._ensure_connected():
                        break
                else:
                    logger.error(f"❌ IMAP: שגיאה בהעברה — {e}")
        return False

    def mark_as_spam(self, msg_id: str) -> bool:
        """מסמן כספאם (מעביר לתיקיית Spam)."""
        return self.move_to_folder(msg_id, "[Gmail]/Spam")

    def delete_email(self, msg_id: str) -> bool:
        """
        מוחק מייל.
        ⚠️ לא לקרוא ללא אישור מפורש מהמשתמש!
        """
        try:
            self.connection.select("INBOX")
            self.connection.store(msg_id.encode(), "+FLAGS", "\\Deleted")
            self.connection.expunge()
            logger.info(f"🗑️ IMAP: מייל {msg_id} נמחק")
            return True
        except Exception as e:
            logger.error(f"❌ IMAP: שגיאה במחיקה — {e}")
            return False
