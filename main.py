from fastapi import FastAPI, Query, HTTPException
from database import DatabaseManager
from response_models import SuccessResponse, ErrorResponse, PaginatedResponse, ErrorCode
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os


app = FastAPI()

# 初始化数据库管理器（单例模式）
db_manager = DatabaseManager()

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
    """根路径"""
    return SuccessResponse(data={"message": "Hello World"})


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    """根据ID获取用户"""
    try:
        user = db_manager.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(data=user)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取用户失败: {str(e)}")

@app.post("/users/create")
async def create_user(request: CreateUserRequest):
    """创建用户"""
    try:
        user_id = db_manager.insert_user(request.name, request.email, request.age, request.password)
        if not user_id:
            raise HTTPException(status_code=400, detail="创建用户失败")
        return SuccessResponse(data={"id": user_id}, message="用户创建成功")
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"创建用户失败: {str(e)}")


@app.post("/users/change")
async def change_user(request: ChangeUserRequest):
    """修改用户信息"""
    try:
        success = db_manager.update_user(
            request.id, 
            email=request.email, 
            name=request.name, 
            age=request.age, 
            password=request.password
        )
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(message="用户信息更新成功")
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"更新用户失败: {str(e)}")

@app.post("/users/delete")
async def delete_user(request: DeleteUserRequest):
    """删除用户"""
    try:
        success = db_manager.delete_user(request.id)
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(message="用户删除成功")
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"删除用户失败: {str(e)}")

