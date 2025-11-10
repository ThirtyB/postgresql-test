from pydantic import BaseModel
from typing import Any, Optional, TypeVar, Generic, Dict, List
from enum import Enum
from datetime import datetime


class ResponseStatus(str, Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    ERROR = "error"


class BaseResponse(BaseModel):
    """基础响应模型"""
    code: int
    message: str
    status: ResponseStatus
    timestamp: str
    path: Optional[str] = None
    request_id: Optional[str] = None


class DataResponse(BaseResponse):
    """带数据的响应模型"""
    data: Optional[Any] = None


class PaginatedResponse(BaseResponse):
    """分页响应模型"""
    data: Optional[Any] = None
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class ErrorDetail(BaseModel):
    """错误详情模型"""
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseResponse):
    """错误响应模型"""
    errors: Optional[List[ErrorDetail]] = None
    trace_id: Optional[str] = None
    documentation_url: Optional[str] = None


# 预定义的响应模型
class SuccessResponse(DataResponse):
    """成功响应"""
    def __init__(self, data: Any = None, message: str = "操作成功", path: str = None, request_id: str = None):
        super().__init__(
            code=200, 
            message=message, 
            status=ResponseStatus.SUCCESS, 
            data=data,
            timestamp=datetime.now().isoformat(),
            path=path,
            request_id=request_id
        )


class ErrorResponseBuilder:
    """错误响应构建器"""
    
    @staticmethod
    def create(
        code: int = 500, 
        message: str = "操作失败", 
        errors: List[ErrorDetail] = None,
        path: str = None,
        request_id: str = None,
        trace_id: str = None,
        documentation_url: str = None
    ) -> ErrorResponse:
        """创建错误响应"""
        return ErrorResponse(
            code=code,
            message=message,
            status=ResponseStatus.ERROR,
            timestamp=datetime.now().isoformat(),
            errors=errors,
            path=path,
            request_id=request_id,
            trace_id=trace_id,
            documentation_url=documentation_url
        )
    
    @staticmethod
    def bad_request(
        message: str = "请求参数错误",
        errors: List[ErrorDetail] = None,
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """400 错误请求"""
        return ErrorResponseBuilder.create(
            code=400,
            message=message,
            errors=errors,
            path=path,
            request_id=request_id
        )
    
    @staticmethod
    def unauthorized(
        message: str = "未授权访问",
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """401 未授权"""
        return ErrorResponseBuilder.create(
            code=401,
            message=message,
            path=path,
            request_id=request_id
        )
    
    @staticmethod
    def forbidden(
        message: str = "禁止访问",
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """403 禁止访问"""
        return ErrorResponseBuilder.create(
            code=403,
            message=message,
            path=path,
            request_id=request_id
        )
    
    @staticmethod
    def not_found(
        message: str = "资源不存在",
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """404 资源不存在"""
        return ErrorResponseBuilder.create(
            code=404,
            message=message,
            path=path,
            request_id=request_id
        )
    
    @staticmethod
    def internal_error(
        message: str = "服务器内部错误",
        path: str = None,
        request_id: str = None,
        trace_id: str = None
    ) -> ErrorResponse:
        """500 服务器内部错误"""
        return ErrorResponseBuilder.create(
            code=500,
            message=message,
            path=path,
            request_id=request_id,
            trace_id=trace_id
        )
    
    @staticmethod
    def database_error(
        message: str = "数据库操作失败",
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """501 数据库错误"""
        return ErrorResponseBuilder.create(
            code=501,
            message=message,
            path=path,
            request_id=request_id
        )
    
    @staticmethod
    def validation_error(
        errors: List[ErrorDetail],
        message: str = "数据验证失败",
        path: str = None,
        request_id: str = None
    ) -> ErrorResponse:
        """422 数据验证错误"""
        return ErrorResponseBuilder.create(
            code=422,
            message=message,
            errors=errors,
            path=path,
            request_id=request_id
        )


# 预定义错误码
class ErrorCode:
    """错误码定义"""
    SUCCESS = 200
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    INTERNAL_ERROR = 500
    DATABASE_ERROR = 501
    VALIDATION_ERROR = 422
    
    # 业务错误码
    USER_EXISTS = 1001
    USER_NOT_FOUND = 1002
    INVALID_CREDENTIALS = 1003
    INSUFFICIENT_PERMISSIONS = 1004
    RESOURCE_LIMIT_EXCEEDED = 1005
    
    # 系统错误码
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504