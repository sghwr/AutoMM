"""基于 Paramiko 的 SSH 计算适配器。"""

from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from ..common import ROOT, RUNTIME_DIR, read_yaml, resolve_project_path
from .base import AdapterError, RemoteAdapter, secret_value
from .bundle import prepare_bundle, safe_extract_zip

# Windows 远端控制脚本：放在任务包里随 SFTP 上传，用 powershell -File 调用，
# 避免在 cmd/PowerShell 默认 shell 里做复杂的 $变量内联转义。
WINDOWS_LAUNCH_PS1 = r"""param(
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [Parameter(Mandatory = $true)]
    [string]$TaskName
)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$inner = "Set-Location -LiteralPath '$dir'; & '$Python' 'runner.py'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$inner`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
$TaskName
"""

WINDOWS_CHECK_PS1 = r"""param(
    [Parameter(Mandatory = $true)]
    [int]$Pid
)
if (Get-Process -Id $Pid -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }
"""

WINDOWS_CANCEL_PS1 = r"""param(
    [Parameter(Mandatory = $true)]
    [string]$TaskName
)
schtasks /End /TN $TaskName /F 2>$null | Out-Null
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
"""


class SSHAdapter(RemoteAdapter):
    backend = "ssh"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or read_yaml(ROOT / "config" / "ssh.yaml")
        if not self.config.get("enabled", False):
            raise AdapterError("SSH 适配器未启用")

    def _is_windows(self) -> bool:
        return str(self.config.get("platform", "") or "").strip().lower() in {"windows", "win", "nt", "windows_native"}

    @staticmethod
    def _win_cmd_quote(value: str) -> str:
        text = str(value)
        if any(ch.isspace() for ch in text) or '"' in text:
            return '"' + text.replace('"', '\\"') + '"'
        return text

    def _client(self):
        try:
            import paramiko
        except ImportError as exc:
            raise AdapterError("未安装 Paramiko，请安装 scripts/requirements.txt") from exc
        host = str(self.config.get("host", "")).strip()
        username = str(self.config.get("username", "")).strip()
        if not host or not username:
            raise AdapterError("SSH host 和 username 不能为空")
        known_hosts = RUNTIME_DIR / "remote" / "ssh_known_hosts"
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if known_hosts.exists():
            client.load_host_keys(str(known_hosts))
        expected_fingerprint = str(self.config.get("host_key_sha256", "") or "").strip().lower()

        class FingerprintPolicy(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, ssh_client, hostname, key):  # noqa: ANN001
                actual = hashlib.sha256(key.asbytes()).hexdigest().lower()
                if expected_fingerprint and actual != expected_fingerprint:
                    raise AdapterError("SSH 主机指纹与配置不匹配")
                ssh_client._host_keys.add(hostname, key.get_name(), key)

        if expected_fingerprint or not known_hosts.exists():
            client.set_missing_host_key_policy(FingerprintPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        password = secret_value(self.config, "password", "password_env") or None
        key = secret_value(self.config, "private_key_path", "private_key_env") or None
        kwargs: dict[str, Any] = {
            "hostname": host,
            "port": int(self.config.get("port", 22)),
            "username": username,
            "password": password,
            "timeout": int(self.config.get("connect_timeout_seconds", 20)),
            "banner_timeout": int(self.config.get("connect_timeout_seconds", 20)),
            "auth_timeout": int(self.config.get("connect_timeout_seconds", 20)),
            "look_for_keys": not bool(password or key),
            "allow_agent": not bool(password or key),
        }
        if key:
            key_path = Path(key).expanduser()
            if not key_path.exists():
                raise AdapterError("SSH 私钥路径不存在")
            kwargs["key_filename"] = str(key_path)
        try:
            client.connect(**kwargs)
            client.save_host_keys(str(known_hosts))
            return client
        except Exception as exc:
            client.close()
            raise AdapterError(f"SSH 连接或认证失败: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _exec(client: Any, command: str, timeout: int = 60) -> tuple[int, str, str]:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        return code, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")

    def _python_command(self, client: Any) -> str:
        configured = str(self.config.get("remote_python", "") or "").strip()
        if configured:
            return configured
        if self._is_windows():
            return self._windows_python_command(client)
        code, stdout, stderr = SSHAdapter._exec(
            client,
            "for candidate in python3 python python.exe /root/miniconda3/bin/python "
            "/opt/conda/bin/python; do "
            'if command -v "$candidate" >/dev/null 2>&1; then command -v "$candidate"; exit 0; fi; '
            'if [ -x "$candidate" ]; then printf \'%s\\n\' "$candidate"; exit 0; fi; '
            "done; exit 127",
            timeout=20,
        )
        if code != 0 or not stdout.strip():
            raise AdapterError(f"SSH 远端没有可用 Python: {(stderr or stdout).strip()[-500:]}")
        return stdout.strip().splitlines()[-1]

    def _windows_python_command(self, client: Any) -> str:
        commands = [
            'py -3 -c "import sys; print(sys.executable)"',
            "where.exe python",
        ]
        for command in commands:
            code, stdout, stderr = self._exec(client, command, timeout=20)
            if code != 0 or not stdout.strip():
                continue
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            if not lines:
                continue
            if command.startswith("py "):
                return lines[-1]
            for line in lines:
                if "WindowsApps" not in line:
                    return line
            return lines[-1]
        raise AdapterError("SSH 远端没有可用 Windows Python（需要 py 启动器或 python.exe）")

    def _remote_dir(self, spec: dict[str, Any]) -> str:
        raw_root = str(self.config.get("remote_root", "automm/")).strip()
        root = raw_root.replace("\\", "/").strip("/")
        attempt = int(spec.get("attempt", 1))
        return str(PurePosixPath(root) / "tasks" / spec["task_id"] / f"attempt-{attempt:03d}")

    @classmethod
    def _mkdirs(cls, sftp: Any, path: str) -> None:
        current = PurePosixPath(".")
        for part in PurePosixPath(path.replace("\\", "/")).parts:
            if part in {"", "."}:
                continue
            # Windows 盘符（如 D:）不是需要创建的目录，直接作为路径前缀保留。
            if re.match(r"^[A-Za-z]:$", part):
                current = PurePosixPath(part)
                continue
            current /= part
            try:
                sftp.stat(str(current))
            except OSError:
                sftp.mkdir(str(current))

    @classmethod
    def _upload_tree(cls, sftp: Any, source: Path, target: str) -> None:
        cls._mkdirs(sftp, target)
        for item in source.rglob("*"):
            relative = item.relative_to(source).as_posix()
            remote = str(PurePosixPath(target) / relative)
            if item.is_dir():
                cls._mkdirs(sftp, remote)
            else:
                cls._mkdirs(sftp, str(PurePosixPath(remote).parent))
                sftp.put(str(item), remote)

    def probe(self) -> dict[str, Any]:
        with self._client() as client:
            python_command = self._python_command(client)
            if self._is_windows():
                command = f"{self._win_cmd_quote(python_command)} --version && cmd /c cd"
            else:
                command = f"{shlex.quote(python_command)} --version && pwd && uname -s"
            code, stdout, stderr = self._exec(client, command, timeout=30)
            if code != 0:
                raise AdapterError(f"SSH 探测命令失败: {(stderr or stdout).strip()[-1000:]}")
            key = client.get_transport().get_remote_server_key()
            fingerprint = hashlib.sha256(key.asbytes()).hexdigest()
            lines = [line.strip() for line in stdout.splitlines() if line.strip()]
            return {
                "backend": self.backend,
                "status": "ok",
                "host_key_sha256": fingerprint,
                "python_command": python_command,
                "remote": lines,
            }

    def _add_windows_control_scripts(self, bundle: Path) -> None:
        (bundle / "launch.ps1").write_text(WINDOWS_LAUNCH_PS1, encoding="utf-8")
        (bundle / "check.ps1").write_text(WINDOWS_CHECK_PS1, encoding="utf-8")
        (bundle / "cancel.ps1").write_text(WINDOWS_CANCEL_PS1, encoding="utf-8")

    def _windows_control_command(self, remote_dir: str, script: str, *args: str) -> str:
        script_path = self._win_cmd_quote(str(PurePosixPath(remote_dir) / script).replace("\\", "/"))
        parts = [script_path, *args]
        return "powershell -NoProfile -ExecutionPolicy Bypass -File " + " ".join(parts)

    def submit(self, spec: dict[str, Any]) -> dict[str, Any]:
        bundle = prepare_bundle(spec)
        if self._is_windows():
            self._add_windows_control_scripts(bundle)
        remote_dir = self._remote_dir(spec)
        with self._client() as client:
            python_command = self._python_command(client)
            with client.open_sftp() as sftp:
                self._upload_tree(sftp, bundle, remote_dir)
            if self._is_windows():
                task_name = f"automm-{spec['task_id']}-a{int(spec.get('attempt', 1)):03d}"
                command = self._windows_control_command(
                    remote_dir,
                    "launch.ps1",
                    "-Python",
                    self._win_cmd_quote(python_command),
                    "-TaskName",
                    self._win_cmd_quote(task_name),
                )
            else:
                quoted = shlex.quote(remote_dir)
                command = (
                    f"cd {quoted} && (nohup {shlex.quote(python_command)} runner.py "
                    "> launcher.log 2>&1 < /dev/null & echo $!)"
                )
            code, stdout, stderr = self._exec(client, command)
            if code != 0 or not stdout.strip():
                raise AdapterError(f"SSH 远端任务启动失败: {(stderr or stdout).strip()[-1000:]}")
            remote_job_id = stdout.strip().splitlines()[-1].strip()
            if self._is_windows() and not remote_job_id:
                raise AdapterError("SSH 远端任务启动失败: 未返回计划任务名")
            if not self._is_windows() and not remote_job_id.isdigit():
                raise AdapterError(f"SSH 远端任务启动失败: {(stderr or stdout).strip()[-1000:]}")
        return {"status": "running", "remote_job_id": remote_job_id, "remote_directory": remote_dir}

    def status(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        remote_dir = str(state.get("remote_directory") or self._remote_dir(spec))
        pid = str(state.get("remote_job_id", ""))
        with self._client() as client:
            with client.open_sftp() as sftp:
                try:
                    with sftp.open(str(PurePosixPath(remote_dir) / "remote-status.json"), "r") as handle:
                        payload = read_json_from_remote(handle.read())
                    return payload
                except OSError:
                    pass
            if self._is_windows():
                if pid:
                    code, _stdout, _stderr = self._exec(
                        client,
                        f"schtasks /Query /TN {self._win_cmd_quote(pid)} 2>nul",
                        timeout=20,
                    )
                else:
                    code = 1
            elif pid.isdigit():
                code, _stdout, _stderr = self._exec(client, f"kill -0 {shlex.quote(pid)} 2>/dev/null")
            else:
                code = 1
        if code == 0:
            return {"status": "running"}
        return {"status": "lost", "failure_type": "remote_process_lost", "message": "远端 PID 消失且没有终态文件"}

    def pull(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        remote_dir = str(state.get("remote_directory") or self._remote_dir(spec))
        local = RUNTIME_DIR / "remote_results" / "ssh" / spec["task_id"] / f"attempt-{int(spec.get('attempt', 1)):03d}"
        local.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []
        with self._client() as client:
            with client.open_sftp() as sftp:
                names = (
                    "remote-status.json",
                    "stdout.log",
                    "stderr.log",
                    "launcher.log",
                    "runner-error.log",
                    "automm-result.zip",
                )
                for name in names:
                    try:
                        sftp.get(str(PurePosixPath(remote_dir) / name), str(local / name))
                        downloaded.append(name)
                    except OSError:
                        continue
        archive = local / "automm-result.zip"
        if not archive.exists():
            raise AdapterError("SSH 结果包不存在")
        files = safe_extract_zip(archive, resolve_project_path(spec["output_directory"]))
        return {"downloaded": downloaded, "result_files": files, "result_archive": archive.relative_to(ROOT).as_posix()}

    def cancel(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        job_id = str(state.get("remote_job_id", ""))
        if not job_id:
            raise AdapterError("SSH 任务没有有效的远端任务标识")
        with self._client() as client:
            if self._is_windows():
                remote_dir = str(state.get("remote_directory") or self._remote_dir(spec))
                code, _stdout, stderr = self._exec(
                    client,
                    self._windows_control_command(remote_dir, "cancel.ps1", "-TaskName", self._win_cmd_quote(job_id)),
                    timeout=20,
                )
            else:
                if not job_id.isdigit():
                    raise AdapterError("SSH 任务没有有效的远端 PID")
                code, _stdout, stderr = self._exec(client, f"kill {shlex.quote(job_id)}", timeout=20)
        if code != 0:
            raise AdapterError(f"SSH 任务终止失败: {stderr.strip()[-1000:]}")
        return {"status": "cancelled"}


def read_json_from_remote(value: str | bytes) -> dict[str, Any]:
    import json

    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise AdapterError("SSH 远端状态不是 JSON 对象")
    return payload
