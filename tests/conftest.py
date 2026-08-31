from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1]
ISOLATED_ROOT = Path(tempfile.mkdtemp(prefix="automm-harness-tests-"))
os.environ["AUTOMM_ROOT"] = str(ISOLATED_ROOT)
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))


def _copy_static_tree() -> None:
    for name in ("config", "templates", "agents", "skills", "scripts"):
        source = SOURCE_ROOT / name
        target = ISOLATED_ROOT / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)


def _reset_dynamic_tree() -> None:
    for name in ("runtime", "problems", "reports", "request", "data"):
        target = ISOLATED_ROOT / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    (ISOLATED_ROOT / "reports" / "autoresearch").mkdir(parents=True)
    (ISOLATED_ROOT / "request" / "attachments").mkdir(parents=True)
    (ISOLATED_ROOT / "request" / "problem.md").write_text(
        "# 合成数学建模题\n\n研究一个受容量约束的线性系统。\n", encoding="utf-8"
    )
    for name in ("AGENTS.md", "PROJECT.md", "RESEARCH_LOOP.md"):
        source = SOURCE_ROOT / name
        if source.exists():
            shutil.copy2(source, ISOLATED_ROOT / name)
    _normalize_local_test_config()


def _normalize_local_test_config() -> None:
    """把从工作区复制来的本机配置重置为测试所需的本地/关闭态。

    工作区里的 config/compute.yaml 与 config/ssh.yaml 可能已按本机环境改为
    remote/ssh；测试必须跑在确定性的 local 模式，不受本机配置影响。
    """
    from automm.common import read_yaml, write_yaml

    compute_path = ISOLATED_ROOT / "config" / "compute.yaml"
    compute = read_yaml(compute_path)
    compute["default_backend"] = "local"
    write_yaml(compute_path, compute)

    ssh_path = ISOLATED_ROOT / "config" / "ssh.yaml"
    ssh = read_yaml(ssh_path)
    ssh["enabled"] = False
    write_yaml(ssh_path, ssh)


_copy_static_tree()
_reset_dynamic_tree()


@pytest.fixture(autouse=True)
def isolated_project() -> Path:
    _copy_static_tree()
    _reset_dynamic_tree()
    return ISOLATED_ROOT


@pytest.fixture
def project_root() -> Path:
    return ISOLATED_ROOT


@pytest.fixture
def initialized_problem() -> tuple[str, Path]:
    from automm.problems import init_problem

    problem_id = "synthetic"
    return problem_id, init_problem(problem_id, 3)
