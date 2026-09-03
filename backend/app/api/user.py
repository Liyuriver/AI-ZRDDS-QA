"""User API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import DuplicateResourceError, RepositoryError, UserRepository
from app.schemas.user import (
    AuthSession,
    AvatarUpdate,
    LoginRequest,
    PasswordUpdate,
    ProfileUpdate,
    RegisterRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.security import create_access_token, decode_access_token
from app.services.user_service import InvalidCredentialsError, UserNotFoundError, UserService
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(UserRepository(db))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: UserService = Depends(get_user_service),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        return service.get_user(decode_access_token(credentials.credentials))
    except (ValueError, UserNotFoundError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@auth_router.post("/register", response_model=AuthSession, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, service: UserService = Depends(get_user_service)) -> AuthSession:
    try:
        user = service.register(payload.username, payload.email, payload.password)
        return AuthSession(token=create_access_token(user.id), user=user)
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_router.post("/login", response_model=AuthSession)
def login(payload: LoginRequest, service: UserService = Depends(get_user_service)) -> AuthSession:
    try:
        user = service.authenticate(payload.username, payload.password)
        return AuthSession(token=create_access_token(user.id), user=user)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@auth_router.get("/me", response_model=UserRead)
def current_user(user: UserRead = Depends(get_current_user)) -> UserRead:
    return user


@auth_router.patch("/me", response_model=UserRead)
def update_profile(
    payload: ProfileUpdate,
    user: UserRead = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    try:
        model = service.get_user(user.id)
        service.verify_current_password(model, payload.current_password)
        return service.update_user(user.id, payload.username, payload.email)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_router.patch("/password", status_code=status.HTTP_204_NO_CONTENT)
def update_password(
    payload: PasswordUpdate,
    user: UserRead = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> None:
    try:
        service.change_password(
            service.get_user(user.id), payload.current_password, payload.new_password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@auth_router.put("/avatar", response_model=UserRead)
def update_avatar(
    payload: AvatarUpdate,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
) -> UserRead:
    try:
        return service.update_avatar(user, payload.data_url)
    except (ValueError, RepositoryError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
    _current: User = Depends(get_current_user),
) -> UserRead:
    try:
        return service.create_user(payload.username, payload.email, payload.password)
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[UserRead])
def list_users(current: User = Depends(get_current_user)) -> list[UserRead]:
    return [current]


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: str,
    service: UserService = Depends(get_user_service),
    current: User = Depends(get_current_user),
) -> UserRead:
    if user_id != current.id:
        raise HTTPException(status_code=403, detail="无权访问其他用户资料")
    try:
        return service.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    payload: UserUpdate,
    service: UserService = Depends(get_user_service),
    current: User = Depends(get_current_user),
) -> UserRead:
    if user_id != current.id:
        raise HTTPException(status_code=403, detail="无权修改其他用户资料")
    try:
        return service.update_user(user_id, payload.username, payload.email)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
