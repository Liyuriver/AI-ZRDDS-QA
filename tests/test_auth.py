import pytest
from fastapi import HTTPException
from unittest.mock import Mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.database.repository import UserRepository
from app.services.security import create_access_token, decode_access_token, hash_password, verify_password
from app.services.user_service import InvalidCredentialsError, UserService
from app.api.user import update_password, update_profile
from app.schemas.user import PasswordUpdate, ProfileUpdate


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("valid-password")
    second = hash_password("valid-password")
    assert first != second
    assert verify_password("valid-password", first)
    assert not verify_password("wrong-password", first)


def test_signed_token_round_trip(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-only-auth-secret-that-is-at-least-32-characters")
    token = create_access_token("user-1")
    assert decode_access_token(token) == "user-1"
    with pytest.raises(ValueError):
        decode_access_token(token + "tampered")


def test_register_login_and_change_password():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        service = UserService(UserRepository(db))
        user = service.register("secure-user", "secure@example.com", "old-password")
        assert service.authenticate("secure-user", "old-password").id == user.id
        with pytest.raises(InvalidCredentialsError):
            service.authenticate("secure-user", "wrong-password")
        service.change_password(user, "old-password", "new-password")
        with pytest.raises(InvalidCredentialsError):
            service.authenticate("secure-user", "old-password")
        assert service.authenticate("secure-user", "new-password").id == user.id


def test_wrong_current_password_is_not_treated_as_expired_login():
    service = Mock()
    current = Mock(id="user-1")
    service.get_user.return_value = current
    service.verify_current_password.side_effect = InvalidCredentialsError("当前密码错误")

    with pytest.raises(HTTPException) as profile_error:
        update_profile(
            ProfileUpdate(
                username="new-name",
                email="new@example.com",
                current_password="wrong",
            ),
            current,
            service,
        )
    assert profile_error.value.status_code == 400

    service.change_password.side_effect = InvalidCredentialsError("当前密码错误")
    with pytest.raises(HTTPException) as password_error:
        update_password(
            PasswordUpdate(current_password="wrong", new_password="new-password"),
            current,
            service,
        )
    assert password_error.value.status_code == 400
