from fastapi import FastAPI
from database import DatabaseManager
from pydantic import BaseModel
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
        db.disconnect

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
        db.disconnect
