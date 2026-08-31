"""User business services."""

from typing import List, Optional

from app.database.repository import DuplicateResourceError, RepositoryError, UserRepository
from app.models import User


class UserNotFoundError(LookupError):
    """The requested user does not exist."""


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def create_user(self, username: str, email: str) -> User:
        if not username.strip() or not email.strip():
            raise ValueError("username 和 email 不能为空")
        return self.repository.create(username.strip(), email.strip())

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
