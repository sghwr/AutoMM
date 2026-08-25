"""使用官方 Kaggle CLI 提交和拉取私有 Kernel。"""

from __future__ import annotations

import base64
import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from ..common import ROOT, RUNTIME_DIR, read_yaml, resolve_project_path, write_json, write_text
from .base import AdapterError, RemoteAdapter, run_command, secret_value
from .bundle import prepare_bundle, safe_extract_zip


class KaggleAdapter(RemoteAdapter):
    backend = "kaggle"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or read_yaml(ROOT / "config" / "kaggle.yaml")
        if not self.config.get("enabled", False):
            raise AdapterError("Kaggle 适配器未启用")

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        username = str(self.config.get("username", "") or "").strip()
        token = secret_value(self.config, "auth_token", "auth_token_env")
        if not username or not token:
            raise AdapterError("Kaggle username 或 auth_token 未配置")
        env.update(
            {
                "KAGGLE_USERNAME": username,
                "KAGGLE_API_TOKEN": token,
                "KAGGLE_KEY": token,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        return env

    def _slug(self, spec: dict[str, Any]) -> str:
        username = str(self.config["username"]).lower()
        attempt = int(spec.get("attempt", 1))
        return f"{username}/automm-{spec['task_id']}-a{attempt:03d}"

    def probe(self) -> dict[str, Any]:
        result = run_command(
            ["kaggle", "kernels", "list", "--mine", "--page-size", "1", "--csv"],
            env=self._env(),
            timeout=45,
        )
        return {
            "backend": self.backend,
            "status": "ok",
            "authenticated": True,
            "response_lines": len(result.stdout.splitlines()),
        }

    def _stage(self, spec: dict[str, Any]) -> Path:
        bundle = prepare_bundle(spec)
        stage = RUNTIME_DIR / "remote_bundles" / spec["task_id"] / f"attempt-{int(spec.get('attempt', 1)):03d}-kaggle"
        stage.mkdir(parents=True, exist_ok=True)
        memory = BytesIO()
        with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in bundle.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle).as_posix())
        encoded = base64.b64encode(memory.getvalue()).decode("ascii")
        kernel = (
            "import base64, pathlib, shutil, subprocess, sys, zipfile\n"
            f"payload = {encoded!r}\n"
            "root = pathlib.Path('/kaggle/working/automm')\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "archive = root / 'bundle.zip'\n"
            "archive.write_bytes(base64.b64decode(payload))\n"
            "with zipfile.ZipFile(archive) as z: z.extractall(root)\n"
            "code = subprocess.run([sys.executable, str(root / 'runner.py')], cwd=root).returncode\n"
            "if (root / 'automm-result.zip').exists(): shutil.copy2(\n"
            "    root / 'automm-result.zip', pathlib.Path('/kaggle/working/automm-result.zip'))\n"
            "raise SystemExit(code)\n"
        )
        write_text(stage / "kernel.py", kernel)
        slug = self._slug(spec)
        # Kaggle CLI validates that slugify(title) matches the kernel slug.
        # Keep the human title identical to the slug suffix for deterministic pushes.
        kernel_slug = slug.split("/", 1)[1]
        metadata = {
            "id": slug,
            "title": kernel_slug,
            "code_file": "kernel.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": False,
            "enable_internet": False,
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
        }
        write_json(stage / "kernel-metadata.json", metadata)
        return stage

    def submit(self, spec: dict[str, Any]) -> dict[str, Any]:
        stage = self._stage(spec)
        run_command(["kaggle", "kernels", "push", "-p", str(stage)], env=self._env(), timeout=180)
        return {
            "status": "queued",
            "remote_job_id": self._slug(spec),
            "remote_directory": stage.relative_to(ROOT).as_posix(),
        }

    def status(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        slug = str(state.get("remote_job_id") or self._slug(spec))
        result = run_command(["kaggle", "kernels", "status", slug], env=self._env(), timeout=45)
        text = f"{result.stdout}\n{result.stderr}".lower()
        match = re.search(r"status\s*[:=]\s*[\"']?([a-z_ -]+)", text)
        normalized = match.group(1).strip().replace("-", "_").replace(" ", "_") if match else text
        if (
            normalized in {"complete", "completed", "success", "succeeded"}
            or "status: complete" in text
            or "kernelworkerstatus.complete" in text
        ):
            return {"status": "succeeded"}
        if (
            normalized in {"error", "failed", "failure"}
            or "status: error" in text
            or "kernelworkerstatus.error" in text
            or "kernelworkerstatus.failed" in text
        ):
            return {"status": "failed", "failure_type": "remote_process_exit", "message": result.stdout.strip()[-1000:]}
        if normalized.startswith("cancel"):
            return {"status": "cancelled"}
        if normalized.startswith("run") or "status: running" in text:
            return {"status": "running"}
        if normalized.startswith("queue") or "status: queued" in text:
            return {"status": "queued"}
        raise AdapterError(f"无法解析 Kaggle Kernel 状态: {result.stdout.strip()[-1000:]}")

    def pull(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        slug = str(state.get("remote_job_id") or self._slug(spec))
        local = (
            RUNTIME_DIR / "remote_results" / "kaggle" / spec["task_id"] / f"attempt-{int(spec.get('attempt', 1)):03d}"
        )
        local.mkdir(parents=True, exist_ok=True)
        run_command(
            ["kaggle", "kernels", "output", slug, "-p", str(local), "--force", "--quiet"],
            env=self._env(),
            timeout=180,
        )
        archive = local / "automm-result.zip"
        if not archive.exists():
            raise AdapterError("Kaggle 输出中没有 automm-result.zip")
        files = safe_extract_zip(archive, resolve_project_path(spec["output_directory"]))
        return {"result_files": files, "result_archive": archive.relative_to(ROOT).as_posix()}

    def cancel(self, spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        raise AdapterError("Kaggle CLI 不提供安全的运行中取消接口；请在 Kaggle 控制台终止")
