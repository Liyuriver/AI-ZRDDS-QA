"""Validate and persist user avatar images outside the database."""

import base64
import binascii
from pathlib import Path
from uuid import uuid4


AVATAR_DIR = Path(__file__).resolve().parents[2] / "data" / "avatars"
MAX_AVATAR_BYTES = 2 * 1024 * 1024
SUPPORTED = {
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/webp": (".webp", b"RIFF"),
}


def save_avatar(user_id: str, data_url: str, old_url: str | None = None) -> str:
    try:
        header, encoded = data_url.split(",", 1)
        mime = header.removeprefix("data:").removesuffix(";base64")
        suffix, signature = SUPPORTED[mime]
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, KeyError, binascii.Error) as exc:
        raise ValueError("头像必须是 PNG、JPEG 或 WebP 图片") from exc
    if not content or len(content) > MAX_AVATAR_BYTES:
        raise ValueError("头像大小不能超过 2 MB")
    if not content.startswith(signature) or (mime == "image/webp" and content[8:12] != b"WEBP"):
        raise ValueError("头像文件内容与格式不匹配")

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{user_id}-{uuid4().hex}{suffix}"
    path = AVATAR_DIR / filename
    path.write_bytes(content)

    if old_url:
        old_name = Path(old_url).name
        if old_name.startswith(f"{user_id}-"):
            old_path = AVATAR_DIR / old_name
            if old_path.is_file() and old_path != path:
                old_path.unlink()
    return f"/static/avatars/{filename}"
