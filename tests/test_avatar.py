import base64

import pytest

from app.services import avatar_service


def data_url(content: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode()}"


def test_avatar_validation_and_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_service, "AVATAR_DIR", tmp_path)
    first = avatar_service.save_avatar("user-1", data_url(b"\x89PNG\r\n\x1a\nfirst"))
    first_path = tmp_path / first.rsplit("/", 1)[-1]
    assert first_path.is_file()

    second = avatar_service.save_avatar(
        "user-1", data_url(b"\x89PNG\r\n\x1a\nsecond"), first
    )
    assert not first_path.exists()
    assert (tmp_path / second.rsplit("/", 1)[-1]).is_file()


def test_avatar_rejects_unsupported_or_oversized_content(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_service, "AVATAR_DIR", tmp_path)
    with pytest.raises(ValueError):
        avatar_service.save_avatar("user-1", data_url(b"GIF89a", "image/gif"))
    with pytest.raises(ValueError):
        avatar_service.save_avatar(
            "user-1", data_url(b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024))
        )
