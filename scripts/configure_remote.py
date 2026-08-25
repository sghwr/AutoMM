"""AutoMM 远端计算 + 邮件 一键配置脚本（单文件，非侵入式）。

只写三个用户配置：config/ssh.yaml、config/notifications.yaml、config/compute.yaml。
不修改 scripts/automm 下任何 harness 逻辑（Python 代码）。写盘前自动备份，可反复运行。

用法（项目根目录、用项目 venv 的 python 运行）：
    python scripts/configure_remote.py                # 交互式配置，结束后可选连接探测
    python scripts/configure_remote.py show           # 只读：打印当前三项配置（脱敏）
    python scripts/configure_remote.py --skip-probe   # 只写配置，不做任何网络探测
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("缺少 PyYAML。请用项目 venv 运行，例如：", file=sys.stderr)
    print("  <venv>\\Scripts\\python.exe scripts\\configure_remote.py", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
SSH_YAML = ROOT / "config" / "ssh.yaml"
NOTIFY_YAML = ROOT / "config" / "notifications.yaml"
COMPUTE_YAML = ROOT / "config" / "compute.yaml"

DEFAULT_IMPORTS = ["numpy", "pandas", "scipy", "openpyxl", "yaml"]
SECRET_KEYS = {"password", "auth_token", "smtp_auth_code", "authorization_code", "api_key", "token"}


# ---------- 基础工具 ----------

def read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = path.with_name(path.name + f".bak.{stamp}")
    shutil.copy2(path, target)
    print(f"    [备份] {path.name} -> {target.name}")


def ask(prompt: str, default: object = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    if secret:
        value = getpass.getpass(f"{prompt}{suffix}: ").strip()
    else:
        value = input(f"{prompt}{suffix}: ").strip()
    return "" if default is None and value == "" else (str(default) if value == "" else value)


def ask_bool(prompt: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    value = input(f"{prompt} (y/n) [{d}]: ").strip().lower()
    return default if value == "" else value in {"y", "yes", "1", "true"}


def redact(data: object) -> object:
    if isinstance(data, dict):
        return {k: ("<redacted>" if str(k).lower() in SECRET_KEYS else redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


# ---------- 探测 ----------

def probe_ssh(host: str, port: int, username: str, password: str, remote_python: str) -> dict:
    try:
        import paramiko
    except ImportError:
        return {"ok": False, "error": "缺少 paramiko，请先安装 scripts/requirements.txt"}
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    result: dict = {"ok": False}
    try:
        client.connect(host, port=int(port), username=username, password=password,
                       timeout=20, banner_timeout=20, auth_timeout=20, look_for_keys=False, allow_agent=False)
        key = client.get_transport().get_remote_server_key()
        result["host_key_sha256"] = hashlib.sha256(key.asbytes()).hexdigest()
        _i, out, err = client.exec_command(f"{shlex.quote(remote_python)} --version", timeout=20)
        out.channel.recv_exit_status()
        result["python_version"] = (out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")).strip()
        probe_code = "".join(f"import {m};" for m in DEFAULT_IMPORTS) + 'print("imports_ok")'
        _i2, out2, err2 = client.exec_command(f"{shlex.quote(remote_python)} -c {shlex.quote(probe_code)}", timeout=30)
        out2.channel.recv_exit_status()
        result["imports_ok"] = "imports_ok" in out2.read().decode("utf-8", "replace")
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        client.close()
    return result


def probe_smtp(cfg: dict) -> dict:
    import smtplib
    import ssl
    try:
        with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port", 587)), timeout=30) as c:
            if cfg.get("smtp_use_tls", True):
                c.starttls(context=ssl.create_default_context())
            c.login(cfg["username"], cfg["password"])
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def probe_imap(cfg: dict) -> dict:
    import imaplib
    try:
        cls = imaplib.IMAP4_SSL if cfg.get("imap_use_ssl", True) else imaplib.IMAP4
        with cls(cfg["imap_host"], int(cfg.get("imap_port", 993))) as c:
            c.login(cfg["username"], cfg["password"])
            c.select("INBOX")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------- 三个配置段 ----------

def configure_ssh() -> dict:
    print("\n=== 1/3 SSH 远端计算 ===")
    cur = read_yaml(SSH_YAML)
    host = ask("SSH host", cur.get("host", ""))
    port = int(ask("SSH port", cur.get("port", 22)))
    username = ask("SSH username", cur.get("username", "root"))
    password = ask("SSH 密码（明文写入 ssh.yaml，注意安全）", cur.get("password", ""), secret=True)
    remote_root = ask("远端工作目录（相对 home）", cur.get("remote_root", "automm/"))
    data = read_yaml(SSH_YAML)
    data.update({
        "enabled": True,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "password_env": "AUTOMM_SSH_PASSWORD",
        "remote_root": remote_root,
        "host_key_sha256": cur.get("host_key_sha256", ""),
        "connect_timeout_seconds": int(cur.get("connect_timeout_seconds", 20)),
    })
    backup(SSH_YAML)
    write_yaml(SSH_YAML, data)
    print(f"    已写入 {SSH_YAML.relative_to(ROOT)}")
    return {"host": host, "port": port, "username": username, "password": password}


def configure_email() -> dict:
    print("\n=== 2/3 QQ 邮箱通知 ===")
    cur = read_yaml(NOTIFY_YAML)
    enable = ask_bool("启用邮件通知", default=bool(cur.get("enabled", False)))
    username = ask("QQ 邮箱地址（完整，如 123456@qq.com）", cur.get("username", ""))
    password = ask("QQ 授权码（不是登录密码）", cur.get("password", ""), secret=True)
    smtp_host = ask("SMTP host", cur.get("smtp_host", "smtp.qq.com"))
    smtp_port = int(ask("SMTP port", cur.get("smtp_port", 587)))
    imap_host = ask("IMAP host", cur.get("imap_host", "imap.qq.com"))
    imap_port = int(ask("IMAP port", cur.get("imap_port", 993)))
    from_addr = ask("发件人（通常同 QQ 邮箱）", cur.get("from", username))
    to_addr = ask("收件人", cur.get("to", ""))
    allowed = ask("允许发控制命令的邮箱（逗号分隔）", ",".join(cur.get("allowed_senders", [])))
    data = read_yaml(NOTIFY_YAML)
    data.update({
        "enabled": enable,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_use_tls": True,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "imap_use_ssl": True,
        "username": username,
        "password": password,
        "password_env": "AUTOMM_SMTP_PASSWORD",
        "from": from_addr,
        "to": to_addr,
        "allowed_senders": [s.strip() for s in allowed.split(",") if s.strip()],
    })
    backup(NOTIFY_YAML)
    write_yaml(NOTIFY_YAML, data)
    print(f"    已写入 {NOTIFY_YAML.relative_to(ROOT)}")
    return {"enabled": enable, "username": username, "password": password,
            "smtp_host": smtp_host, "smtp_port": smtp_port, "smtp_use_tls": True,
            "imap_host": imap_host, "imap_port": imap_port, "imap_use_ssl": True}


def configure_compute(mode: str) -> dict:
    print("\n=== 3/3 计算后端 ===")
    data = read_yaml(COMPUTE_YAML)
    backend = "ssh" if mode == "remote" else "local"
    data["default_backend"] = backend
    backup(COMPUTE_YAML)
    write_yaml(COMPUTE_YAML, data)
    print(f"    已写入 {COMPUTE_YAML.relative_to(ROOT)}（default_backend={backend}）")
    return {"default_backend": backend}


# ---------- show / main ----------

def show() -> None:
    for path in (SSH_YAML, NOTIFY_YAML, COMPUTE_YAML):
        print(f"\n----- {path.relative_to(ROOT)} -----")
        if not path.exists():
            print("  (不存在)")
            continue
        print(yaml.safe_dump(redact(read_yaml(path)), allow_unicode=True, sort_keys=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoMM 远端计算 + 邮件 一键配置（非侵入式）")
    parser.add_argument("action", nargs="?", choices=("configure", "show"), default="configure")
    parser.add_argument("--skip-probe", action="store_true", help="只写配置，不做网络探测")
    args = parser.parse_args()

    if args.action == "show":
        show()
        return 0

    print("AutoMM 远端计算 + 邮件配置向导")
    print("提示：回车使用方括号里的默认值；密码/授权码不会回显；写盘前自动备份。\n")

    print("请先选择计算模式：")
    print("  local  —— 所有计算在本地跑（本地压力大）")
    print("  remote —— 重计算走远端 SSH，本地只做编排 + 轻量 smoke（推荐用于全量）")
    mode = ask("计算模式 (local/remote)", "local")
    mode = "remote" if mode.lower() in {"remote", "r", "ssh"} else "local"

    ssh: dict = {}
    if mode == "remote":
        ssh = configure_ssh()
    else:
        print("\n=== 1/3 SSH 远端计算（local 模式，跳过）===")

    email = configure_email()
    compute = configure_compute(mode)

    print("\n" + "=" * 50)
    print(f"配置已写入：计算模式 = {mode}（default_backend={compute['default_backend']}）")
    if mode == "remote":
        print("重计算将走远端 SSH；本地只做编排 + 轻量 smoke。")

    if args.skip_probe:
        print("已跳过网络探测。")
        return 0

    do_probe = ask_bool("\n是否现在探测连接？", default=(mode == "remote"))
    if not do_probe:
        return 0

    if mode == "remote":
        print("\n--- SSH 探测 ---")
        r = probe_ssh(ssh["host"], ssh["port"], ssh["username"], ssh["password"], "python3")
        if r.get("ok"):
            print(f"  OK  python={r.get('python_version')}  imports_ok={r.get('imports_ok')}")
            print(f"  主机指纹 sha256 = {r['host_key_sha256']}")
            stored = read_yaml(SSH_YAML).get("host_key_sha256", "")
            if not stored:
                if ask_bool("是否把该指纹写入 ssh.yaml 以启用校验（推荐）", default=True):
                    data = read_yaml(SSH_YAML)
                    data["host_key_sha256"] = r["host_key_sha256"]
                    write_yaml(SSH_YAML, data)
                    print("    已写入 host_key_sha256")
            elif stored != r["host_key_sha256"]:
                print(f"  ⚠ 警告：指纹与已存值不一致！已存 {stored[:16]}…，实际 {r['host_key_sha256'][:16]}…")
        else:
            print(f"  FAIL {r.get('error')}")
    else:
        print("\nlocal 模式，跳过 SSH 探测。")

    if email["enabled"]:
        print("\n--- SMTP 探测 ---")
        r = probe_smtp(email)
        print(f"  {'OK' if r.get('ok') else 'FAIL ' + str(r.get('error'))}")
        print("--- IMAP 探测 ---")
        r = probe_imap(email)
        print(f"  {'OK' if r.get('ok') else 'FAIL ' + str(r.get('error'))}")
    else:
        print("\n邮件已禁用，跳过 SMTP/IMAP 探测。")

    print("\n完成。下一步：")
    if mode == "remote":
        print("  1) python scripts/sync_remote.py --backend ssh probe   # 复测 SSH")
    print("  2) python scripts/notify_email.py send --kind question-complete --message test --problem-id x --question-id p01")
    print("  3) 确认远端计算路由后即可跑全量 smoke")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)