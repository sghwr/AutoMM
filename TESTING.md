# AutoMM 0.0.2 Beta 测试入口

测试只使用合成 Harness fixture，不读取真实题目、附件、smoke attempt 或远端凭据。

```text
python -m pytest -q
python -m ruff check scripts tests
python -m compileall -q scripts tests
python scripts/harness.py validate-config
```

故障注入重点覆盖 Agent 超时恢复、worker 中断、任务输出隔离、`PASS_WITH_WARNING`、Harness invariant、事务回滚、控制 flag 和跨小问推进。
