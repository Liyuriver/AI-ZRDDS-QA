"""User API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import DuplicateResourceError, RepositoryError, UserRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserNotFoundError, UserService

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)) -> UserRead:
    try:
        return service.create_user(payload.username, payload.email)
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[UserRead])
def list_users(service: UserService = Depends(get_user_service)) -> list[UserRead]:
    return service.list_users()


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: str, service: UserService = Depends(get_user_service)) -> UserRead:
    try:
        return service.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserUpdate, service: UserService = Depends(get_user_service)) -> UserRead:
    try:
        return service.update_user(user_id, payload.username, payload.email)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
