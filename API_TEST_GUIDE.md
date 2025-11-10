# FastAPI接口测试指南

## 内置管理员Token

为了方便测试，系统已经内置了一个有效的管理员JWT token：

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInVzZXJfaWQiOjgsInJvbGUiOiJhZG1pbiIsImV4cCI6MTc2MjYwNDI5N30.uqrGGFnA7j_-SNe4TN5762vgtQtqI5yxUYtMpuM9ojY
```

## 使用方法

### 1. 访问Swagger UI
启动服务后，访问：http://localhost:8000/docs

### 2. 设置Token
1. 点击右上角的 "Authorize" 按钮
2. 在弹出的对话框中输入：
   ```
   Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInVzZXJfaWQiOjgsInJvbGUiOiJhZG1pbiIsImV4cCI6MTc2MjYwNDI5N30.uqrGGFnA7j_-SNe4TN5762vgtQtqI5yxUYtMpuM9ojY
   ```
3. 点击 "Authorize" 按钮确认

### 3. 测试接口
现在你可以直接测试所有需要认证的接口，无需手动获取token。

## Token信息

- **用户名**: admin
- **用户ID**: 8
- **角色**: admin
- **过期时间**: 2025-11-08 23:58:17

## 快速获取Token

你也可以通过以下接口获取token信息：

```bash
GET /test-token
```

## 接口权限说明

- **公开接口** (无需认证):
  - `GET /` - 根路径
  - `POST /auth/register` - 用户注册
  - `POST /auth/login` - 用户登录

- **需要认证的接口** (使用内置token):
  - 所有 `/admin/` 开头的接口 - 管理员功能
  - 所有 `/monitor-metrics/` 开头的接口 - 监控数据
  - 所有 `/protected/` 开头的接口 - 受保护数据

## 开发建议

1. 在开发环境中使用内置token进行测试
2. 生产环境中请使用真实的用户登录流程
3. 内置token有较长的过期时间，适合开发测试

## 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

然后访问 http://localhost:8000/docs 开始测试。