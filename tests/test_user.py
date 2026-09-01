from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database.database import Base
from app.database.repository import ConversationRepository, UserRepository
from app.services.user_service import UserNotFoundError, UserService


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_user_crud_and_unique_fields():
    with make_session() as db:
        service = UserService(UserRepository(db))
        user = service.create_user("alice", "alice@example.com")
        assert service.get_user(user.id).username == "alice"
        assert service.get_user_by_username("alice").id == user.id
        assert len(service.list_users()) == 1

        service.update_user(user.id, username="alice-new")
        assert service.get_user(user.id).username == "alice-new"

        from app.database.repository import DuplicateResourceError
        try:
            service.create_user("alice-new", "other@example.com")
            assert False
        except DuplicateResourceError:
            pass
        try:
            service.create_user("other", "alice@example.com")
            assert False
        except DuplicateResourceError:
            pass
        try:
            service.get_user("missing")
            assert False
        except UserNotFoundError:
            pass


def test_user_has_only_id_as_identifier():
    with make_session() as db:
        columns = {column["name"] for column in inspect(db.bind).get_columns("users")}
        assert "id" in columns
        assert "user_id" not in columns
