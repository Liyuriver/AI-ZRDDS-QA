"""User business services."""

from typing import List, Optional

from app.database.repository import DuplicateResourceError, RepositoryError, UserRepository
from app.models import User
from app.services.security import hash_password, verify_password
from app.services.avatar_service import save_avatar


class UserNotFoundError(LookupError):
    """The requested user does not exist."""


class InvalidCredentialsError(ValueError):
    """Username or password is invalid."""


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def create_user(self, username: str, email: str, password: str | None = None) -> User:
        if not username.strip() or not email.strip():
            raise ValueError("username 和 email 不能为空")
        password_hash = hash_password(password) if password else None
        return self.repository.create(username.strip(), email.strip().lower(), password_hash)

    def register(self, username: str, email: str, password: str) -> User:
        if len(password) < 8:
            raise ValueError("密码长度不能少于 8 位")
        return self.create_user(username, email, password)

    def authenticate(self, username: str, password: str) -> User:
        user = self.repository.get_by_username(username.strip())
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("用户名或密码错误")
        return user

    def verify_current_password(self, user: User, password: str) -> None:
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("当前密码错误")

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        self.verify_current_password(user, current_password)
        if len(new_password) < 8:
            raise ValueError("新密码长度不能少于 8 位")
        self.repository.update_password(user, hash_password(new_password))

    def update_avatar(self, user: User, data_url: str) -> User:
        avatar_url = save_avatar(user.id, data_url, user.avatar_url)
        return self.repository.update_avatar(user, avatar_url)

    def get_user(self, user_id: str) -> User:
        user = self.repository.get(user_id)
        if user is None:
            raise UserNotFoundError(f"用户不存在: {user_id}")
        return user

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self.repository.get_by_username(username)

    def update_user(self, user_id: str, username: Optional[str] = None, email: Optional[str] = None) -> User:
        if username is None and email is None:
            raise ValueError("至少提供一个待修改字段")
        if username is not None and not username.strip():
            raise ValueError("username 不能为空")
        return self.repository.update(self.get_user(user_id), username.strip() if username else None, email.strip() if email else None)

    def list_users(self) -> List[User]:
        return self.repository.list()
