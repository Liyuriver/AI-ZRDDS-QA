"""One-image, non-mutating DashScope VLM diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from app.services.preprocessing import image_vlm  # noqa: E402


def load_env() -> None:
    env_file = BACKEND / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=BACKEND / "data" / "hybrid" / "formal-22-04-01__c362eaa590c9c95f")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=0)
    args = parser.parse_args()
    load_env()
    image_dir = args.output / "images"
    image = next((p for p in sorted(image_dir.iterdir()) if p.is_file()), None)
    if image is None:
        raise SystemExit(f"No image found under {image_dir}")
    os.environ["ENABLE_VLM"] = "true"
    os.environ["VLM_TIMEOUT"] = str(args.timeout)
    os.environ["VLM_RETRIES"] = str(args.retries)
    print(f"image={image}")
    print("endpoint=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    print(f"model={os.getenv('QWEN_VL_MODEL', 'qwen3-vl-plus')}")
    print(f"api_key_present={bool(os.getenv('DASHSCOPE_API_KEY'))}")
    print(f"proxy_http={'HTTP_PROXY' in os.environ or 'http_proxy' in os.environ}")
    print(f"proxy_https={'HTTPS_PROXY' in os.environ or 'https_proxy' in os.environ}")
    print(f"timeout={args.timeout} retries={args.retries}")
    started = time.perf_counter()
    try:
        original_post = image_vlm.httpx.Client.post

        def traced_post(client, *post_args, **post_kwargs):
            response = original_post(client, *post_args, **post_kwargs)
            print(f"http_status={response.status_code}")
            return response

        image_vlm.httpx.Client.post = traced_post
        result = image_vlm.enrich_image(image, document="formal-22-04-01.pdf", section=None,
                                        context_before="", context_after="", mineru_ocr=None,
                                        timeout=args.timeout, retries=args.retries)
        print(f"elapsed_seconds={time.perf_counter() - started:.2f}")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:12000])
        return 0 if result.get("parse_status") == "success" else 2
    except Exception as exc:
        print(f"elapsed_seconds={time.perf_counter() - started:.2f}")
        print(f"exception_type={type(exc).__name__}")
        print(f"exception={exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
