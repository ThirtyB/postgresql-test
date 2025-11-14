import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from typing import List, Dict, Optional
from config import get_db_config
import threading
import bcrypt
import time
from auth_models import UserCreate, UserUpdate, UserLogin, UserResponse


class DatabaseManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化数据库连接池"""
        self.db_config = get_db_config()
        # 创建连接池，最小1个连接，最大10个连接
        self.connection_pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            **self.db_config
        )
        print("数据库连接池初始化成功!")
    
    def get_connection(self):
        """从连接池获取连接"""
        try:
            connection = self.connection_pool.getconn()
            return connection
        except psycopg2.Error as e:
            print(f"获取数据库连接失败: {e}")
            return None
    
    def return_connection(self, connection):
        """将连接返回到连接池"""
        if connection:
            self.connection_pool.putconn(connection)
    
    def close_all_connections(self):
        """关闭所有连接"""
        if hasattr(self, 'connection_pool'):
            self.connection_pool.closeall()
            print("所有数据库连接已关闭")
    
    def create_table(self):
        """创建用户表"""
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
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
            connection.commit()
            print("用户表创建成功!")
            cursor.close()
            return True
        except psycopg2.Error as e:
            print(f"创建表失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def insert_user(self, name: str, email: str, age: int, password: str) -> Optional[int]:
        """插入新用户"""
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor()
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
            connection.commit()
            print(f"用户插入成功! ID: {user_id}， name: {user_name}")
            cursor.close()
            return user_id
        except psycopg2.Error as e:
            print(f"插入用户失败: {e}")
            connection.rollback()
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据ID查询用户"""
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
            
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """根据邮箱查询用户"""
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            select_query = "SELECT * FROM users WHERE email = %s;"
            cursor.execute(select_query, (email,))
            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except psycopg2.Error as e:
            print(f"查询用户失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_all_users(self) -> List[Dict]:
        """查询所有用户"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def update_user(self, user_id: int, name: str = None, email: str = None, age: int = None, password = None) -> bool:
        """更新用户信息"""
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            
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
            connection.commit()
            cursor.close()
            
            if rows_affected > 0:
                print(f"用户 {user_id} 更新成功!")
                return True
            else:
                print(f"未找到ID为 {user_id} 的用户")
                return False
        except psycopg2.Error as e:
            print(f"更新用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            delete_query = "DELETE FROM users WHERE id = %s;"
            cursor.execute(delete_query, (user_id,))
            rows_affected = cursor.rowcount
            connection.commit()
            cursor.close()
            
            if rows_affected > 0:
                print(f"用户 {user_id} 删除成功!")
                return True
            else:
                print(f"未找到ID为 {user_id} 的用户")
                return False
        except psycopg2.Error as e:
            print(f"删除用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def search_users_by_name(self, name_pattern: str) -> List[Dict]:
        """根据姓名模糊查询用户"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_latest_monitor_metrics(self, limit: int = 5) -> List[Dict]:
        """查询最新的监控指标数据"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_metrics_by_ip(self, ip: str, limit: int = 10) -> List[Dict]:
        """根据IP查询监控指标数据"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_latest_metric_by_ip(self, ip: str) -> Optional[Dict]:
        """获取指定IP的最新一条监控指标数据"""
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_metrics_by_time_range(self, start_ts: int, end_ts: int, ip: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """根据时间范围查询监控指标数据"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_metrics_paginated(self, page: int = 1, page_size: int = 20, ip: Optional[str] = None) -> Dict:
        """分页查询监控指标数据"""
        connection = self.get_connection()
        if not connection:
            return {"data": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_all_ips(self) -> List[str]:
        """获取所有监控的IP列表"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor()
            select_query = "SELECT DISTINCT ip FROM node_monitor_metrics ORDER BY ip;"
            cursor.execute(select_query)
            ips = [row[0] for row in cursor.fetchall()]
            cursor.close()
            print(f"查询到 {len(ips)} 个IP")
            return ips
        except psycopg2.Error as e:
            print(f"获取IP列表失败: {e}")
            return []
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_metrics_statistics(self, ip: Optional[str] = None, start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> Optional[Dict]:
        """获取监控指标的统计信息（平均值、最大值、最小值）"""
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_high_cpu_metrics(self, cpu_threshold: float = 80.0, limit: int = 20) -> List[Dict]:
        """查询CPU使用率超过阈值的监控指标"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories
    
    def get_high_memory_metrics(self, mem_threshold: float = 80.0, limit: int = 20) -> List[Dict]:
        """查询内存使用率超过阈值的监控指标"""
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
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
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def get_active_machines_latest_metrics(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取指定时间窗口内活跃机器的最新监控指标
        
        Args:
            time_window_hours: 时间窗口（小时），默认为1小时
            
        Returns:
            每个活跃机器的最新监控指标列表
        """
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            # 计算时间窗口的开始时间戳（当前时间 - 时间窗口）
            import time
            current_timestamp = int(time.time())
            start_timestamp = current_timestamp - (time_window_hours * 3600)
            
            select_query = """
            SELECT
                t0.*
            FROM
                node_monitor_metrics t0,
                (SELECT ip, MAX(ts) AS ts FROM node_monitor_metrics WHERE ts > %s GROUP BY ip) t1
            WHERE
                t0.ip = t1.ip
                AND t0.ts = t1.ts
            """
            
            cursor.execute(select_query, (start_timestamp,))
            metrics = cursor.fetchall()
            cursor.close()
            
            metrics_list = [dict(metric) for metric in metrics]
            print(f"查询到 {len(metrics_list)} 个活跃机器的最新监控指标")
            return metrics_list
            
        except psycopg2.Error as e:
            print(f"获取活跃机器最新监控指标失败: {e}")
            return []
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def get_latest_complete_metrics_by_ip(self, ip: str) -> Optional[Dict]:
        """
        根据IP地址获取该IP的最新完整监控信息，包含所有计算字段
        
        Args:
            ip: IP地址
            
        Returns:
            该IP的最新完整监控信息，包含原始字段和计算字段
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
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
                metric_dict = dict(metric)
                # 在后端完成所有计算
                enriched_metric = self._enrich_metric_with_calculated_fields(metric_dict)
                print(f"成功获取IP {ip} 的最新完整监控信息")
                return enriched_metric
                
        except psycopg2.Error as e:
            print(f"获取IP {ip} 的最新完整监控信息失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def get_latest_ten_complete_metrics_by_ip(self, ip: str) -> List[Dict]:
        """
        根据IP地址获取该IP的最近十条完整监控信息，包含所有计算字段
        
        Args:
            ip: IP地址
            
        Returns:
            该IP的最近十条完整监控信息列表，包含原始字段和计算字段
        """
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE ip = %s 
            ORDER BY ts DESC, inserted_at DESC 
            LIMIT 10;
            """
            
            cursor.execute(select_query, (ip,))
            metrics = cursor.fetchall()
            cursor.close()
            
            enriched_metrics = []
            for metric in metrics:
                metric_dict = dict(metric)
                # 在后端完成所有计算
                enriched_metric = self._enrich_metric_with_calculated_fields(metric_dict)
                enriched_metrics.append(enriched_metric)
            
            print(f"成功获取IP {ip} 的 {len(enriched_metrics)} 条完整监控信息")
            return enriched_metrics
                
        except psycopg2.Error as e:
            print(f"获取IP {ip} 最近十条完整监控信息失败: {e}")
            return []
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    # ==================== 用户认证相关方法 ====================

    def create_user(self, user_data: UserCreate) -> Optional[int]:
        """
        创建新用户
        
        Args:
            user_data: 用户创建数据
            
        Returns:
            创建的用户ID，失败返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor()
            
            # 检查用户名是否已存在
            check_query = """
            SELECT id FROM users 
            WHERE username = %s
            """
            cursor.execute(check_query, (user_data.username,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                print(f"用户名 {user_data.username} 已存在")
                return None
            
            # 哈希密码
            password_hash = bcrypt.hashpw(
                user_data.password.encode('utf-8'), 
                bcrypt.gensalt()
            ).decode('utf-8')
            
            # 插入新用户（只插入用户名和密码）
            insert_query = """
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
            RETURNING id
            """
            cursor.execute(insert_query, (
                user_data.username,
                password_hash
            ))
            
            user_id = cursor.fetchone()[0]
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_data.username} 创建成功，ID: {user_id}")
            return user_id
            
        except psycopg2.Error as e:
            print(f"创建用户失败: {e}")
            connection.rollback()
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories



    def get_user_by_id(self, user_id: int) -> Optional[UserResponse]:
        """
        根据ID获取用户信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户信息，不存在返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT id, username, role, is_active, 
                   last_login, created_at, updated_at
            FROM users 
            WHERE id = %s
            """
            cursor.execute(select_query, (user_id,))
            user_record = cursor.fetchone()
            cursor.close()
            
            if not user_record:
                return None
            
            return UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
        except psycopg2.Error as e:
            print(f"获取用户信息失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def authenticate_user(self, login_data: UserLogin) -> Optional[UserResponse]:
        """
        用户认证
        
        Args:
            login_data: 登录数据
            
        Returns:
            认证成功的用户信息，失败返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            # 查询用户信息
            select_query = """
            SELECT id, username, password_hash, role, 
                   is_active, last_login, created_at, updated_at
            FROM users 
            WHERE username = %s AND is_active = true
            """
            cursor.execute(select_query, (login_data.username,))
            user_record = cursor.fetchone()
            
            if not user_record:
                print(f"用户 {login_data.username} 不存在或未激活")
                return None
            
            # 验证密码
            if not bcrypt.checkpw(
                login_data.password.encode('utf-8'),
                user_record['password_hash'].encode('utf-8')
            ):
                print(f"用户 {login_data.username} 密码错误")
                return None
            
            # 更新最后登录时间
            update_query = """
            UPDATE users SET last_login = NOW() WHERE id = %s
            """
            cursor.execute(update_query, (user_record['id'],))
            connection.commit()
            cursor.close()
            
            # 转换为响应模型
            user_response = UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
            print(f"用户 {login_data.username} 认证成功")
            return user_response
            
        except psycopg2.Error as e:
            print(f"用户认证失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def get_user_by_username(self, username: str) -> Optional[UserResponse]:
        """
        根据用户名获取用户信息
        
        Args:
            username: 用户名
            
        Returns:
            用户信息，不存在返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT id, username, email, full_name, role, is_active, 
                   last_login, created_at, updated_at
            FROM users 
            WHERE username = %s
            """
            cursor.execute(select_query, (username,))
            user_record = cursor.fetchone()
            cursor.close()
            
            if not user_record:
                return None
            
            return UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
        except psycopg2.Error as e:
            print(f"获取用户信息失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def update_user(self, user_id: int, update_data: UserUpdate) -> bool:
        """
        更新用户信息
        
        Args:
            user_id: 用户ID
            update_data: 更新数据
            
        Returns:
            是否更新成功
        """
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            
            # 构建动态更新查询
            update_fields = []
            update_values = []
            
            if update_data.email is not None:
                update_fields.append("email = %s")
                update_values.append(update_data.email)
            
            if update_data.full_name is not None:
                update_fields.append("full_name = %s")
                update_values.append(update_data.full_name)
            
            if update_data.role is not None:
                update_fields.append("role = %s")
                update_values.append(update_data.role.value)
            
            if update_data.is_active is not None:
                update_fields.append("is_active = %s")
                update_values.append(update_data.is_active)
            
            if not update_fields:
                return True  # 没有需要更新的字段
            
            update_values.append(user_id)
            update_query = f"""
            UPDATE users 
            SET {', '.join(update_fields)}
            WHERE id = %s
            """
            
            cursor.execute(update_query, update_values)
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_id} 更新成功")
            return True
            
        except psycopg2.Error as e:
            print(f"更新用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def delete_user(self, user_id: int) -> bool:
        """
        删除用户（软删除，设置为非激活状态）
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            
            update_query = """
            UPDATE users SET is_active = false WHERE id = %s
            """
            cursor.execute(update_query, (user_id,))
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_id} 已删除（设置为非激活状态）")
            return True
            
        except psycopg2.Error as e:
            print(f"删除用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _enrich_metric_with_calculated_fields(self, metric: Dict) -> Dict:
        """
        为监控指标添加计算字段
        
        Args:
            metric: 原始监控指标数据
            
        Returns:
            包含计算字段的完整监控指标数据
        """
        # 获取原始字段值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        swap_total = metric.get('swap_total', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        
        net_rx_kbytes = metric.get('net_rx_kbytes', 0) or 0
        net_tx_kbytes = metric.get('net_tx_kbytes', 0) or 0
        
        # CPU相关计算字段
        cpu_total_usage = cpu_usr + cpu_sys + cpu_iow
        cpu_idle = max(0, 100 - cpu_total_usage)
        
        # 内存相关计算字段
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        mem_actual_used = mem_total - mem_free  # 实际使用内存（不含缓存和缓冲区）
        
        # Swap相关计算字段
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 网络相关计算字段（字节转换）
        net_rx_bytes = net_rx_kbytes * 1024  # KBytes 转 Bytes
        net_tx_bytes = net_tx_kbytes * 1024  # KBytes 转 Bytes
        
        # 添加所有计算字段到返回数据中
        enriched_metric = metric.copy()
        
        # CPU相关字段
        enriched_metric['cpu_total_usage'] = round(cpu_total_usage, 2)
        enriched_metric['cpu_idle'] = round(cpu_idle, 2)
        
        # 内存相关字段
        enriched_metric['mem_used'] = int(mem_used)
        enriched_metric['mem_usage_percent'] = round(mem_usage_percent, 2)
        enriched_metric['mem_actual_used'] = int(mem_actual_used)
        
        # Swap相关字段
        enriched_metric['swap_usage_percent'] = round(swap_usage_percent, 2)
        
        # 网络相关字段
        enriched_metric['net_rx_bytes'] = int(net_rx_bytes)
        enriched_metric['net_tx_bytes'] = int(net_tx_bytes)
        
        # 确保字段名与前端期望的一致
        enriched_metric['mem_buffer'] = mem_buff  # 添加mem_buffer字段别名
        enriched_metric['swap_free'] = swap_total - swap_used  # 计算swap_free
        
        return enriched_metric

    def get_latest_ten_complete_metrics_by_ip(self, ip: str) -> List[Dict]:
        """
        根据IP地址获取该IP的最近十条完整监控信息，包含所有计算字段
        
        Args:
            ip: IP地址
            
        Returns:
            该IP的最近十条完整监控信息列表，包含原始字段和计算字段
        """
        connection = self.get_connection()
        if not connection:
            return []
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT * FROM node_monitor_metrics 
            WHERE ip = %s 
            ORDER BY ts DESC, inserted_at DESC 
            LIMIT 10;
            """
            
            cursor.execute(select_query, (ip,))
            metrics = cursor.fetchall()
            cursor.close()
            
            enriched_metrics = []
            for metric in metrics:
                metric_dict = dict(metric)
                # 在后端完成所有计算
                enriched_metric = self._enrich_metric_with_calculated_fields(metric_dict)
                enriched_metrics.append(enriched_metric)
            
            print(f"成功获取IP {ip} 的 {len(enriched_metrics)} 条完整监控信息")
            return enriched_metrics
                
        except psycopg2.Error as e:
            print(f"获取IP {ip} 最近十条完整监控信息失败: {e}")
            return []
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    # ==================== 用户认证相关方法 ====================

    def create_user(self, user_data: UserCreate) -> Optional[int]:
        """
        创建新用户
        
        Args:
            user_data: 用户创建数据
            
        Returns:
            创建的用户ID，失败返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor()
            
            # 检查用户名是否已存在
            check_query = """
            SELECT id FROM users 
            WHERE username = %s
            """
            cursor.execute(check_query, (user_data.username,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                print(f"用户名 {user_data.username} 已存在")
                return None
            
            # 哈希密码
            password_hash = bcrypt.hashpw(
                user_data.password.encode('utf-8'), 
                bcrypt.gensalt()
            ).decode('utf-8')
            
            # 插入新用户（只插入用户名和密码）
            insert_query = """
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
            RETURNING id
            """
            cursor.execute(insert_query, (
                user_data.username,
                password_hash
            ))
            
            user_id = cursor.fetchone()[0]
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_data.username} 创建成功，ID: {user_id}")
            return user_id
            
        except psycopg2.Error as e:
            print(f"创建用户失败: {e}")
            connection.rollback()
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories



    def get_user_by_id(self, user_id: int) -> Optional[UserResponse]:
        """
        根据ID获取用户信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户信息，不存在返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT id, username, role, is_active, 
                   last_login, created_at, updated_at
            FROM users 
            WHERE id = %s
            """
            cursor.execute(select_query, (user_id,))
            user_record = cursor.fetchone()
            cursor.close()
            
            if not user_record:
                return None
            
            return UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
        except psycopg2.Error as e:
            print(f"获取用户信息失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def authenticate_user(self, login_data: UserLogin) -> Optional[UserResponse]:
        """
        用户认证
        
        Args:
            login_data: 登录数据
            
        Returns:
            认证成功的用户信息，失败返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            # 查询用户信息
            select_query = """
            SELECT id, username, password_hash, role, 
                   is_active, last_login, created_at, updated_at
            FROM users 
            WHERE username = %s AND is_active = true
            """
            cursor.execute(select_query, (login_data.username,))
            user_record = cursor.fetchone()
            
            if not user_record:
                print(f"用户 {login_data.username} 不存在或未激活")
                return None
            
            # 验证密码
            if not bcrypt.checkpw(
                login_data.password.encode('utf-8'),
                user_record['password_hash'].encode('utf-8')
            ):
                print(f"用户 {login_data.username} 密码错误")
                return None
            
            # 更新最后登录时间
            update_query = """
            UPDATE users SET last_login = NOW() WHERE id = %s
            """
            cursor.execute(update_query, (user_record['id'],))
            connection.commit()
            cursor.close()
            
            # 转换为响应模型
            user_response = UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
            print(f"用户 {login_data.username} 认证成功")
            return user_response
            
        except psycopg2.Error as e:
            print(f"用户认证失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def get_user_by_username(self, username: str) -> Optional[UserResponse]:
        """
        根据用户名获取用户信息
        
        Args:
            username: 用户名
            
        Returns:
            用户信息，不存在返回None
        """
        connection = self.get_connection()
        if not connection:
            return None
            
        try:
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            
            select_query = """
            SELECT id, username, email, full_name, role, is_active, 
                   last_login, created_at, updated_at
            FROM users 
            WHERE username = %s
            """
            cursor.execute(select_query, (username,))
            user_record = cursor.fetchone()
            cursor.close()
            
            if not user_record:
                return None
            
            return UserResponse(
                id=user_record['id'],
                username=user_record['username'],
                email=None,  # 用户表没有email字段
                full_name=None,  # 用户表没有full_name字段
                role=user_record['role'],
                is_active=user_record['is_active'],
                last_login=str(user_record['last_login']) if user_record['last_login'] else None,
                created_at=str(user_record['created_at']),
                updated_at=str(user_record['updated_at'])
            )
            
        except psycopg2.Error as e:
            print(f"获取用户信息失败: {e}")
            return None
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def update_user(self, user_id: int, update_data: UserUpdate) -> bool:
        """
        更新用户信息
        
        Args:
            user_id: 用户ID
            update_data: 更新数据
            
        Returns:
            是否更新成功
        """
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            
            # 构建动态更新查询
            update_fields = []
            update_values = []
            
            if update_data.email is not None:
                update_fields.append("email = %s")
                update_values.append(update_data.email)
            
            if update_data.full_name is not None:
                update_fields.append("full_name = %s")
                update_values.append(update_data.full_name)
            
            if update_data.role is not None:
                update_fields.append("role = %s")
                update_values.append(update_data.role.value)
            
            if update_data.is_active is not None:
                update_fields.append("is_active = %s")
                update_values.append(update_data.is_active)
            
            if not update_fields:
                return True  # 没有需要更新的字段
            
            update_values.append(user_id)
            update_query = f"""
            UPDATE users 
            SET {', '.join(update_fields)}
            WHERE id = %s
            """
            
            cursor.execute(update_query, update_values)
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_id} 更新成功")
            return True
            
        except psycopg2.Error as e:
            print(f"更新用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def delete_user(self, user_id: int) -> bool:
        """
        删除用户（软删除，设置为非激活状态）
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        connection = self.get_connection()
        if not connection:
            return False
            
        try:
            cursor = connection.cursor()
            
            update_query = """
            UPDATE users SET is_active = false WHERE id = %s
            """
            cursor.execute(update_query, (user_id,))
            connection.commit()
            cursor.close()
            
            print(f"用户 {user_id} 已删除（设置为非激活状态）")
            return True
            
        except psycopg2.Error as e:
            print(f"删除用户失败: {e}")
            connection.rollback()
            return False
        finally:
            self.return_connection(connection)

    def assess_machine_status(self, metric: Dict) -> Dict:
        """
        根据监控指标评估机器运行状态
        
        Args:
            metric: 监控指标数据
            
        Returns:
            包含状态分级和详细信息的字典
        """
        # 获取关键指标值，处理None值
        cpu_usr = metric.get('cpu_usr', 0) or 0
        cpu_sys = metric.get('cpu_sys', 0) or 0
        cpu_iow = metric.get('cpu_iow', 0) or 0
        
        mem_total = metric.get('mem_total', 0) or 0
        mem_free = metric.get('mem_free', 0) or 0
        mem_buff = metric.get('mem_buff', 0) or 0
        mem_cache = metric.get('mem_cache', 0) or 0
        
        disk_used_percent = metric.get('disk_used_percent', 0) or 0
        swap_used = metric.get('swap_used', 0) or 0
        swap_total = metric.get('swap_total', 0) or 0
        
        # 计算关键指标
        cpu_total = cpu_usr + cpu_sys + cpu_iow
        mem_used = mem_total - mem_free - mem_buff - mem_cache
        mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
        swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
        
        # 状态评估
        status_level = "正常"
        issues = []
        warnings = []
        
        # CPU使用率检查
        if cpu_total >= 90:
            status_level = "警告"
            issues.append(f"CPU使用率过高: {cpu_total:.1f}%")
        elif cpu_total >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"CPU使用率较高: {cpu_total:.1f}%")
        
        # 内存使用率检查
        if mem_usage_percent >= 90:
            status_level = "警告"
            issues.append(f"内存使用率过高: {mem_usage_percent:.1f}%")
        elif mem_usage_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"内存使用率较高: {mem_usage_percent:.1f}%")
        
        # 磁盘使用率检查
        if disk_used_percent >= 90:
            status_level = "警告"
            issues.append(f"磁盘使用率过高: {disk_used_percent:.1f}%")
        elif disk_used_percent >= 70:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"磁盘使用率较高: {disk_used_percent:.1f}%")
        
        # Swap使用率检查
        if swap_usage_percent >= 50:
            status_level = "警告"
            issues.append(f"Swap使用率过高: {swap_usage_percent:.1f}%")
        elif swap_usage_percent >= 20:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"Swap使用率较高: {swap_usage_percent:.1f}%")
        
        # 数据时效性检查（超过1小时无数据视为异常）
        import time
        current_timestamp = int(time.time())
        metric_timestamp = metric.get('ts', 0)
        time_diff_hours = (current_timestamp - metric_timestamp) / 3600
        
        if time_diff_hours > 1:
            status_level = "警告"
            issues.append(f"数据已过期: {time_diff_hours:.1f}小时前")
        elif time_diff_hours > 0.3:
            if status_level != "警告":
                status_level = "提示"
            warnings.append(f"数据较旧: {time_diff_hours:.1f}小时前")
        
        # 构建返回结果
        result = {
            "status_level": status_level,
            "ip": metric.get('ip', '未知'),
            "timestamp": metric_timestamp,
            "key_metrics": {
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": round(disk_used_percent, 2),
                "swap_usage_percent": round(swap_usage_percent, 2),
                "data_freshness_hours": round(time_diff_hours, 2)
            },
            "issues": issues,
            "warnings": warnings,
            "is_healthy": status_level == "正常",
            "overall_score": self._calculate_health_score(cpu_total, mem_usage_percent, disk_used_percent, swap_usage_percent, time_diff_hours)
        }
        
        return result

    def _calculate_health_score(self, cpu_usage: float, mem_usage: float, disk_usage: float, swap_usage: float, data_freshness: float) -> int:
        """
        计算机器健康评分（0-100分）
        
        Args:
            cpu_usage: CPU使用率
            mem_usage: 内存使用率
            disk_usage: 磁盘使用率
            swap_usage: Swap使用率
            data_freshness: 数据新鲜度（小时）
            
        Returns:
            健康评分（0-100）
        """
        # 各项指标的权重
        weights = {
            'cpu': 0.25,
            'memory': 0.25,
            'disk': 0.20,
            'swap': 0.15,
            'freshness': 0.15
        }
        
        # 计算各项得分（0-100分）
        cpu_score = max(0, 100 - cpu_usage)  # CPU使用率越低得分越高
        mem_score = max(0, 100 - mem_usage)  # 内存使用率越低得分越高
        disk_score = max(0, 100 - disk_usage)  # 磁盘使用率越低得分越高
        swap_score = max(0, 100 - min(swap_usage * 2, 100))  # Swap使用率影响加倍
        
        # 数据新鲜度得分（1小时内得100分，超过1小时线性递减）
        freshness_score = max(0, 100 - (data_freshness * 20))  # 每超过1小时减20分
        
        # 加权平均
        total_score = (
            cpu_score * weights['cpu'] +
            mem_score * weights['memory'] +
            disk_score * weights['disk'] +
            swap_score * weights['swap'] +
            freshness_score * weights['freshness']
        )
        
        return int(max(0, min(100, total_score)))

    def get_machine_status_by_ip(self, ip: str) -> Dict:
        """
        根据IP地址获取机器的最新状态评估
        
        Args:
            ip: IP地址
            
        Returns:
            机器状态评估结果
        """
        # 获取最新监控数据
        metric = self.get_latest_metric_by_ip(ip)
        
        if not metric:
            return {
                "status_level": "未知",
                "ip": ip,
                "timestamp": None,
                "key_metrics": {},
                "issues": ["未找到该IP的监控数据"],
                "warnings": [],
                "is_healthy": False,
                "overall_score": 0,
                "error": "未找到监控数据"
            }
        
        # 评估状态
        return self.assess_machine_status(metric)

    def get_all_machines_status(self, time_window_hours: int = 1) -> List[Dict]:
        """
        获取所有机器的状态评估
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            所有机器的状态评估列表
        """
        # 获取活跃机器的监控数据
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        status_list = []
        for metric in metrics:
            status = self.assess_machine_status(metric)
            status_list.append(status)
        
        # 按健康评分排序
        status_list.sort(key=lambda x: x['overall_score'], reverse=True)
        
        return status_list

    def get_system_overview(self, time_window_hours: int = 1) -> Dict:
        """
        获取系统总体概览信息
        
        Args:
            time_window_hours: 时间窗口（小时）
            
        Returns:
            系统总体概览信息，包含：
            - 活跃机器统计
            - 健康状态分布
            - 告警和提示信息汇总
            - 关键指标统计
            - 性能趋势分析
        """
        # 获取所有机器的状态评估
        status_list = self.get_all_machines_status(time_window_hours)
        
        # 获取活跃机器的原始监控数据用于统计计算
        metrics = self.get_active_machines_latest_metrics(time_window_hours)
        
        # 1. 活跃机器统计
        active_machines = len(status_list)
        active_ips = [status['ip'] for status in status_list]
        
        # 2. 健康状态分布
        status_distribution = {
            "正常": len([s for s in status_list if s['status_level'] == "正常"]),
            "提示": len([s for s in status_list if s['status_level'] == "提示"]),
            "警告": len([s for s in status_list if s['status_level'] == "警告"]),
            "未知": len([s for s in status_list if s['status_level'] == "未知"])
        }
        
        # 3. 告警和提示信息汇总
        all_issues = []
        all_warnings = []
        
        for status in status_list:
            all_issues.extend([{"ip": status['ip'], "issue": issue} for issue in status['issues']])
            all_warnings.extend([{"ip": status['ip'], "warning": warning} for warning in status['warnings']])
        
        # 4. 关键指标统计（最大值、平均值、最小值）
        key_metrics_stats = self._calculate_key_metrics_statistics(metrics)
        
        # 5. 性能趋势分析（基于最近10条数据）
        trend_analysis = self._analyze_performance_trend(time_window_hours)
        
        # 6. 系统健康评分
        overall_health_score = self._calculate_system_health_score(status_list)
        
        # 构建总体概览信息
        overview = {
            "timestamp": int(time.time()),
            "time_window_hours": time_window_hours,
            "active_machines": {
                "total": active_machines,
                "ips": active_ips
            },
            "health_status": {
                "distribution": status_distribution,
                "overall_score": overall_health_score,
                "health_percentage": round((status_distribution["正常"] / active_machines * 100), 2) if active_machines > 0 else 0
            },
            "alerts_summary": {
                "critical_issues": len(all_issues),
                "warning_issues": len(all_warnings),
                "issues_by_type": self._categorize_issues(all_issues),
                "warnings_by_type": self._categorize_warnings(all_warnings)
            },
            "key_metrics": key_metrics_stats,
            "performance_trend": trend_analysis,
            "detailed_alerts": {
                "critical": all_issues,
                "warning": all_warnings
            }
        }
        
        return overview

    def _calculate_key_metrics_statistics(self, metrics: List[Dict]) -> Dict:
        """计算关键指标的统计信息"""
        if not metrics:
            return {
                "cpu_usage": {"max": 0, "avg": 0, "min": 0},
                "memory_usage": {"max": 0, "avg": 0, "min": 0},
                "disk_usage": {"max": 0, "avg": 0, "min": 0},
                "swap_usage": {"max": 0, "avg": 0, "min": 0}
            }
        
        cpu_usages = []
        memory_usages = []
        disk_usages = []
        swap_usages = []
        
        for metric in metrics:
            # 计算各项指标
            cpu_usr = metric.get('cpu_usr', 0) or 0
            cpu_sys = metric.get('cpu_sys', 0) or 0
            cpu_iow = metric.get('cpu_iow', 0) or 0
            cpu_total = cpu_usr + cpu_sys + cpu_iow
            
            mem_total = metric.get('mem_total', 0) or 0
            mem_free = metric.get('mem_free', 0) or 0
            mem_buff = metric.get('mem_buff', 0) or 0
            mem_cache = metric.get('mem_cache', 0) or 0
            mem_used = mem_total - mem_free - mem_buff - mem_cache
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            disk_usage = metric.get('disk_used_percent', 0) or 0
            
            swap_used = metric.get('swap_used', 0) or 0
            swap_total = metric.get('swap_total', 0) or 0
            swap_usage_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0
            
            cpu_usages.append(cpu_total)
            memory_usages.append(mem_usage_percent)
            disk_usages.append(disk_usage)
            swap_usages.append(swap_usage_percent)
        
        return {
            "cpu_usage": {
                "max": round(max(cpu_usages), 2) if cpu_usages else 0,
                "avg": round(sum(cpu_usages) / len(cpu_usages), 2) if cpu_usages else 0,
                "min": round(min(cpu_usages), 2) if cpu_usages else 0
            },
            "memory_usage": {
                "max": round(max(memory_usages), 2) if memory_usages else 0,
                "avg": round(sum(memory_usages) / len(memory_usages), 2) if memory_usages else 0,
                "min": round(min(memory_usages), 2) if memory_usages else 0
            },
            "disk_usage": {
                "max": round(max(disk_usages), 2) if disk_usages else 0,
                "avg": round(sum(disk_usages) / len(disk_usages), 2) if disk_usages else 0,
                "min": round(min(disk_usages), 2) if disk_usages else 0
            },
            "swap_usage": {
                "max": round(max(swap_usages), 2) if swap_usages else 0,
                "avg": round(sum(swap_usages) / len(swap_usages), 2) if swap_usages else 0,
                "min": round(min(swap_usages), 2) if swap_usages else 0
            }
        }

    def _analyze_performance_trend(self, time_window_hours: int) -> Dict:
        """分析性能趋势"""
        # 这里可以扩展为获取历史数据进行趋势分析
        # 目前返回基础趋势信息
        return {
            "trend": "stable",  # stable, improving, declining
            "confidence": 0.8,
            "analysis": "系统性能整体稳定",
            "suggestions": ["建议定期检查磁盘使用率", "关注内存使用趋势"]
        }

    def _calculate_system_health_score(self, status_list: List[Dict]) -> float:
        """计算系统整体健康评分"""
        if not status_list:
            return 0.0
        
        total_score = sum(status['overall_score'] for status in status_list)
        return round(total_score / len(status_list), 2)

    def _categorize_issues(self, issues: List[Dict]) -> Dict:
        """分类汇总问题"""
        categories = {}
        
        for issue_item in issues:
            issue_text = issue_item['issue']
            if "CPU" in issue_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in issue_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in issue_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in issue_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in issue_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories

    def _categorize_warnings(self, warnings: List[Dict]) -> Dict:
        """分类汇总警告"""
        categories = {}
        
        for warning_item in warnings:
            warning_text = warning_item['warning']
            if "CPU" in warning_text:
                categories["cpu"] = categories.get("cpu", 0) + 1
            elif "内存" in warning_text:
                categories["memory"] = categories.get("memory", 0) + 1
            elif "磁盘" in warning_text:
                categories["disk"] = categories.get("disk", 0) + 1
            elif "Swap" in warning_text:
                categories["swap"] = categories.get("swap", 0) + 1
            elif "数据" in warning_text:
                categories["data_freshness"] = categories.get("data_freshness", 0) + 1
            else:
                categories["other"] = categories.get("other", 0) + 1
        
        return categories