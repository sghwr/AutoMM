# TUI Commands

| 命令 | 说明 |
| --- | --- |
| `/help` | 显示帮助 |
| `/return` | 触发 server 扫描并刷新主界面 |
| `/select exp001` | 选择 Ready Queue 中的实验 |
| `/run 0` | 在 local session 运行当前选择的实验 |
| `/run 1` | 在 Kaggle CPU session 运行当前选择的实验 |
| `/run 1 --gpu` | 在 Kaggle GPU session 运行当前选择的实验 |
| `/status 2` | 进入 session 2 全屏状态视图 |
| `/log 2` | 进入 session 2 全屏日志视图 |
| `/session 2` | 进入 session 2 元信息视图 |
| `/stop 2` | 请求停止 session 2，需要确认 |
| `/clear 2` | 清理已结束 session 的显示，需要确认 |
| `/exit` | 退出 client TUI |

