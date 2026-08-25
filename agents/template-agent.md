## 目的

生成新的 AutoMM 专职 Agent 定义。不得覆盖同名 Agent，除非调用者明确要求更新。

## 必含区块

1. YAML frontmatter：name、description、tools、model。
2. 角色：单一职责和不负责事项。
3. 输入：权威文件和前置状态。
4. 步骤：有序、可执行、包含落盘动作。
5. 完成条件和失败路由。
6. 约束：路径、版本、引用、状态和安全边界。
7. 统一输出字段：status、IDs、artifacts、findings、warnings、blocking、next stage、state patch。

工具遵循最小权限原则；路径必须相对；所有说明使用简体中文。生成后回报文件路径、触发描述和与 Orchestrator 的契约。
