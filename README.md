# FastAPI PostgreSQL 数据库操作示例

这是一个基于 FastAPI 的 PostgreSQL 数据库操作示例，包含了基本的增删改查功能，并集成了 Redis 缓存、JWT 认证和监控接口。

## 功能特性

- ✅ 数据库连接管理
- ✅ 创建数据表
- ✅ 插入数据 (CREATE)
- ✅ 查询数据 (READ)
- ✅ 更新数据 (UPDATE)
- ✅ 删除数据 (DELETE)
- ✅ 模糊搜索
- ✅ 批量操作示例
- ✅ **Redis 缓存支持**（多后端访问）
- ✅ **JWT 认证系统**（6小时Token，支持续期）
- ✅ **监控接口缓存**（1分钟缓存失效）
- ✅ **缓存监控统计**
- ✅ **Token 缓存和续期**

## 安装依赖

```bash
pip install -r requirements.txt
```

**新增依赖**:
- `redis>=4.5.0`: Redis 客户端
- `hiredis>=2.0.0`: Redis 高性能解析器

**注意**: 如果安装 `psycopg2-binary` 时遇到问题，可以尝试以下解决方案：

1. **Windows 用户**: 确保使用 `psycopg2-binary` 而不是 `psycopg2`
2. **如果仍然失败**: 可以尝试安装预编译的 wheel 包：
   ```bash
   pip install --only-binary=all psycopg2-binary
   ```
3. **替代方案**: 如果问题持续，可以使用 `psycopg2` 的替代包：
   ```bash
   pip install psycopg2-binary --upgrade
   ```

## 数据库准备

1. 确保 PostgreSQL 服务正在运行
2. 创建数据库（可选）：
   ```sql
   CREATE DATABASE testdb;
   ```

## 配置数据库连接

复制 `.env.example` 为 `.env` 文件，并修改配置信息（`.env` 已在 `.gitignore` 中忽略，不会被提交）：

```bash
cp .env.example .env
```

编辑 `.env` 文件，修改以下配置：

### 数据库配置
- `DB_HOST`: 数据库主机地址
- `DB_PORT`: 数据库端口
- `DB_NAME`: 数据库名称
- `DB_USER`: 数据库用户名
- `DB_PASSWORD`: 数据库密码

### Redis配置
- `REDIS_HOST`: Redis主机地址（默认localhost）
- `REDIS_PORT`: Redis端口（默认6379）
- `REDIS_DB`: Redis数据库编号（默认0）
- `REDIS_PASSWORD`: Redis密码（可选）

### JWT安全配置（重要！）
- `JWT_SECRET_KEY`: JWT密钥（生产环境必须修改）
- `JWT_ALGORITHM`: JWT算法（默认HS256）
- `ACCESS_TOKEN_EXPIRE_MINUTES`: 访问令牌过期时间（默认6小时）
- `REFRESH_TOKEN_EXPIRE_DAYS`: 刷新令牌过期时间（默认7天）

**重要安全提醒**: 生产环境必须修改 `JWT_SECRET_KEY`，使用强随机密钥：
```bash
# 生成安全密钥
openssl rand -base64 32
# 或使用Python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 运行示例

```bash
python main.py
```

## 文件说明

- `database.py`: 数据库操作类，包含所有 CRUD 操作
- `main.py`: 主程序，演示各种数据库操作
- `requirements.txt`: Python 依赖包列表
- `env_example.txt`: 环境变量配置示例
  - 请复制为 `.env`，并填写真实的敏感信息（不要提交 `.env`）

## 数据库表结构

程序会自动创建 `users` 表，结构如下：

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    age INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 主要功能

### DatabaseManager 类方法

- `connect()`: 连接数据库
- `disconnect()`: 断开数据库连接
- `create_table()`: 创建用户表
- `insert_user(name, email, age)`: 插入新用户
- `get_user_by_id(user_id)`: 根据ID查询用户
- `get_all_users()`: 查询所有用户
- `update_user(user_id, name, email, age)`: 更新用户信息
- `delete_user(user_id)`: 删除用户
- `search_users_by_name(name_pattern)`: 根据姓名模糊搜索

## 注意事项

1. 确保 PostgreSQL 服务正在运行
2. 检查数据库连接配置是否正确
3. 确保有足够的数据库权限
4. 程序会自动创建表，如果表已存在则跳过创建
