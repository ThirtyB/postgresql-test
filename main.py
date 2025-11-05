from fastapi import FastAPI, Query
from database import DatabaseManager
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os


app = FastAPI()

class CreateUserRequest(BaseModel):
    name: str
    email: str
    age: int
    password: str

class CreateUserResponse(BaseModel):
    id: int
    status: str

class ChangeUserRequest(BaseModel):
    id: int
    name: str
    age: int
    email: str
    password: str

class ChangeUserResponse(BaseModel):
    result: float | str
    status: str

class DeleteUserRequest(BaseModel):
    id: int

class DeleteUserResponse(BaseModel):
    result: float | str
    status: str

class NodeMonitorMetric(BaseModel):
    id: int
    ip: str
    ts: int
    cpu_usr: Optional[float] = None
    cpu_sys: Optional[float] = None
    cpu_iow: Optional[float] = None
    mem_total: Optional[int] = None
    mem_free: Optional[int] = None
    mem_buff: Optional[int] = None
    mem_cache: Optional[int] = None
    swap_total: Optional[int] = None
    swap_used: Optional[int] = None
    swap_in: Optional[int] = None
    swap_out: Optional[int] = None
    system_in: Optional[int] = None
    system_cs: Optional[int] = None
    disk_name: Optional[str] = None
    disk_total: Optional[int] = None
    disk_used: Optional[int] = None
    disk_used_percent: Optional[float] = None
    disk_iops: Optional[int] = None
    disk_r: Optional[int] = None
    disk_w: Optional[int] = None
    net_rx_kbytes: Optional[float] = None
    net_tx_kbytes: Optional[float] = None
    net_rx_kbps: Optional[float] = None
    net_tx_kbps: Optional[float] = None
    version: Optional[str] = None
    inserted_at: datetime

class PaginatedMetricsResponse(BaseModel):
    data: List[NodeMonitorMetric]
    total: int
    page: int
    page_size: int
    total_pages: int

class StatisticsResponse(BaseModel):
    count: Optional[int] = None
    avg_cpu_total: Optional[float] = None
    max_cpu_total: Optional[float] = None
    min_cpu_total: Optional[float] = None
    avg_mem_usage_percent: Optional[float] = None
    max_mem_usage_percent: Optional[float] = None
    avg_disk_used_percent: Optional[float] = None
    max_disk_used_percent: Optional[float] = None
    avg_net_rx_kbps: Optional[float] = None
    max_net_rx_kbps: Optional[float] = None
    avg_net_tx_kbps: Optional[float] = None
    max_net_tx_kbps: Optional[float] = None


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    db = DatabaseManager()
    if not db.connect():
        return {"message": "Failed to connect to database"}
    user = db.get_user_by_id(user_id)
    if not user:
        return {"message": "User not found"}
    return user

@app.post("/users/create", response_model=CreateUserResponse)
async def create_user(request: CreateUserRequest):
    db = DatabaseManager()
    if not db.connect():
        return CreateUserResponse(id=None, status="Failed to connect to database")
    try:
        user_id = db.insert_user(request.id, request.name, request.email, request.age, request.password)
        return CreateUserResponse(id=user_id, status="success")
    except Exception as e:
        return CreateUserResponse(id=None, status=f"Failed to create user: {e}")
    finally:
        db.disconnect()


@app.post("/users/change", response_model=ChangeUserResponse)
async def change_user(request: ChangeUserRequest):
    db = DatabaseManager()
    if not db.connect():
        return {
            "result": "无法连接数据库",
            "status": "error"
        }
    try:
        user_id = db.update_user(request.id, email=request.email, name=request.name, age=request.age, password=request.password)
        return {
            "result": 200,
            "status": "success"
        }
    except Exception as e:
        return {
            "result": e,
            "status": "error"
        }
    finally:
        db.disconnect()

@app.post("/users/delete", response_model=DeleteUserResponse)
async def delete_user(request: DeleteUserRequest):
    db = DatabaseManager()
    if not db.connect():
        return {
            "result": "无法连接数据库",
            "status": "error"
        }
    try:
        user_id = db.delete_user(request.id)
        return {
            "result": 200,
            "status": "success"
        }
    except Exception as e:
        return {
            "result": e,
            "status": "error"
        }
    finally:
        db.disconnect()

