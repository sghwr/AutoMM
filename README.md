# AutoMM

AutoMM 是一个面向数模/Kaggle 实验的轻量 client/server 工作流。

V1-beta 的边界：

- `client/`：TUI 控制台，只负责监视、调度和展示。
- `server/`：实验工作流服务端，负责扫描 `ACK.txt`、管理 session、本地运行、Kaggle 推送和输出拉取。
- `#Myworkfolder/`：实验脚本实际生成和运行目录。
- `explog.md`：人工顺序记录实验目的、参考文献和结论。

## 快速启动

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m server.app
```

另一个终端启动 TUI：

```powershell
.\.venv\Scripts\python -m client.tui.app
```

Mac 端运行 client 时，将 `configs/client.yaml` 的 `base_url` 改为 server 所在局域网地址。

## TUI 命令

```text
/help
/return
/select exp001
/run 0
/run 1
/run 1 --gpu
/status 2
/log 2
/session 2
/stop 2
/clear 2
/exit
```

`/status`、`/log`、`/session` 会进入只读全屏子界面，输入 `q` 返回主界面。

