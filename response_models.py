from pydantic import BaseModel
from typing import Any, Optional, TypeVar, Generic
from enum import Enum


class ResponseStatus(str, Enum):
    """响应状态枚举"""
    SUCCESS = "success"
    ERROR = "error"


class BaseResponse(BaseModel):
    """基础响应模型"""
    code: int
    message: str
    status: ResponseStatus


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


# 预定义的响应模型
class SuccessResponse(DataResponse):
    """成功响应"""
    def __init__(self, data: Any = None, message: str = "操作成功"):
        super().__init__(code=200, message=message, status=ResponseStatus.SUCCESS, data=data)


class ErrorResponse(BaseResponse):
    """错误响应"""
    def __init__(self, code: int = 500, message: str = "操作失败"):
        super().__init__(code=code, message=message, status=ResponseStatus.ERROR)


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