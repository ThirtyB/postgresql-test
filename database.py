from traceback import print_tb
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from typing import List, Dict, Optional
from config import get_db_config

class DatabaseManager:
    def __init__(self):
        # 数据库连接配置由 config.py 统一管理
        self.db_config = get_db_config()
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
    
    def get_latest_monitor_metrics(self, limit: int = 5) -> List[Dict]:
        """查询最新的监控指标数据"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = """
            SELECT * FROM node_monitor_metrics 
            ORDER BY ts DESC, inserted_at DESC 
            LIMIT %s;
            """
            cursor.execute(select_query, (limit,))
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 {len(metrics_list)} 条监控指标数据")
            return metrics_list
        except psycopg2.Error as e:
            print(f"查询监控指标失败: {e}")
            return []
    
    def get_metrics_by_ip(self, ip: str, limit: int = 10) -> List[Dict]:
        """根据IP查询监控指标数据"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE ip = %s 
            ORDER BY ts DESC, inserted_at DESC 
            LIMIT %s;
            """
            cursor.execute(select_query, (ip, limit))
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 IP {ip} 的 {len(metrics_list)} 条监控指标数据")
            return metrics_list
        except psycopg2.Error as e:
            print(f"根据IP查询监控指标失败: {e}")
            return []
    
    def get_latest_metric_by_ip(self, ip: str) -> Optional[Dict]:
        """获取指定IP的最新一条监控指标数据"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE ip = %s 
            ORDER BY ts DESC, inserted_at DESC 
            LIMIT 1;
            """
            cursor.execute(select_query, (ip,))
            metric = cursor.fetchone()
            cursor.close()
            if metric:
                return dict(metric)
            return None
        except psycopg2.Error as e:
            print(f"获取IP最新监控指标失败: {e}")
            return None
    
    def get_metrics_by_time_range(self, start_ts: int, end_ts: int, ip: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """根据时间范围查询监控指标数据"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            if ip:
                select_query = """
                SELECT * FROM node_monitor_metrics 
                WHERE ts >= %s AND ts <= %s AND ip = %s
                ORDER BY ts DESC, inserted_at DESC 
                LIMIT %s;
                """
                cursor.execute(select_query, (start_ts, end_ts, ip, limit))
            else:
                select_query = """
                SELECT * FROM node_monitor_metrics 
                WHERE ts >= %s AND ts <= %s
                ORDER BY ts DESC, inserted_at DESC 
                LIMIT %s;
                """
                cursor.execute(select_query, (start_ts, end_ts, limit))
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 {len(metrics_list)} 条监控指标数据")
            return metrics_list
        except psycopg2.Error as e:
            print(f"根据时间范围查询监控指标失败: {e}")
            return []
    
    def get_metrics_paginated(self, page: int = 1, page_size: int = 20, ip: Optional[str] = None) -> Dict:
        """分页查询监控指标数据"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            offset = (page - 1) * page_size
            
            if ip:
                # 查询总数
                count_query = "SELECT COUNT(*) FROM node_monitor_metrics WHERE ip = %s;"
                cursor.execute(count_query, (ip,))
                total = cursor.fetchone()[0]
                
                # 查询数据
                select_query = """
                SELECT * FROM node_monitor_metrics 
                WHERE ip = %s
                ORDER BY ts DESC, inserted_at DESC 
                LIMIT %s OFFSET %s;
                """
                cursor.execute(select_query, (ip, page_size, offset))
            else:
                # 查询总数
                count_query = "SELECT COUNT(*) FROM node_monitor_metrics;"
                cursor.execute(count_query)
                total = cursor.fetchone()[0]
                
                # 查询数据
                select_query = """
                SELECT * FROM node_monitor_metrics 
                ORDER BY ts DESC, inserted_at DESC 
                LIMIT %s OFFSET %s;
                """
                cursor.execute(select_query, (page_size, offset))
            
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            
            return {
                "data": metrics_list,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
        except psycopg2.Error as e:
            print(f"分页查询监控指标失败: {e}")
            return {"data": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
    
    def get_all_ips(self) -> List[str]:
        """获取所有监控的IP列表"""
        try:
            cursor = self.connection.cursor()
            select_query = "SELECT DISTINCT ip FROM node_monitor_metrics ORDER BY ip;"
            cursor.execute(select_query)
            ips = [row[0] for row in cursor.fetchall()]
            cursor.close()
            print(f"查询到 {len(ips)} 个IP")
            return ips
        except psycopg2.Error as e:
            print(f"获取IP列表失败: {e}")
            return []
    
    def get_metrics_statistics(self, ip: Optional[str] = None, start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> Optional[Dict]:
        """获取监控指标的统计信息（平均值、最大值、最小值）"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            
            # 构建WHERE条件
            where_conditions = []
            params = []
            
            if ip:
                where_conditions.append("ip = %s")
                params.append(ip)
            if start_ts:
                where_conditions.append("ts >= %s")
                params.append(start_ts)
            if end_ts:
                where_conditions.append("ts <= %s")
                params.append(end_ts)
            
            where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            
            select_query = f"""
            SELECT 
                COUNT(*) as count,
                AVG(cpu_usr + COALESCE(cpu_sys, 0) + COALESCE(cpu_iow, 0)) as avg_cpu_total,
                MAX(cpu_usr + COALESCE(cpu_sys, 0) + COALESCE(cpu_iow, 0)) as max_cpu_total,
                MIN(cpu_usr + COALESCE(cpu_sys, 0) + COALESCE(cpu_iow, 0)) as min_cpu_total,
                AVG((mem_total - COALESCE(mem_free, 0) - COALESCE(mem_buff, 0) - COALESCE(mem_cache, 0)) * 100.0 / NULLIF(mem_total, 0)) as avg_mem_usage_percent,
                MAX((mem_total - COALESCE(mem_free, 0) - COALESCE(mem_buff, 0) - COALESCE(mem_cache, 0)) * 100.0 / NULLIF(mem_total, 0)) as max_mem_usage_percent,
                AVG(disk_used_percent) as avg_disk_used_percent,
                MAX(disk_used_percent) as max_disk_used_percent,
                AVG(net_rx_kbps) as avg_net_rx_kbps,
                MAX(net_rx_kbps) as max_net_rx_kbps,
                AVG(net_tx_kbps) as avg_net_tx_kbps,
                MAX(net_tx_kbps) as max_net_tx_kbps
            FROM node_monitor_metrics 
            {where_clause};
            """
            
            cursor.execute(select_query, params)
            stats = cursor.fetchone()
            cursor.close()
            
            if stats:
                return dict(stats)
            return None
        except psycopg2.Error as e:
            print(f"获取统计信息失败: {e}")
            return None
    
    def get_high_cpu_metrics(self, cpu_threshold: float = 80.0, limit: int = 20) -> List[Dict]:
        """查询CPU使用率超过阈值的监控指标"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE (cpu_usr + COALESCE(cpu_sys, 0) + COALESCE(cpu_iow, 0)) >= %s
            ORDER BY (cpu_usr + COALESCE(cpu_sys, 0) + COALESCE(cpu_iow, 0)) DESC, ts DESC
            LIMIT %s;
            """
            cursor.execute(select_query, (cpu_threshold, limit))
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 {len(metrics_list)} 条高CPU使用率监控指标")
            return metrics_list
        except psycopg2.Error as e:
            print(f"查询高CPU使用率监控指标失败: {e}")
            return []
    
    def get_high_memory_metrics(self, mem_threshold: float = 80.0, limit: int = 20) -> List[Dict]:
        """查询内存使用率超过阈值的监控指标"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE ((mem_total - COALESCE(mem_free, 0) - COALESCE(mem_buff, 0) - COALESCE(mem_cache, 0)) * 100.0 / NULLIF(mem_total, 0)) >= %s
            ORDER BY ((mem_total - COALESCE(mem_free, 0) - COALESCE(mem_buff, 0) - COALESCE(mem_cache, 0)) * 100.0 / NULLIF(mem_total, 0)) DESC, ts DESC
            LIMIT %s;
            """
            cursor.execute(select_query, (mem_threshold, limit))
            metrics = cursor.fetchall()
            cursor.close()
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 {len(metrics_list)} 条高内存使用率监控指标")
            return metrics_list
        except psycopg2.Error as e:
            print(f"查询高内存使用率监控指标失败: {e}")
            return []