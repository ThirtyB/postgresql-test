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
        user_id = db.insert_user(request.name, request.email, request.age, request.password)
        return CreateUserResponse(id=user_id, status="success")
    except Exception as e:
        return CreateUserResponse(id=None, status=f"Failed to create user: {e}")
    finally:
        db.disconnect()
