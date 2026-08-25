"""通过 SMTP 发送通知，并通过 IMAP 轮询精确控制命令。"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.policy import default
from email.utils import parseaddr
from pathlib import Path

from automm.common import ROOT, read_json, read_yaml, utc_now, write_json, write_yaml
from automm.problems import question_manifest
from automm.state import apply_control, load_state, save_state

EMAIL_DIR = ROOT / "runtime" / "email"


def config() -> dict:
    override = os.getenv("AUTOMM_NOTIFICATIONS_CONFIG")
    return read_yaml(Path(override).expanduser().resolve() if override else ROOT / "config" / "notifications.yaml")


def password(cfg: dict) -> str:
    return os.getenv(cfg.get("password_env", "AUTOMM_SMTP_PASSWORD"), "") or cfg.get("password", "")


def require_fields(cfg: dict, fields: tuple[str, ...]) -> None:
    missing = [name for name in fields if not cfg.get(name)]
    if missing:
        raise SystemExit(f"邮件配置缺少：{', '.join(missing)}")


def send(args: argparse.Namespace) -> None:
    cfg = config()
    manifest_path = None
    manifest = None
    if args.kind == "question-complete" and args.problem_id and args.question_id:
        manifest_path, manifest = question_manifest(args.problem_id, args.question_id)
        manifest.setdefault("notification", {})["attempts"] = (
            int(manifest.get("notification", {}).get("attempts", 0)) + 1
        )
        write_yaml(manifest_path, manifest)
    if not cfg.get("enabled"):
        if manifest is not None:
            manifest["notification"]["status"] = "skipped_disabled"
            write_yaml(manifest_path, manifest)
            if int(manifest["notification"]["attempts"]) == 3:
                state = load_state()
                state.setdefault("warnings", []).append(f"{args.question_id} 完成通知因邮件未启用而跳过")
                save_state(
                    state,
                    event="question_notification_skipped",
                    details={"problem_id": args.problem_id, "question_id": args.question_id},
                )
        print("SKIPPED_DISABLED: config/notifications.yaml 未启用")
        return
    require_fields(cfg, ("smtp_host", "username", "from", "to"))
    secret = password(cfg)
    if not secret:
        raise SystemExit("邮件密码为空；请填写 password 或 password_env 对应环境变量")
    request_id = args.request_id or uuid.uuid4().hex[:16]
    subject_kind = args.kind.upper().replace("-", "_")
    message = EmailMessage()
    message["Subject"] = f"[AutoMM][{subject_kind}][{request_id}]"
    message["From"] = cfg["from"]
    message["To"] = cfg["to"]
    message.set_content(args.message)
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for _ in range(max(1, int(cfg.get("retry_attempts", 3)))):
        try:
            with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port", 587)), timeout=30) as client:
                if cfg.get("smtp_use_tls", True):
                    client.starttls(context=context)
                client.login(cfg["username"], secret)
                client.send_message(message)
            last_error = None
            break
        except (OSError, smtplib.SMTPException) as exc:
            last_error = exc
    if last_error is not None:
        raise RuntimeError(f"SMTP 发送失败：{last_error}") from last_error
    record = {
        "request_id": request_id,
        "kind": args.kind,
        "sent_at": utc_now(),
        "problem_id": args.problem_id,
        "question_id": args.question_id,
    }
    EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    write_json(EMAIL_DIR / "requests" / f"{request_id}.json", record)
    if manifest is not None:
        manifest["notification"]["sent"] = True
        manifest["notification"]["status"] = "sent"
        manifest["notification"]["sent_at"] = utc_now()
        write_yaml(manifest_path, manifest)
    print(json.dumps(record, ensure_ascii=False, indent=2))


def message_text(message: email.message.EmailMessage) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                return part.get_content()
        return ""
    return message.get_content()


def process_command(raw: str, sender: str, message_id: str) -> dict:
    parts = raw.strip().split()
    control = {"PAUSE", "STOP", "RESUME"}
    if len(parts) == 1 and parts[0].upper() in control:
        command = parts[0].upper()
        apply_control(command, source=f"email:{sender}")
        return {"message_id": message_id, "command": command, "status": "applied"}
    return {"message_id": message_id, "status": "ignored_invalid_exact_command"}


def poll() -> None:
    cfg = config()
    if not cfg.get("enabled"):
        print("SKIPPED_DISABLED: config/notifications.yaml 未启用")
        return
    require_fields(cfg, ("imap_host", "username"))
    secret = password(cfg)
    if not secret:
        raise SystemExit("邮件密码为空；请填写 password 或 password_env 对应环境变量")
    processed_path = ROOT / cfg.get("processed_messages_file", "runtime/email/processed_messages.json")
    processed = read_json(processed_path, default={"message_ids": []})
    known = set(processed.get("message_ids", []))
    allowed = {item.lower() for item in cfg.get("allowed_senders", [])}
    if not allowed:
        raise SystemExit("邮件启用时 allowed_senders 不能为空")
    results = []
    client_type = imaplib.IMAP4_SSL if cfg.get("imap_use_ssl", True) else imaplib.IMAP4
    with client_type(cfg["imap_host"], int(cfg.get("imap_port", 993))) as client:
        client.login(cfg["username"], secret)
        client.select("INBOX")
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("IMAP 搜索失败")
        for uid in data[0].split():
            uid_text = uid.decode("ascii")
            if uid_text in known:
                continue
            status, fetched = client.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            message = email.message_from_bytes(fetched[0][1], policy=default)
            sender = parseaddr(message.get("From", ""))[1].lower()
            if allowed and sender not in allowed:
                result = {"message_id": uid_text, "status": "ignored_sender", "sender": sender}
            else:
                result = process_command(message_text(message), sender, uid_text)
            results.append(result)
            known.add(uid_text)
    write_json(processed_path, {"updated_at": utc_now(), "message_ids": sorted(known)})
    print(json.dumps(results, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoMM 邮件通知与控制")
    sub = parser.add_subparsers(dest="action", required=True)
    sender = sub.add_parser("send")
    sender.add_argument("--kind", choices=("question-complete", "problem-complete"), required=True)
    sender.add_argument("--message", required=True)
    sender.add_argument("--problem-id")
    sender.add_argument("--question-id")
    sender.add_argument("--request-id")
    sub.add_parser("poll")
    args = parser.parse_args()
    send(args) if args.action == "send" else poll()


if __name__ == "__main__":
    main()
