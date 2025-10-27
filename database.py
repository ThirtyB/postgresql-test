from traceback import print_tb
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from typing import List, Dict, Optional

class DatabaseManager:
    def __init__(self):
        # 数据库连接配置
        self.db_config = {
            'host': os.getenv('DB_HOST', '192.168.0.166'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'exampledb'),
            'user': os.getenv('DB_USER', 'user1'),
            'password': os.getenv('DB_PASSWORD', '123456')
        }
        self.connection = None
    
    def connect(self):
        """建立数据库连接"""
        try:
            self.connection = psycopg2.connect(**self.db_config)
            print("数据库连接成功!")
            return True
        except psycopg2.Error as e:
            print(f"数据库连接失败: {e}")
            return False
    
    def disconnect(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            print("数据库连接已关闭")
    
    def create_table(self):
        """创建用户表"""
        try:
            cursor = self.connection.cursor()
            create_table_query = """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                password VARCHAR(100) NOT NULL,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                age INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
            cursor.execute(create_table_query)
            self.connection.commit()
            print("用户表创建成功!")
            cursor.close()
        except psycopg2.Error as e:
            print(f"创建表失败: {e}")
            self.connection.rollback()
    
    def insert_user(self, name: str, email: str, age: int, password: str) -> Optional[int]:
        """插入新用户"""
        try:
            cursor = self.connection.cursor()
            insert_query = """
            INSERT INTO users (name, email, age, password) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id, name;
            """
            cursor.execute(insert_query, (name, email, age, password))
            user_id = cursor.fetchone()
            print(user_id)
            user_name = user_id[1]
            user_id = user_id[0]
            self.connection.commit()
            print(f"用户插入成功! ID: {user_id}， name: {user_name}")
            cursor.close()
            return user_id
        except psycopg2.Error as e:
            print(f"插入用户失败: {e}")
            self.connection.rollback()
            return None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据ID查询用户"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = "SELECT * FROM users WHERE id = %s;"
            cursor.execute(select_query, (user_id,))
            user = cursor.fetchone()
            print(f"查询id中，这里返回信息是{user}")
            cursor.close()
            if user:
                print(f"找到用户: {dict(user)}")
                return dict(user)
            else:
                print(f"未找到ID为 {user_id} 的用户")
                return None
        except psycopg2.Error as e:
            print(f"查询用户失败: {e}")
            return None
            
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根据邮箱查询用户"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = "SELECT * FROM users WHERE email = %s;"
            cursor.execute(select_query, (email,))
            user = cursor.fetchone()
            cursor.close()
            return dict(user)
        except psycopg2.Error as e:
            print(f"查询用户失败: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """查询所有用户"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = "SELECT * FROM users ORDER BY id;"
            cursor.execute(select_query)
            users = cursor.fetchall()
            cursor.close()
            users_list = [dict(user) for user in users]
            print(f"查询到 {len(users_list)} 个用户")
            return users_list
        except psycopg2.Error as e:
            print(f"查询所有用户失败: {e}")
            return []
    
    def update_user(self, user_id: int, name: str = None, email: str = None, age: int = None, password = None) -> bool:
        """更新用户信息"""
        try:
            cursor = self.connection.cursor()
            
            # 构建动态更新查询
            update_fields = []
            params = []
            
            if name is not None:
                update_fields.append("name = %s")
                params.append(name)
            if email is not None:
                update_fields.append("email = %s")
                params.append(email)
            if age is not None:
                update_fields.append("age = %s")
                params.append(age)
            if password is not None:
                update_fields.append("password = %s")
                params.append(password)
            
            if not update_fields:
                print("没有提供要更新的字段")
                return False
            
            params.append(user_id)
            update_query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s;"
            cursor.execute(update_query, params)
            rows_affected = cursor.rowcount
            self.connection.commit()
            cursor.close()
            
            if rows_affected > 0:
                print(f"用户 {user_id} 更新成功!")
                return True
            else:
                print(f"未找到ID为 {user_id} 的用户")
                return False
        except psycopg2.Error as e:
            print(f"更新用户失败: {e}")
            self.connection.rollback()
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        try:
            cursor = self.connection.cursor()
            delete_query = "DELETE FROM users WHERE id = %s;"
            cursor.execute(delete_query, (user_id,))
            rows_affected = cursor.rowcount
            self.connection.commit()
            cursor.close()
            
            if rows_affected > 0:
                print(f"用户 {user_id} 删除成功!")
                return True
            else:
                print(f"未找到ID为 {user_id} 的用户")
                return False
        except psycopg2.Error as e:
            print(f"删除用户失败: {e}")
            self.connection.rollback()
            return False
    
    def search_users_by_name(self, name_pattern: str) -> List[Dict]:
        """根据姓名模糊查询用户"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            search_query = "SELECT * FROM users WHERE name ILIKE %s ORDER BY id;"
            cursor.execute(search_query, (f"%{name_pattern}%",))
            users = cursor.fetchall()
            cursor.close()
            users_list = [dict(user) for user in users]
            print(f"找到 {len(users_list)} 个匹配的用户")
            return users_list
        except psycopg2.Error as e:
            print(f"搜索用户失败: {e}")
            return []
