---
name: email-notifier
description: 发送小问完成与整题摘要完成通知，并接收流程控制命令。
---

# Email Notifier

## 发送

SMTP 发送。小问完成邮件包括题目/小问 ID、模型、主要结果、图表、sanity、robustness、路径和下一步；整题完成邮件指向 `reports/final_summary.md`。两者均为单向通知。

发送失败重试 3 次；失败后继续并记录 warning，不改变研究结果状态。

## 接收

IMAP 或稳定 API 轮询。校验 allowed_senders 和未处理 message ID，只接受精确的 PAUSE/STOP/RESUME。处理后将 message ID 原子写入 processed 文件，防止重复执行。

## 安全

邮箱密码优先从环境变量读取。不要在日志中输出密码、完整 token 或邮件认证头。