@app.get("/monitor-metrics/latest")
async def get_latest_monitor_metrics(limit: int = Query(default=5, ge=1, le=100)):
    """获取最新的监控指标数据"""
    try:
        metrics = db_manager.get_latest_monitor_metrics(limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取监控指标失败: {str(e)}")

@app.get("/monitor-metrics/ip/{ip}")
async def get_metrics_by_ip(ip: str, limit: int = Query(default=10, ge=1, le=100)):
    """根据IP查询监控指标数据"""
    try:
        metrics = db_manager.get_metrics_by_ip(ip=ip, limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"根据IP查询监控指标失败: {str(e)}")

@app.get("/monitor-metrics/ip/{ip}/latest")
async def get_latest_metric_by_ip(ip: str):
    """获取指定IP的最新一条监控指标数据"""
    try:
        metric = db_manager.get_latest_metric_by_ip(ip=ip)
        if not metric:
            raise HTTPException(status_code=404, detail="未找到该IP的监控数据")
        return SuccessResponse(data=metric)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取IP最新监控指标失败: {str(e)}")

@app.get("/monitor-metrics/time-range")
async def get_metrics_by_time_range(
    start_ts: int = Query(..., description="开始时间戳"),
    end_ts: int = Query(..., description="结束时间戳"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数限制")
):
    """根据时间范围查询监控指标数据"""
    try:
        metrics = db_manager.get_metrics_by_time_range(start_ts=start_ts, end_ts=end_ts, ip=ip, limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"根据时间范围查询监控指标失败: {str(e)}")

@app.get("/monitor-metrics/paginated")
async def get_metrics_paginated(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）")
):
    """分页查询监控指标数据"""
    try:
        result = db_manager.get_metrics_paginated(page=page, page_size=page_size, ip=ip)
        return PaginatedResponse(
            data=result["data"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"]
        )
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"分页查询监控指标失败: {str(e)}")

@app.get("/monitor-metrics/ips")
async def get_all_ips():
    """获取所有监控的IP列表"""
    try:
        ips = db_manager.get_all_ips()
        return SuccessResponse(data=ips)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取IP列表失败: {str(e)}")

@app.get("/monitor-metrics/statistics")
async def get_metrics_statistics(
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    start_ts: Optional[int] = Query(default=None, description="开始时间戳（可选）"),
    end_ts: Optional[int] = Query(default=None, description="结束时间戳（可选）")
):
    """获取监控指标的统计信息（平均值、最大值、最小值）"""
    try:
        stats = db_manager.get_metrics_statistics(ip=ip, start_ts=start_ts, end_ts=end_ts)
        if not stats:
            raise HTTPException(status_code=404, detail="未找到统计信息")
        return SuccessResponse(data=stats)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取统计信息失败: {str(e)}")

@app.get("/monitor-metrics/high-cpu")
async def get_high_cpu_metrics(
    cpu_threshold: float = Query(default=80.0, ge=0, le=100, description="CPU使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制")
):
    """查询CPU使用率超过阈值的监控指标"""
    try:
        metrics = db_manager.get_high_cpu_metrics(cpu_threshold=cpu_threshold, limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"查询高CPU使用率监控指标失败: {str(e)}")

@app.get("/monitor-metrics/high-memory")
async def get_high_memory_metrics(
    mem_threshold: float = Query(default=80.0, ge=0, le=100, description="内存使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制")
):
    """查询内存使用率超过阈值的监控指标"""
    try:
        metrics = db_manager.get_high_memory_metrics(mem_threshold=mem_threshold, limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"查询高内存使用率监控指标失败: {str(e)}")


@app.get("/monitor-metrics/active-machines")
async def get_active_machines_latest_metrics(
    time_window_hours: int = Query(default=1, ge=1, le=24, description="时间窗口（小时），默认为1小时")
):
    """
    获取指定时间窗口内活跃机器的最新监控指标
    
    参数:
        time_window_hours: 时间窗口（小时），默认1小时，最大24小时
        
    返回:
        每个活跃机器的最新监控指标，包含机器IP、CPU使用率、内存使用率、磁盘使用率等信息
    """
    try:
        metrics = db_manager.get_active_machines_latest_metrics(time_window_hours=time_window_hours)
        
        # 格式化返回数据，只包含关键信息
        formatted_metrics = []
        for metric in metrics:
            # 计算CPU总使用率
            cpu_total = (metric.get('cpu_usr', 0) or 0) + (metric.get('cpu_sys', 0) or 0) + (metric.get('cpu_iow', 0) or 0)
            
            # 计算内存使用率
            mem_total = metric.get('mem_total', 0) or 0
            mem_used = mem_total - (metric.get('mem_free', 0) or 0) - (metric.get('mem_buff', 0) or 0) - (metric.get('mem_cache', 0) or 0)
            mem_usage_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            formatted_metric = {
                "ip": metric.get('ip', ''),
                "timestamp": metric.get('ts', 0),
                "cpu_usage_percent": round(cpu_total, 2),
                "memory_usage_percent": round(mem_usage_percent, 2),
                "disk_usage_percent": metric.get('disk_used_percent', 0) or 0,
                "network_rx_kbps": metric.get('net_rx_kbps', 0) or 0,
                "network_tx_kbps": metric.get('net_tx_kbps', 0) or 0,
                "last_updated": metric.get('inserted_at')
            }
            formatted_metrics.append(formatted_metric)
        
        return SuccessResponse(
            data=formatted_metrics,
            message=f"成功获取{len(formatted_metrics)}个活跃机器的最新监控数据"
        )
        
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR, 
            message=f"获取活跃机器最新监控指标失败: {str(e)}"
        )


@app.get("/monitor-metrics/ip/{ip}/complete")
async def get_latest_complete_metrics_by_ip(ip: str):
    """
    根据IP地址获取该IP的最新完整监控信息
    
    参数:
        ip: IP地址
        
    返回:
        该IP的最新完整监控信息，包含所有字段：
        - 基础信息：id, ip, timestamp, version
        - CPU使用情况：cpu_usr, cpu_sys, cpu_iow
        - 内存使用情况：mem_total, mem_free, mem_buff, mem_cache
        - 交换空间：swap_total, swap_used, swap_in, swap_out
        - 系统信息：system_in, system_cs
        - 磁盘信息：disk_name, disk_total, disk_used, disk_used_percent, disk_iops, disk_r, disk_w
        - 网络信息：net_rx_kbytes, net_tx_kbytes, net_rx_kbps, net_tx_kbps
        - 时间信息：inserted_at
    """
    try:
        metric = db_manager.get_latest_complete_metrics_by_ip(ip=ip)
        
        if not metric:
            raise HTTPException(status_code=404, detail=f"未找到IP {ip} 的监控数据")
        
        # 返回完整的监控信息，包含所有字段
        return SuccessResponse(
            data=metric,
            message=f"成功获取IP {ip} 的最新完整监控信息"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR, 
            message=f"获取IP {ip} 最新完整监控信息失败: {str(e)}"
        )