@app.get("/monitor-metrics/latest", response_model=list[NodeMonitorMetric])
async def get_latest_monitor_metrics(limit: int = Query(default=5, ge=1, le=100)):
    """获取最新的监控指标数据"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        metrics = db.get_latest_monitor_metrics(limit=limit)
        return metrics
    except Exception as e:
        print(f"获取监控指标失败: {e}")
        return []
    finally:
        db.disconnect()

@app.get("/monitor-metrics/ip/{ip}", response_model=list[NodeMonitorMetric])
async def get_metrics_by_ip(ip: str, limit: int = Query(default=10, ge=1, le=100)):
    """根据IP查询监控指标数据"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        metrics = db.get_metrics_by_ip(ip=ip, limit=limit)
        return metrics
    except Exception as e:
        print(f"根据IP查询监控指标失败: {e}")
        return []
    finally:
        db.disconnect()

@app.get("/monitor-metrics/ip/{ip}/latest", response_model=Optional[NodeMonitorMetric])
async def get_latest_metric_by_ip(ip: str):
    """获取指定IP的最新一条监控指标数据"""
    db = DatabaseManager()
    if not db.connect():
        return None
    try:
        metric = db.get_latest_metric_by_ip(ip=ip)
        return metric
    except Exception as e:
        print(f"获取IP最新监控指标失败: {e}")
        return None
    finally:
        db.disconnect()

@app.get("/monitor-metrics/time-range", response_model=list[NodeMonitorMetric])
async def get_metrics_by_time_range(
    start_ts: int = Query(..., description="开始时间戳"),
    end_ts: int = Query(..., description="结束时间戳"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数限制")
):
    """根据时间范围查询监控指标数据"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        metrics = db.get_metrics_by_time_range(start_ts=start_ts, end_ts=end_ts, ip=ip, limit=limit)
        return metrics
    except Exception as e:
        print(f"根据时间范围查询监控指标失败: {e}")
        return []
    finally:
        db.disconnect()

@app.get("/monitor-metrics/paginated", response_model=PaginatedMetricsResponse)
async def get_metrics_paginated(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）")
):
    """分页查询监控指标数据"""
    db = DatabaseManager()
    if not db.connect():
        return PaginatedMetricsResponse(data=[], total=0, page=page, page_size=page_size, total_pages=0)
    try:
        result = db.get_metrics_paginated(page=page, page_size=page_size, ip=ip)
        return result
    except Exception as e:
        print(f"分页查询监控指标失败: {e}")
        return PaginatedMetricsResponse(data=[], total=0, page=page, page_size=page_size, total_pages=0)
    finally:
        db.disconnect()

@app.get("/monitor-metrics/ips", response_model=list[str])
async def get_all_ips():
    """获取所有监控的IP列表"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        ips = db.get_all_ips()
        return ips
    except Exception as e:
        print(f"获取IP列表失败: {e}")
        return []
    finally:
        db.disconnect()

@app.get("/monitor-metrics/statistics", response_model=Optional[StatisticsResponse])
async def get_metrics_statistics(
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    start_ts: Optional[int] = Query(default=None, description="开始时间戳（可选）"),
    end_ts: Optional[int] = Query(default=None, description="结束时间戳（可选）")
):
    """获取监控指标的统计信息（平均值、最大值、最小值）"""
    db = DatabaseManager()
    if not db.connect():
        return None
    try:
        stats = db.get_metrics_statistics(ip=ip, start_ts=start_ts, end_ts=end_ts)
        if stats:
            return StatisticsResponse(**stats)
        return None
    except Exception as e:
        print(f"获取统计信息失败: {e}")
        return None
    finally:
        db.disconnect()

@app.get("/monitor-metrics/high-cpu", response_model=list[NodeMonitorMetric])
async def get_high_cpu_metrics(
    cpu_threshold: float = Query(default=80.0, ge=0, le=100, description="CPU使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制")
):
    """查询CPU使用率超过阈值的监控指标"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        metrics = db.get_high_cpu_metrics(cpu_threshold=cpu_threshold, limit=limit)
        return metrics
    except Exception as e:
        print(f"查询高CPU使用率监控指标失败: {e}")
        return []
    finally:
        db.disconnect()

@app.get("/monitor-metrics/high-memory", response_model=list[NodeMonitorMetric])
async def get_high_memory_metrics(
    mem_threshold: float = Query(default=80.0, ge=0, le=100, description="内存使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制")
):
    """查询内存使用率超过阈值的监控指标"""
    db = DatabaseManager()
    if not db.connect():
        return []
    try:
        metrics = db.get_high_memory_metrics(mem_threshold=mem_threshold, limit=limit)
        return metrics
    except Exception as e:
        print(f"查询高内存使用率监控指标失败: {e}")
        return []
    finally:
        db.disconnect()
