# PostgreSQL 数据库操作示例

这是一个简单的 Python PostgreSQL 数据库操作示例，包含了基本的增删改查功能。

## 功能特性

- ✅ 数据库连接管理
- ✅ 创建数据表
- ✅ 插入数据 (CREATE)
- ✅ 查询数据 (READ)
- ✅ 更新数据 (UPDATE)
- ✅ 删除数据 (DELETE)
- ✅ 模糊搜索
- ✅ 批量操作示例

## 安装依赖

```bash
pip install -r requirements.txt
```

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

复制 `env_example.txt` 为 `.env` 文件，并修改数据库连接信息：

```bash
cp env_example.txt .env
```

编辑 `.env` 文件，修改以下配置：
- `DB_HOST`: 数据库主机地址
- `DB_PORT`: 数据库端口
- `DB_NAME`: 数据库名称
- `DB_USER`: 数据库用户名
- `DB_PASSWORD`: 数据库密码

## 运行示例

```bash
python main.py
```

## 文件说明

- `database.py`: 数据库操作类，包含所有 CRUD 操作
- `main.py`: 主程序，演示各种数据库操作
- `requirements.txt`: Python 依赖包列表
- `env_example.txt`: 环境变量配置示例

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
