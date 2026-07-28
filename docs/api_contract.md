# API Contract

Base URL:

```text
http://<server-ip>:8787
```

统一响应：

```json
{
  "ok": true,
  "data": {},
  "message": "ok"
}
```

错误响应：

```json
{
  "ok": false,
  "error_code": "SESSION_BUSY",
  "message": "session 1 is already running exp003",
  "data": {}
}
```

核心接口：

```text
GET  /health
GET  /dashboard/state
POST /experiments/scan
POST /queue/select
POST /sessions/{session_id}/run
GET  /sessions/{session_id}/status
GET  /sessions/{session_id}/log?tail=300
GET  /sessions/{session_id}
POST /sessions/{session_id}/stop
POST /sessions/{session_id}/clear
```

