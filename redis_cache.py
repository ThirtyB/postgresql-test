import redis
import json
import pickle
from typing import Any, Optional, Callable, Union
from functools import wraps
import time
from datetime import datetime, timedelta
from config import get_redis_config


class RedisCacheManager:
    """Redis缓存管理器，支持多后端访问"""
    
    def __init__(self):
        self.redis_config = get_redis_config()
        self._redis_client = None
        self._redis_clients = {}  # 多后端连接池
    
    @property
    def client(self):
        """获取默认Redis客户端"""
        if self._redis_client is None:
            self._redis_client = self._create_client()
        return self._redis_client
    
    def get_client(self, backend_name: str = "default") -> redis.Redis:
        """获取指定后端的Redis客户端"""
        if backend_name not in self._redis_clients:
            # 可以根据不同后端配置不同的连接参数
            config = self.redis_config.copy()
            # 这里可以根据backend_name调整配置
            if backend_name != "default":
                config["db"] = int(config.get("db", 0)) + 1  # 不同后端使用不同数据库
            
            self._redis_clients[backend_name] = redis.Redis(**config)
        return self._redis_clients[backend_name]
    
    def _create_client(self) -> redis.Redis:
        """创建Redis客户端"""
        try:
            client = redis.Redis(**self.redis_config)
            # 测试连接
            client.ping()
            return client
        except redis.ConnectionError as e:
            print(f"Redis连接失败: {e}")
            # 返回一个模拟的客户端，避免服务中断
            return self._create_mock_client()
    
    def _create_mock_client(self):
        """创建模拟Redis客户端（当Redis不可用时）"""
        class MockRedis:
            def __init__(self):
                self._cache = {}
                self.connected = False
            
            def ping(self):
                return False
            
            def get(self, key):
                if key in self._cache:
                    data, expiry = self._cache[key]
                    if expiry and time.time() > expiry:
                        del self._cache[key]
                        return None
                    return data
                return None
            
            def set(self, key, value, ex=None):
                expiry = time.time() + ex if ex else None
                self._cache[key] = (value, expiry)
                return True
            
            def delete(self, *keys):
                count = 0
                for key in keys:
                    if key in self._cache:
                        del self._cache[key]
                        count += 1
                return count
            
            def exists(self, key):
                if key in self._cache:
                    data, expiry = self._cache[key]
                    if expiry and time.time() > expiry:
                        del self._cache[key]
                        return 0
                    return 1
                return 0
            
            def expire(self, key, time):
                if key in self._cache:
                    data, _ = self._cache[key]
                    self._cache[key] = (data, time.time() + time)
                    return True
                return False
        
        return MockRedis()
    
    def set_cache(self, key: str, value: Any, expire_seconds: int = 60, backend: str = "default") -> bool:
        """设置缓存"""
        try:
            client = self.get_client(backend)
            serialized_value = pickle.dumps(value)
            # 使用二进制模式存储，避免编码问题
            return client.set(key, serialized_value, ex=expire_seconds)
        except Exception as e:
            print(f"设置缓存失败: {e}")
            return False
    
    def get_cache(self, key: str, backend: str = "default") -> Optional[Any]:
        """获取缓存"""
        try:
            client = self.get_client(backend)
            cached_data = client.get(key)
            if cached_data:
                # 处理二进制数据
                if isinstance(cached_data, bytes):
                    return pickle.loads(cached_data)
                # 如果是字符串，尝试解码
                elif isinstance(cached_data, str):
                    return pickle.loads(cached_data.encode('utf-8'))
            return None
        except Exception as e:
            print(f"获取缓存失败: {e}")
            return None
    
    def delete_cache(self, key: str, backend: str = "default") -> bool:
        """删除缓存"""
        try:
            client = self.get_client(backend)
            return bool(client.delete(key))
        except Exception as e:
            print(f"删除缓存失败: {e}")
            return False
    
    def exists(self, key: str, backend: str = "default") -> bool:
        """检查缓存是否存在"""
        try:
            client = self.get_client(backend)
            return bool(client.exists(key))
        except Exception as e:
            print(f"检查缓存存在失败: {e}")
            return False
    
    def clear_pattern(self, pattern: str, backend: str = "default") -> int:
        """清除匹配模式的缓存"""
        try:
            client = self.get_client(backend)
            keys = client.keys(pattern)
            if keys:
                return client.delete(*keys)
            return 0
        except Exception as e:
            print(f"清除模式缓存失败: {e}")
            return 0


# 创建全局缓存管理器实例
cache_manager = RedisCacheManager()


def cache_decorator(expire_seconds: int = 60, key_prefix: str = "", backend: str = "default"):
    """
    缓存装饰器
    
    Args:
        expire_seconds: 缓存过期时间（秒）
        key_prefix: 缓存键前缀
        backend: Redis后端名称
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # 尝试从缓存获取
            cached_result = cache_manager.get_cache(cache_key, backend)
            if cached_result is not None:
                return cached_result
            
            # 执行函数获取结果
            result = await func(*args, **kwargs)
            
            # 设置缓存
            cache_manager.set_cache(cache_key, result, expire_seconds, backend)
            
            return result
        
        return wrapper
    return decorator


def token_cache_decorator(expire_seconds: int = 21600, backend: str = "tokens"):  # 6小时
    """
    Token缓存装饰器
    
    Args:
        expire_seconds: Token缓存过期时间（秒）
        backend: Redis后端名称
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成Token缓存键
            username = kwargs.get('username') or (args[1].username if len(args) > 1 else None)
            if username:
                cache_key = f"token:{username}"
                
                # 尝试从缓存获取Token
                cached_token = cache_manager.get_cache(cache_key, backend)
                if cached_token is not None:
                    return cached_token
                
                # 生成新Token
                result = await func(*args, **kwargs)
                
                # 设置Token缓存
                cache_manager.set_cache(cache_key, result, expire_seconds, backend)
                
                return result
            
            # 如果没有用户名，直接执行函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


class CacheMetrics:
    """缓存监控指标"""
    
    def __init__(self):
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_errors = 0
        self.last_reset = datetime.now()
    
    def record_hit(self):
        """记录缓存命中"""
        self.cache_hits += 1
    
    def record_miss(self):
        """记录缓存未命中"""
        self.cache_misses += 1
    
    def record_error(self):
        """记录缓存错误"""
        self.cache_errors += 1
    
    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        total = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total * 100) if total > 0 else 0
        
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_errors": self.cache_errors,
            "hit_rate": round(hit_rate, 2),
            "total_requests": total,
            "last_reset": self.last_reset.isoformat(),
            "uptime_minutes": (datetime.now() - self.last_reset).total_seconds() / 60
        }
    
    def reset(self):
        """重置统计信息"""
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_errors = 0
        self.last_reset = datetime.now()


# 创建全局缓存监控实例
cache_metrics = CacheMetrics()