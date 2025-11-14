from fastapi import FastAPI, Query, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from database import DatabaseManager
from response_models import SuccessResponse, ErrorResponse, ErrorResponseBuilder, PaginatedResponse, ErrorCode, ErrorDetail
from auth_models import UserCreate, UserLogin, UserUpdate, UserResponse, Token
from jwt_auth import create_access_token, create_refresh_token, refresh_access_token, get_current_user, get_current_active_user, allow_admin, allow_admin_user, allow_all
from redis_cache import cache_manager, cache_decorator, cache_metrics
from pydantic import BaseModel, ValidationError
from typing import Optional, List
from datetime import datetime, timedelta
import os
import uuid


app = FastAPI()

# 初始化数据库管理器（单例模式）
db_manager = DatabaseManager()

# 全局异常处理器
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    request_id = str(uuid.uuid4())
    
    error_response = ErrorResponseBuilder.create(
        code=exc.status_code,
        message=exc.detail,
        path=str(request.url),
        request_id=request_id
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.dict()
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """数据验证异常处理器"""
    request_id = str(uuid.uuid4())
    
    # 提取验证错误详情
    errors = []
    for error in exc.errors():
        error_detail = ErrorDetail(
            field=error.get('loc', [''])[-1] if error.get('loc') else None,
            message=error.get('msg', '验证错误'),
            code=error.get('type')
        )
        errors.append(error_detail)
    
    error_response = ErrorResponseBuilder.validation_error(
        errors=errors,
        path=str(request.url),
        request_id=request_id
    )
    
    return JSONResponse(
        status_code=422,
        content=error_response.dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    request_id = str(uuid.uuid4())
    
    error_response = ErrorResponseBuilder.internal_error(
        message="服务器内部错误",
        path=str(request.url),
        request_id=request_id,
        trace_id=request_id  # 生产环境应该使用真实的trace ID
    )
    
    # 记录错误日志
    print(f"请求ID: {request_id}, 错误: {str(exc)}")
    
    return JSONResponse(
        status_code=500,
        content=error_response.dict()
    )

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
async def get_user(user_id: int, current_user: UserResponse = Depends(allow_admin), request: Request = None):
    """根据ID获取用户（仅管理员可用）"""
    request_id = str(uuid.uuid4())
    
    try:
        user = db_manager.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(data=user, request_id=request_id)
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponseBuilder.database_error(
            message=f"获取用户失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.post("/users/create")
async def create_user(request_data: CreateUserRequest, current_user: UserResponse = Depends(allow_admin), request: Request = None):
    """创建用户（仅管理员可用）"""
    request_id = str(uuid.uuid4())
    
    try:
        user_id = db_manager.insert_user(request_data.name, request_data.email, request_data.age, request_data.password)
        if not user_id:
            raise HTTPException(status_code=400, detail="创建用户失败")
        return SuccessResponse(data={"id": user_id}, message="用户创建成功", request_id=request_id)
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponseBuilder.database_error(
            message=f"创建用户失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )


@app.post("/users/change")
async def change_user(request_data: ChangeUserRequest, current_user: UserResponse = Depends(allow_admin), request: Request = None):
    """修改用户信息（仅管理员可用）"""
    request_id = str(uuid.uuid4())
    
    try:
        success = db_manager.update_user(
            request_data.id, 
            email=request_data.email, 
            name=request_data.name, 
            age=request_data.age, 
            password=request_data.password
        )
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(message="用户信息更新成功", request_id=request_id)
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponseBuilder.database_error(
            message=f"更新用户失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.post("/users/delete")
async def delete_user(request_data: DeleteUserRequest, current_user: UserResponse = Depends(allow_admin), request: Request = None):
    """删除用户（仅管理员可用）"""
    request_id = str(uuid.uuid4())
    
    try:
        success = db_manager.delete_user(request_data.id)
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")
        return SuccessResponse(message="用户删除成功", request_id=request_id)
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponseBuilder.database_error(
            message=f"删除用户失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.get("/monitor-metrics/latest")
@cache_decorator(expire_seconds=60, key_prefix="monitor_metrics")
async def get_latest_monitor_metrics(limit: int = Query(default=5, ge=1, le=100), current_user: UserResponse = Depends(allow_all), request: Request = None):
    """获取最新的监控指标数据（需要认证，1分钟缓存）"""
    request_id = str(uuid.uuid4())
    
    try:
        metrics = db_manager.get_latest_monitor_metrics(limit=limit)
        cache_metrics.record_hit()
        return SuccessResponse(data=metrics, request_id=request_id)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponseBuilder.database_error(
            message=f"获取监控指标失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.get("/monitor-metrics/ip/{ip}")
@cache_decorator(expire_seconds=60, key_prefix="metrics_by_ip")
async def get_metrics_by_ip(ip: str, limit: int = Query(default=10, ge=1, le=100), current_user: UserResponse = Depends(allow_all), request: Request = None):
    """根据IP查询监控指标数据（需要认证，1分钟缓存）"""
    request_id = str(uuid.uuid4())
    
    try:
        metrics = db_manager.get_metrics_by_ip(ip=ip, limit=limit)
        cache_metrics.record_hit()
        return SuccessResponse(data=metrics, request_id=request_id)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponseBuilder.database_error(
            message=f"根据IP查询监控指标失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.get("/monitor-metrics/ip/{ip}/latest")
@cache_decorator(expire_seconds=60, key_prefix="latest_metric_by_ip")
async def get_latest_metric_by_ip(ip: str, current_user: UserResponse = Depends(allow_all), request: Request = None):
    """获取指定IP的最新一条监控指标数据（需要认证，1分钟缓存）"""
    request_id = str(uuid.uuid4())
    
    try:
        metric = db_manager.get_latest_metric_by_ip(ip=ip)
        if not metric:
            raise HTTPException(status_code=404, detail="未找到该IP的监控数据")
        cache_metrics.record_hit()
        return SuccessResponse(data=metric, request_id=request_id)
    except HTTPException:
        raise
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponseBuilder.database_error(
            message=f"获取IP最新监控指标失败: {str(e)}",
            path=str(request.url) if request else None,
            request_id=request_id
        )

@app.get("/monitor-metrics/time-range")
@cache_decorator(expire_seconds=60, key_prefix="metrics_by_time_range")
async def get_metrics_by_time_range(
    start_ts: int = Query(..., description="开始时间戳"),
    end_ts: int = Query(..., description="结束时间戳"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    limit: int = Query(default=100, ge=1, le=1000, description="返回条数限制"),
    current_user: UserResponse = Depends(allow_all)
):
    """根据时间范围查询监控指标数据（需要认证，1分钟缓存）"""
    try:
        metrics = db_manager.get_metrics_by_time_range(start_ts=start_ts, end_ts=end_ts, ip=ip, limit=limit)
        cache_metrics.record_hit()
        return SuccessResponse(data=metrics)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"根据时间范围查询监控指标失败: {str(e)}")

@app.get("/monitor-metrics/paginated")
@cache_decorator(expire_seconds=60, key_prefix="metrics_paginated")
async def get_metrics_paginated(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    current_user: UserResponse = Depends(allow_all)
):
    """分页查询监控指标数据（需要认证，1分钟缓存）"""
    try:
        result = db_manager.get_metrics_paginated(page=page, page_size=page_size, ip=ip)
        cache_metrics.record_hit()
        return PaginatedResponse(
            data=result["data"],
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"]
        )
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"分页查询监控指标失败: {str(e)}")

@app.get("/monitor-metrics/ips")
@cache_decorator(expire_seconds=60, key_prefix="all_ips")
async def get_all_ips(current_user: UserResponse = Depends(allow_all)):
    """获取所有监控的IP列表（需要认证，1分钟缓存）"""
    try:
        ips = db_manager.get_all_ips()
        cache_metrics.record_hit()
        return SuccessResponse(data=ips)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取IP列表失败: {str(e)}")

@app.get("/monitor-metrics/statistics")
@cache_decorator(expire_seconds=60, key_prefix="metrics_statistics")
async def get_metrics_statistics(
    ip: Optional[str] = Query(default=None, description="IP地址（可选）"),
    start_ts: Optional[int] = Query(default=None, description="开始时间戳（可选）"),
    end_ts: Optional[int] = Query(default=None, description="结束时间戳（可选）"),
    current_user: UserResponse = Depends(allow_all)
):
    """获取监控指标的统计信息（平均值、最大值、最小值）（需要认证，1分钟缓存）"""
    try:
        stats = db_manager.get_metrics_statistics(ip=ip, start_ts=start_ts, end_ts=end_ts)
        if not stats:
            raise HTTPException(status_code=404, detail="未找到统计信息")
        cache_metrics.record_hit()
        return SuccessResponse(data=stats)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取统计信息失败: {str(e)}")

@app.get("/monitor-metrics/high-cpu")
@cache_decorator(expire_seconds=60, key_prefix="high_cpu_metrics")
async def get_high_cpu_metrics(
    cpu_threshold: float = Query(default=80.0, ge=0, le=100, description="CPU使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制"),
    current_user: UserResponse = Depends(allow_all)
):
    """查询CPU使用率超过阈值的监控指标（需要认证，1分钟缓存）"""
    try:
        metrics = db_manager.get_high_cpu_metrics(cpu_threshold=cpu_threshold, limit=limit)
        cache_metrics.record_hit()
        return SuccessResponse(data=metrics)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"查询高CPU使用率监控指标失败: {str(e)}")

@app.get("/monitor-metrics/high-memory")
@cache_decorator(expire_seconds=60, key_prefix="high_memory_metrics")
async def get_high_memory_metrics(
    mem_threshold: float = Query(default=80.0, ge=0, le=100, description="内存使用率阈值（%）"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数限制"),
    current_user: UserResponse = Depends(allow_all)
):
    """查询内存使用率超过阈值的监控指标（需要认证，1分钟缓存）"""
    try:
        metrics = db_manager.get_high_memory_metrics(mem_threshold=mem_threshold, limit=limit)
        cache_metrics.record_hit()
        return SuccessResponse(data=metrics)
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"查询高内存使用率监控指标失败: {str(e)}")


@app.get("/monitor-metrics/active-machines")
@cache_decorator(expire_seconds=60, key_prefix="active_machines")
async def get_active_machines_latest_metrics(
    time_window_hours: int = Query(default=1, ge=1, le=24, description="时间窗口（小时），默认为1小时"),
    current_user: UserResponse = Depends(allow_all)
):
    """
    获取指定时间窗口内活跃机器的最新监控指标（需要认证，1分钟缓存）
    
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
        
        cache_metrics.record_hit()
        return SuccessResponse(
            data=formatted_metrics,
            message=f"成功获取{len(formatted_metrics)}个活跃机器的最新监控数据"
        )
        
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR, 
            message=f"获取活跃机器最新监控指标失败: {str(e)}"
        )


@app.get("/monitor-metrics/ip/{ip}/complete")
@cache_decorator(expire_seconds=60, key_prefix="complete_metrics_by_ip")
async def get_latest_complete_metrics_by_ip(ip: str, current_user: UserResponse = Depends(allow_all)):
    """
    根据IP地址获取该IP的最新完整监控信息，包含所有计算字段（需要认证，1分钟缓存）
    
    参数:
        ip: IP地址
        
    返回:
        该IP的最新完整监控信息，包含原始字段和计算字段：
        
        CPU相关字段：
        - cpu_usr, cpu_sys, cpu_iow - CPU使用率原始数据
        - cpu_total_usage - CPU总使用率百分比
        - cpu_idle - CPU空闲百分比
        
        内存相关字段：
        - mem_total, mem_free, mem_cache, mem_buffer - 内存原始数据
        - mem_used - 已使用内存字节数
        - mem_usage_percent - 内存使用率百分比
        - mem_actual_used - 实际使用内存（不含缓存和缓冲区）
        
        Swap相关字段：
        - swap_total, swap_used - Swap原始数据
        - swap_free - 空闲Swap字节数
        - swap_usage_percent - Swap使用率百分比
        
        网络相关字段：
        - net_rx_kbytes, net_tx_kbytes - 网络流量原始数据（KB）
        - net_rx_kbps, net_tx_kbps - 网络速率（KB/s）
        - net_rx_bytes, net_tx_bytes - 网络流量字节数
        
        磁盘相关字段：
        - disk_name, disk_total, disk_used, disk_used_percent, disk_iops, disk_r, disk_w
        
        系统信息：
        - system_in, system_cs
        
        基础信息：
        - id, ip, ts, version, inserted_at
    """
    try:
        metric = db_manager.get_latest_complete_metrics_by_ip(ip=ip)
        
        if not metric:
            raise HTTPException(status_code=404, detail=f"未找到IP {ip} 的监控数据")
        
        cache_metrics.record_hit()
        # 返回完整的监控信息，包含所有计算字段
        return SuccessResponse(
            data=metric,
            message=f"成功获取IP {ip} 的最新完整监控信息"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR, 
            message=f"获取IP {ip} 最新完整监控信息失败: {str(e)}"
        )


@app.get("/monitor-metrics/ip/{ip}/latest-ten")
@cache_decorator(expire_seconds=60, key_prefix="latest_ten_metrics_by_ip")
async def get_latest_ten_complete_metrics_by_ip(ip: str, current_user: UserResponse = Depends(allow_all)):
    """
    根据IP地址获取该IP的最近十条完整监控信息，包含所有计算字段（需要认证，1分钟缓存）
    
    参数:
        ip: IP地址
        
    返回:
        该IP的最近十条完整监控信息列表，包含原始字段和计算字段：
        
        CPU相关字段：
        - cpu_usr, cpu_sys, cpu_iow - CPU使用率原始数据
        - cpu_total_usage - CPU总使用率百分比
        - cpu_idle - CPU空闲百分比
        
        内存相关字段：
        - mem_total, mem_free, mem_cache, mem_buffer - 内存原始数据
        - mem_used - 已使用内存字节数
        - mem_usage_percent - 内存使用率百分比
        - mem_actual_used - 实际使用内存（不含缓存和缓冲区）
        
        Swap相关字段：
        - swap_total, swap_used - Swap原始数据
        - swap_free - 空闲Swap字节数
        - swap_usage_percent - Swap使用率百分比
        
        网络相关字段：
        - net_rx_kbytes, net_tx_kbytes - 网络流量原始数据（KB）
        - net_rx_kbps, net_tx_kbps - 网络速率（KB/s）
        - net_rx_bytes, net_tx_bytes - 网络流量字节数
        
        磁盘相关字段：
        - disk_name, disk_total, disk_used, disk_used_percent, disk_iops, disk_r, disk_w
        
        系统信息：
        - system_in, system_cs
        
        基础信息：
        - id, ip, ts, version, inserted_at
        
        总计信息：
        - 每个记录都包含完整的计算字段，方便前端直接使用
    """
    try:
        metrics = db_manager.get_latest_ten_complete_metrics_by_ip(ip=ip)
        
        if not metrics:
            raise HTTPException(status_code=404, detail=f"未找到IP {ip} 的监控数据")
        
        # 计算总计信息（基于最近十条数据的统计）
        total_info = {
            "total_records": len(metrics),
            "avg_cpu_total_usage": 0.0,
            "avg_mem_usage_percent": 0.0,
            "avg_disk_used_percent": 0.0,
            "max_cpu_total_usage": 0.0,
            "max_mem_usage_percent": 0.0,
            "min_cpu_idle": 100.0,
            "avg_net_rx_kbps": 0.0,
            "avg_net_tx_kbps": 0.0
        }
        
        if metrics:
            # 计算各项平均值和极值
            cpu_total_usages = [m.get('cpu_total_usage', 0) or 0 for m in metrics]
            mem_usage_percents = [m.get('mem_usage_percent', 0) or 0 for m in metrics]
            disk_used_percents = [m.get('disk_used_percent', 0) or 0 for m in metrics]
            cpu_idles = [m.get('cpu_idle', 0) or 0 for m in metrics]
            net_rx_kbps_list = [m.get('net_rx_kbps', 0) or 0 for m in metrics]
            net_tx_kbps_list = [m.get('net_tx_kbps', 0) or 0 for m in metrics]
            
            total_info["avg_cpu_total_usage"] = round(sum(cpu_total_usages) / len(cpu_total_usages), 2)
            total_info["avg_mem_usage_percent"] = round(sum(mem_usage_percents) / len(mem_usage_percents), 2)
            total_info["avg_disk_used_percent"] = round(sum(disk_used_percents) / len(disk_used_percents), 2)
            total_info["max_cpu_total_usage"] = round(max(cpu_total_usages), 2)
            total_info["max_mem_usage_percent"] = round(max(mem_usage_percents), 2)
            total_info["min_cpu_idle"] = round(min(cpu_idles), 2)
            total_info["avg_net_rx_kbps"] = round(sum(net_rx_kbps_list) / len(net_rx_kbps_list), 2)
            total_info["avg_net_tx_kbps"] = round(sum(net_tx_kbps_list) / len(net_tx_kbps_list), 2)
        
        # 返回包含详细数据和总计信息的响应
        response_data = {
            "metrics": metrics,
            "summary": total_info,
            "ip": ip,
            "timestamp_range": {
                "earliest": metrics[-1].get('ts') if metrics else None,
                "latest": metrics[0].get('ts') if metrics else None
            }
        }
        
        cache_metrics.record_hit()
        return SuccessResponse(
            data=response_data,
            message=f"成功获取IP {ip} 的最近{len(metrics)}条完整监控信息"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR, 
            message=f"获取IP {ip} 最近十条完整监控信息失败: {str(e)}"
        )


# ==================== 用户认证相关API ====================

@app.post("/auth/register", response_model=SuccessResponse)
async def register_user(user_data: UserCreate):
    """
    用户注册
    
    Args:
        user_data: 用户注册信息
        
    Returns:
        注册结果
    """
    try:
        user_id = db_manager.create_user(user_data)
        if not user_id:
            raise HTTPException(status_code=400, detail="用户名已存在")
        
        return SuccessResponse(
            data={"user_id": user_id},
            message="用户注册成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"用户注册失败: {str(e)}"
        )


@app.post("/auth/login", response_model=SuccessResponse)
async def login_user(login_data: UserLogin):
    """
    用户登录（Token缓存6小时）
    
    Args:
        login_data: 登录信息
        
    Returns:
        登录结果和访问令牌
    """
    try:
        user = db_manager.authenticate_user(login_data)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        
        # 创建访问令牌（6小时过期）
        access_token_expires = timedelta(hours=6)
        access_token = await create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "role": user.role
            },
            expires_delta=access_token_expires
        )
        
        # 创建刷新令牌（7天过期）
        refresh_token = create_refresh_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "role": user.role
            }
        )
        
        token_response = Token(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=access_token_expires.seconds,
            token_type="bearer"
        )
        
        return SuccessResponse(
            data={
                "user": user,
                "token": token_response
            },
            message="登录成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"登录失败: {str(e)}"
        )


@app.get("/auth/me", response_model=SuccessResponse)
async def get_current_user_info(current_user: UserResponse = Depends(get_current_active_user)):
    """
    获取当前用户信息
    
    Args:
        current_user: 当前认证用户
        
    Returns:
        当前用户信息
    """
    return SuccessResponse(data=current_user, message="获取用户信息成功")


@app.put("/auth/profile", response_model=SuccessResponse)
async def update_user_profile(
    update_data: UserUpdate,
    current_user: UserResponse = Depends(get_current_active_user)
):
    """
    更新用户个人信息
    
    Args:
        update_data: 更新数据
        current_user: 当前认证用户
        
    Returns:
        更新结果
    """
    try:
        success = db_manager.update_user(current_user.id, update_data)
        if not success:
            raise HTTPException(status_code=400, detail="更新用户信息失败")
        
        # 获取更新后的用户信息
        updated_user = db_manager.get_user_by_id(current_user.id)
        
        return SuccessResponse(
            data=updated_user,
            message="用户信息更新成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"更新用户信息失败: {str(e)}"
        )


# ==================== 受保护的监控数据API ====================

@app.get("/protected/monitor-metrics/latest", response_model=SuccessResponse)
async def get_protected_latest_monitor_metrics(
    limit: int = Query(default=5, ge=1, le=100),
    current_user: UserResponse = Depends(allow_all)
):
    """获取最新的监控指标数据（需要认证）"""
    try:
        metrics = db_manager.get_latest_monitor_metrics(limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"获取监控指标失败: {str(e)}")


@app.get("/protected/monitor-metrics/ip/{ip}", response_model=SuccessResponse)
async def get_protected_metrics_by_ip(
    ip: str,
    limit: int = Query(default=10, ge=1, le=100),
    current_user: UserResponse = Depends(allow_all)
):
    """根据IP查询监控指标数据（需要认证）"""
    try:
        metrics = db_manager.get_metrics_by_ip(ip=ip, limit=limit)
        return SuccessResponse(data=metrics)
    except Exception as e:
        return ErrorResponse(code=ErrorCode.DATABASE_ERROR, message=f"根据IP查询监控指标失败: {str(e)}")


@app.post("/auth/refresh", response_model=SuccessResponse)
async def refresh_token(refresh_token: str):
    """
    Token续期接口
    
    Args:
        refresh_token: 刷新令牌
        
    Returns:
        新的访问令牌
    """
    try:
        new_token = await refresh_access_token(refresh_token)
        if not new_token:
            raise HTTPException(status_code=401, detail="无效的刷新令牌")
        
        return SuccessResponse(
            data={"token": new_token},
            message="Token续期成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.AUTHENTICATION_ERROR,
            message=f"Token续期失败: {str(e)}"
        )


@app.get("/monitor-metrics/machine-status/{ip}", response_model=SuccessResponse)
@cache_decorator(expire_seconds=60, key_prefix="machine_status")
async def get_machine_status_by_ip(ip: str, current_user: UserResponse = Depends(allow_all)):
    """
    根据IP地址获取机器的最新状态评估（需要认证，1分钟缓存）
    
    Args:
        ip: IP地址
        current_user: 当前认证用户
        
    Returns:
        机器状态评估结果，包含：
        - status_level: 状态分级（正常/提示/警告/未知）
        - key_metrics: 关键指标数据
        - issues: 问题列表
        - warnings: 警告列表
        - is_healthy: 是否健康
        - overall_score: 健康评分（0-100）
    """
    try:
        status = db_manager.get_machine_status_by_ip(ip)
        cache_metrics.record_hit()
        return SuccessResponse(
            data=status,
            message=f"成功获取IP {ip} 的状态评估"
        )
        
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"获取机器状态评估失败: {str(e)}"
        )

@app.get("/monitor-metrics/all-machines-status", response_model=SuccessResponse)
@cache_decorator(expire_seconds=60, key_prefix="all_machines_status")
async def get_all_machines_status(
    time_window_hours: int = Query(default=1, ge=1, le=24, description="时间窗口（小时），默认为1小时"),
    current_user: UserResponse = Depends(allow_all)
):
    """
    获取所有机器的状态评估（需要认证，1分钟缓存）
    
    Args:
        time_window_hours: 时间窗口（小时）
        current_user: 当前认证用户
        
    Returns:
        所有机器的状态评估列表，按健康评分排序
    """
    try:
        status_list = db_manager.get_all_machines_status(time_window_hours)
        
        # 统计信息
        total_machines = len(status_list)
        healthy_machines = len([s for s in status_list if s['is_healthy']])
        warning_machines = len([s for s in status_list if s['status_level'] == "提示"])
        critical_machines = len([s for s in status_list if s['status_level'] == "警告"])
        unknown_machines = len([s for s in status_list if s['status_level'] == "未知"])
        
        summary = {
            "total_machines": total_machines,
            "healthy_machines": healthy_machines,
            "warning_machines": warning_machines,
            "critical_machines": critical_machines,
            "unknown_machines": unknown_machines,
            "health_percentage": round((healthy_machines / total_machines * 100), 2) if total_machines > 0 else 0
        }
        
        cache_metrics.record_hit()
        return SuccessResponse(
            data={
                "machines": status_list,
                "summary": summary
            },
            message=f"成功获取{total_machines}个机器的状态评估"
        )
        
    except Exception as e:
        cache_metrics.record_error()
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"获取所有机器状态评估失败: {str(e)}"
        )

@app.get("/monitor-metrics/system-overview")
@cache_decorator(expire_seconds=60, key_prefix="system_overview")
async def get_system_overview(
    time_window_hours: int = Query(default=1, ge=1, le=24, description="时间窗口（小时），默认为1小时"),
    current_user: UserResponse = Depends(allow_all)
):
    """
    获取系统总体概览信息（需要认证，1分钟缓存）
    
    Args:
        time_window_hours: 时间窗口（小时）
        current_user: 当前认证用户
        
    Returns:
        系统总体概览信息，包含：
        - 活跃机器数量和IP列表
        - 健康状态分布统计
        - 告警和提示信息汇总
        - 关键指标的最大值、平均值、最小值
        - 性能趋势分析
        - 详细告警信息
    """
    try:
        overview = db_manager.get_system_overview(time_window_hours)
        
        cache_metrics.record_hit()
        # 直接返回数据，避免响应模型验证问题
        return {
            "code": 200,
            "message": "成功获取系统总体概览信息",
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": overview
        }
        
    except Exception as e:
        cache_metrics.record_error()
        return {
            "code": ErrorCode.DATABASE_ERROR,
            "message": f"获取系统总体概览信息失败: {str(e)}",
            "status": "error",
            "timestamp": datetime.now().isoformat()
        }

@app.get("/cache/stats", response_model=SuccessResponse)
async def get_cache_statistics(current_user: UserResponse = Depends(allow_admin)):
    """
    获取缓存统计信息（仅管理员可用）
    
    Args:
        current_user: 当前认证用户（必须是管理员）
        
    Returns:
        缓存统计信息
    """
    try:
        stats = cache_metrics.get_stats()
        return SuccessResponse(
            data=stats,
            message="获取缓存统计信息成功"
        )
        
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"获取缓存统计信息失败: {str(e)}"
        )


@app.post("/cache/clear", response_model=SuccessResponse)
async def clear_cache(pattern: str = "*", current_user: UserResponse = Depends(allow_admin)):
    """
    清除缓存（仅管理员可用）
    
    Args:
        pattern: 缓存键模式
        current_user: 当前认证用户（必须是管理员）
        
    Returns:
        清除结果
    """
    try:
        # 清除所有后端的匹配缓存
        cleared_count = 0
        for backend in ["default", "tokens", "monitor_metrics"]:
            count = cache_manager.clear_pattern(pattern, backend)
            cleared_count += count
        
        # 重置统计信息
        cache_metrics.reset()
        
        return SuccessResponse(
            data={"cleared_count": cleared_count},
            message=f"成功清除{cleared_count}个缓存项"
        )
        
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"清除缓存失败: {str(e)}"
        )


@app.get("/admin/users", response_model=SuccessResponse)
async def get_all_users(
    current_user: UserResponse = Depends(allow_admin)
):
    """
    获取所有用户列表（仅管理员可用）
    
    Args:
        current_user: 当前认证用户（必须是管理员）
        
    Returns:
        用户列表
    """
    try:
        # 这里需要实现获取所有用户的方法
        # 暂时返回空列表，需要时再实现
        return SuccessResponse(
            data=[],
            message="获取用户列表成功"
        )
        
    except Exception as e:
        return ErrorResponse(
            code=ErrorCode.DATABASE_ERROR,
            message=f"获取用户列表失败: {str(e)}"
        )
