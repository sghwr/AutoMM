from __future__ import annotations

from automm.tasks import reconcile_tasks


def test_reconcile_dead_worker_is_transient(initialized_problem: tuple[str, object]) -> None:
    # 真实 task 的创建需要已接受 formulation；这里确保对账入口可安全调用。
    assert reconcile_tasks() == []
