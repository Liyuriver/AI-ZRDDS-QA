# 前后端联调说明

复制 `.env.example` 为 `.env.local`。Mock 模式使用 `VITE_USE_MOCK=true`；连接真实 FastAPI 时使用：

```env
VITE_USE_MOCK=false
VITE_API_BASE_URL=/api/v1
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
```

Vite 会把 `/api` 请求代理至 FastAPI，开发阶段无需浏览器跨域配置。

## 已适配接口

- `POST /api/v1/users`
- `GET /api/v1/users`
- `POST /api/v1/conversations`
- `GET /api/v1/users/{user_id}/conversations`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/chat`

## 当前后端缺口

1. 没有密码认证接口。真实模式暂时使用用户名和邮箱识别用户，不能视为正式认证。
2. 没有会话标题更新接口，首问标题只在当前前端运行期间显示。
3. 历史消息不保存引用、图片和回答状态，刷新后旧回答只能恢复正文。
4. `Source` 没有版本和 `version_status` 字段，前端必须显示“版本适用性未知”。
5. Windows 后端测试需要 `tzdata`，当前依赖文件未声明。
6. 知识 API 测试依赖未提交的 `backend/data/metadata/document_metadata.json`。
