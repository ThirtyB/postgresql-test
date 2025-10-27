#!/usr/bin/env python3
"""
PostgreSQL数据库操作示例程序
演示基本的增删改查操作
"""

from database import DatabaseManager
import os

def main():
    """主程序演示数据库操作"""
    print("=== PostgreSQL 数据库操作示例 ===\n")
    
    # 创建数据库管理器实例
    db = DatabaseManager()
    
    # 连接数据库
    if not db.connect():
        print("无法连接到数据库，程序退出")
        return
    
    try:
        # 创建表
        print("1. 创建用户表...")
        db.create_table()
        print()
        
        # 插入数据
        print("2. 插入用户数据...")
        user1_id = db.insert_user("张三", "zhangsan@example.com", 25, "123456")
        user2_id = db.insert_user("李四", "lisi@example.com", 30, "123456")
        user3_id = db.insert_user("王五", "wangwu@example.com", 28, "123456")
        print()
        
        # 查询单个用户
        print("3. 查询单个用户...")
        user = db.get_user_by_id(user1_id)
        print()
        print("3.1 通过邮箱查询单个用户")
        user = db.get_user_by_email("zhangsan@example.com")
        print(user)
        print()
        
        # 查询所有用户
        print("4. 查询所有用户...")
        all_users = db.get_all_users()
        for user in all_users:
            print(f"  ID: {user['id']}, 姓名: {user['name']}, 邮箱: {user['email']}, 年龄: {user['age']}")
        print()
        
        # 更新用户
        print("5. 更新用户信息...")
        db.update_user(user1_id, name="张三丰", age=26, password="12345678")
        updated_user = db.get_user_by_id(user1_id)
        print()
        
        # 模糊搜索
        print("6. 模糊搜索用户...")
        search_results = db.search_users_by_name("三")
        for user in search_results:
            print(f"  找到用户: {user['name']} ({user['email']})")
        print()
        
        # 删除用户
        print("7. 删除用户...")
        db.delete_user(user3_id)
        print()
        
        # 再次查询所有用户
        print("8. 删除后的用户列表...")
        remaining_users = db.get_all_users()
        for user in remaining_users:
            print(f"  ID: {user['id']}, 姓名: {user['name']}, 邮箱: {user['email']}, 年龄: {user['age']}, 密码: {user['password']}")
        print()
        
    except Exception as e:
        print(f"程序执行出错: {e}")
    
    finally:
        # 关闭数据库连接
        db.disconnect()
        print("程序执行完毕!")

def demo_advanced_operations():
    """演示高级操作"""
    print("\n=== 高级操作演示 ===\n")
    
    db = DatabaseManager()
    if not db.connect():
        return
    
    try:
        # 批量插入
        print("批量插入用户...")
        users_data = [
            ("赵六", "zhaoliu@example.com", 32, "123456"),
            ("钱七", "qianqi@example.com", 29, "123456"),
            ("孙八", "sunba@example.com", 35, "123456")
        ]
        
        for name, email, age, password in users_data:
            db.insert_user(name, email, age, password)
        print()
        
        # 条件查询
        print("查询年龄大于30的用户...")
        all_users = db.get_all_users()
        older_users = [user for user in all_users if user['age'] and user['age'] > 30]
        for user in older_users:
            print(f"  {user['name']} - {user['age']}岁")
        print()
        
        # 更新多个字段
        print("更新用户多个字段...")
        if older_users:
            first_user = older_users[0]
            db.update_user(first_user['id'], name=f"{first_user['name']}_updated", age=first_user['age'] + 1)
        print()
        
    except Exception as e:
        print(f"高级操作出错: {e}")
    
    finally:
        db.disconnect()

if __name__ == "__main__":
    # 设置环境变量（可选）
    # os.environ['DB_HOST'] = 'localhost'
    # os.environ['DB_PORT'] = '5432'
    # os.environ['DB_NAME'] = 'your_database'
    # os.environ['DB_USER'] = 'your_username'
    # os.environ['DB_PASSWORD'] = 'your_password'
    
    # 运行基本操作演示
    main()
    
    # 运行高级操作演示
    demo_advanced_operations()
