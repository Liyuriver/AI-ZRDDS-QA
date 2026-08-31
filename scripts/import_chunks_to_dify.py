"""
批量将 backend/data/hybrid 下预处理完成的 chunks.jsonl
导入 Dify 知识库。

目录示例：

AI-ZRDDS-QA/
├─ backend/
│  └─ data/
│     └─ hybrid/
│        ├─ 文档A__hash/
│        │  ├─ chunks.jsonl
│        │  ├─ images/
│        │  └─ ...
│        ├─ 文档B__hash/
│        │  └─ chunks.jsonl
│        └─ ...
│
├─ scripts/
│  └─ import_chunks_to_dify.py
│
└─ .env / backend/.env

处理逻辑：
1. 自动扫描所有 chunks.jsonl
2. 每个处理目录对应一个 Dify document
3. 创建临时占位分段初始化索引
4. 等待索引完成
5. 删除占位分段
6. 将 chunks.jsonl 中每条 content 直接作为 Dify segment
7. 保存 segment_id -> chunk/image 等信息的总映射
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# ============================================================
# 路径
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

HYBRID_ROOT = PROJECT_ROOT / "backend" / "data" / "hybrid"

OUTPUT_MAP = HYBRID_ROOT / "dify_segment_map.json"


# ============================================================
# 读取环境变量
# ============================================================

# 优先加载项目根目录 .env
root_env = PROJECT_ROOT / ".env"

# 同时兼容 backend/.env
backend_env = PROJECT_ROOT / "backend" / ".env"

if root_env.exists():
    load_dotenv(root_env)

if backend_env.exists():
    load_dotenv(backend_env, override=False)

# 最后允许从当前工作目录读取
load_dotenv(override=False)


BASE_URL = os.getenv("DIFY_API_BASE", "").rstrip("/")
API_KEY = os.getenv("DIFY_KB_API_KEY")
DATASET_ID = os.getenv("DIFY_DATASET_ID")


# ============================================================
# Dify 模型配置
# ============================================================

INDEXING_TECHNIQUE = "high_quality"

EMBEDDING_MODEL = "BAAI/bge-m3"

EMBEDDING_PROVIDER = (
    "langgenius/siliconflow/siliconflow"
)

DOC_FORM = "text_model"

# 当前 Dify 要求 50~4000
MAX_TOKENS = 4000

PLACEHOLDER_TEXT = (
    "DIFY_PLACEHOLDER_SEGMENT_FOR_INITIALIZATION"
)


HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

SESSION = requests.Session()
SESSION.trust_env = False

# ============================================================
# 基础工具
# ============================================================

def check_config():
    """检查运行环境。"""

    errors = []

    if not BASE_URL:
        errors.append("缺少 DIFY_API_BASE")

    if not API_KEY:
        errors.append("缺少 DIFY_KB_API_KEY")

    if not DATASET_ID:
        errors.append("缺少 DIFY_DATASET_ID")

    if not HYBRID_ROOT.exists():
        errors.append(
            f"找不到 hybrid 目录：{HYBRID_ROOT}"
        )

    if errors:
        print("\n配置检查失败：")

        for error in errors:
            print(f"  - {error}")

        sys.exit(1)


def request_or_raise(
    method,
    url,
    *,
    timeout=60,
    **kwargs
):
    """
    统一发送 HTTP 请求。
    出错时打印 Dify 返回内容。
    """

    response = SESSION.request(
        method,
        url,
        headers=HEADERS,
        timeout=timeout,
        **kwargs
    )

    if not response.ok:

        print("\n[Dify API 请求失败]")
        print("Method:", method)
        print("URL:", url)
        print("HTTP:", response.status_code)

        try:
            print(
                json.dumps(
                    response.json(),
                    ensure_ascii=False,
                    indent=2
                )
            )
        except Exception:
            print(response.text)

        response.raise_for_status()

    return response


# ============================================================
# 扫描处理结果
# ============================================================

def discover_documents():
    """
    自动寻找：

    backend/data/hybrid/*/chunks.jsonl

    返回：
    [
        {
            "bundle_dir": Path(...),
            "jsonl_path": Path(...)
        },
        ...
    ]
    """

    documents = []

    for child in sorted(HYBRID_ROOT.iterdir()):

        if not child.is_dir():
            continue

        jsonl_path = child / "chunks.jsonl"

        if not jsonl_path.exists():
            continue

        documents.append({
            "bundle_dir": child,
            "jsonl_path": jsonl_path,
        })

    return documents


def load_chunks(jsonl_path):
    """读取一个 chunks.jsonl。"""

    chunks = []

    with jsonl_path.open(
        "r",
        encoding="utf-8"
    ) as f:

        for line_no, line in enumerate(
            f,
            start=1
        ):
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)

            except json.JSONDecodeError as exc:

                raise RuntimeError(
                    f"{jsonl_path}\n"
                    f"第 {line_no} 行 JSON 无效："
                    f"{exc}"
                ) from exc

            content = str(
                item.get("content", "")
            ).strip()

            if not content:
                print(
                    f"  [跳过] 第 {line_no} 行 "
                    f"content 为空"
                )
                continue

            chunks.append(item)

    return chunks


def infer_document_name(
    chunks,
    bundle_dir
):
    """
    优先使用 chunks.jsonl 里的 document 字段。

    若没有，则使用文件夹名并去掉 __hash。
    """

    for item in chunks:

        name = item.get("document")

        if name:
            name = str(name).strip()

            # Dify 文档名没必要保留 .pdf
            if name.lower().endswith(".pdf"):
                name = name[:-4]

            return name

    folder_name = bundle_dir.name

    # 例如：
    # ZRDDS安装配置手册-C-C++__929862b439e73433
    if "__" in folder_name:
        folder_name = folder_name.split(
            "__",
            1
        )[0]

    return folder_name


# ============================================================
# Dify 文档相关
# ============================================================

def create_document(document_name):
    """
    创建临时占位文档。

    首个文档同时明确指定：
    - high_quality
    - BAAI/bge-m3
    - SiliconFlow
    """

    url = (
        f"{BASE_URL}/datasets/"
        f"{DATASET_ID}/document/create-by-text"
    )

    payload = {
        "name": document_name,
        "text": PLACEHOLDER_TEXT,

        "indexing_technique":
            INDEXING_TECHNIQUE,

        "embedding_model":
            EMBEDDING_MODEL,

        "embedding_model_provider":
            EMBEDDING_PROVIDER,

        "doc_form":
            DOC_FORM,

        "doc_language":
            "Chinese",

        "process_rule": {
            "mode": "custom",

            "rules": {
                "pre_processing_rules": [],

                "segmentation": {
                    "separator":
                        "\n<<<NEVER_SPLIT>>>\n",

                    "max_tokens":
                        MAX_TOKENS,

                    "chunk_overlap":
                        0,
                }
            }
        }
    }

    response = request_or_raise(
        "POST",
        url,
        json=payload,
        timeout=60
    )

    data = response.json()

    document_id = data["document"]["id"]
    batch = data["batch"]

    return document_id, batch


def get_document(document_id):
    """取得 Dify 文档详情。"""

    url = (
        f"{BASE_URL}/datasets/"
        f"{DATASET_ID}/documents/"
        f"{document_id}"
    )

    response = request_or_raise(
        "GET",
        url,
        timeout=30
    )

    return response.json()


def wait_until_completed(
    document_id,
    poll_interval=2,
    timeout_seconds=300
):
    """等待占位文档完成索引。"""

    start_time = time.time()

    last_status = None

    while True:

        data = get_document(document_id)

        status = data.get(
            "indexing_status"
        )

        if status != last_status:
            print(
                f"    索引状态：{status}"
            )

            last_status = status

        if status == "completed":
            return

        if status == "error":
            raise RuntimeError(
                "Dify 文档索引失败："
                f"{data.get('error')}"
            )

        if (
            time.time() - start_time
            > timeout_seconds
        ):
            raise TimeoutError(
                "等待 Dify 索引完成超时。"
            )

        time.sleep(poll_interval)


# ============================================================
# 占位分段
# ============================================================

def list_segments(document_id):
    """获取文档中的所有 segment。"""

    url = (
        f"{BASE_URL}/datasets/"
        f"{DATASET_ID}/documents/"
        f"{document_id}/segments"
    )

    all_segments = []

    page = 1
    limit = 100

    while True:

        response = request_or_raise(
            "GET",
            url,
            params={
                "page": page,
                "limit": limit,
            },
            timeout=30
        )

        data = response.json()

        current = data.get(
            "data",
            []
        )

        all_segments.extend(current)

        if len(current) < limit:
            break

        page += 1

    return all_segments


def delete_segment(
    document_id,
    segment_id
):
    """删除单个 segment。"""

    url = (
        f"{BASE_URL}/datasets/"
        f"{DATASET_ID}/documents/"
        f"{document_id}/segments/"
        f"{segment_id}"
    )

    response = SESSION.delete(
        url,
        headers=HEADERS,
        timeout=30
    )

    if response.status_code not in (
        200,
        204
    ):

        print(
            "删除分段失败：",
            response.status_code,
            response.text
        )

        response.raise_for_status()


def remove_placeholder(document_id):
    """删除初始化产生的占位 segment。"""

    segments = list_segments(
        document_id
    )

    removed = 0

    for segment in segments:

        content = str(
            segment.get(
                "content",
                ""
            )
        ).strip()

        if (
            PLACEHOLDER_TEXT
            in content
        ):
            delete_segment(
                document_id,
                segment["id"]
            )

            removed += 1

    if removed:
        print(
            f"    已删除 {removed} 个占位分段"
        )
    else:
        print(
            "    未发现占位分段"
        )


# ============================================================
# 正式导入 chunks
# ============================================================

def build_segment(item):
    """
    Dify 中只放真正知识正文。

    chunk_id / page / images 等信息
    保存在 dify_segment_map.json。
    """

    content = str(
        item.get(
            "content",
            ""
        )
    ).strip()

    return {
        "content": content
    }


def normalize_images(
    images,
    bundle_name
):
    """
    给图片信息增加 bundle_dir。

    后端以后可以根据：

    backend/data/hybrid/
        + bundle_dir
        + image.path

    找到真正图片。

    不写 Windows 绝对路径，
    避免换电脑后失效。
    """

    result = []

    if not isinstance(images, list):
        return result

    for image in images:

        if not isinstance(
            image,
            dict
        ):
            continue

        normalized = dict(image)

        normalized["bundle_dir"] = (
            bundle_name
        )

        result.append(normalized)

    return result


def add_segments(
    document_id,
    document_name,
    chunks,
    bundle_dir,
    batch_size=20
):
    """
    批量创建 Dify segments。

    同时生成 segment -> chunk 映射。
    """

    url = (
        f"{BASE_URL}/datasets/"
        f"{DATASET_ID}/documents/"
        f"{document_id}/segments"
    )

    mappings = []

    total = len(chunks)

    for start in range(
        0,
        total,
        batch_size
    ):

        current_chunks = chunks[
            start:start + batch_size
        ]

        payload = {
            "segments": [
                build_segment(item)
                for item
                in current_chunks
            ]
        }

        response = request_or_raise(
            "POST",
            url,
            json=payload,
            timeout=180
        )

        result = response.json()

        created = result.get(
            "data",
            []
        )

        if (
            len(created)
            != len(current_chunks)
        ):
            raise RuntimeError(
                "Dify 返回分段数量异常："
                f"提交 "
                f"{len(current_chunks)}，"
                f"返回 {len(created)}"
            )

        for original, segment in zip(
            current_chunks,
            created
        ):

            mapping = {
                "segment_id":
                    segment["id"],

                "document_id":
                    document_id,

                "document":
                    original.get(
                        "document",
                        document_name
                    ),

                "chunk_id":
                    original.get(
                        "chunk_id"
                    ),

                "section":
                    original.get(
                        "section"
                    ),

                "page":
                    original.get(
                        "page"
                    ),

                "bundle_dir":
                    bundle_dir.name,

                "images":
                    normalize_images(
                        original.get(
                            "images",
                            []
                        ),
                        bundle_dir.name
                    )
            }

            # 如果将来队友增加代码块等字段，
            # 这里也可以继续保留。
            if "code_blocks" in original:
                mapping["code_blocks"] = (
                    original["code_blocks"]
                )

            mappings.append(
                mapping
            )

        end = start + len(
            current_chunks
        )

        print(
            f"    已导入 "
            f"{end}/{total} 个分段"
        )

        time.sleep(0.3)

    return mappings


# ============================================================
# 保存映射
# ============================================================

def save_map(mappings):
    """保存所有文档的统一映射文件。"""

    OUTPUT_MAP.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with OUTPUT_MAP.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            mappings,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "\n映射文件已生成："
    )

    print(
        f"  {OUTPUT_MAP}"
    )


# ============================================================
# 单文档导入
# ============================================================

def import_one_document(
    item,
    limit=None
):
    bundle_dir = item[
        "bundle_dir"
    ]

    jsonl_path = item[
        "jsonl_path"
    ]

    print(
        "\n"
        + "=" * 70
    )

    print(
        f"处理目录：{bundle_dir.name}"
    )

    chunks = load_chunks(
        jsonl_path
    )

    if limit is not None:
        chunks = chunks[:limit]

    if not chunks:
        print(
            "  没有有效 chunk，跳过。"
        )

        return []

    document_name = (
        infer_document_name(
            chunks,
            bundle_dir
        )
    )

    print(
        f"  Dify 文档名："
        f"{document_name}"
    )

    print(
        f"  chunk 数："
        f"{len(chunks)}"
    )

    print(
        "  [1/4] 创建 Dify 文档"
    )

    document_id, batch = (
        create_document(
            document_name
        )
    )

    print(
        f"    document_id: "
        f"{document_id}"
    )

    print(
        f"    batch: {batch}"
    )

    print(
        "  [2/4] 等待索引"
    )

    wait_until_completed(
        document_id
    )

    print(
        "  [3/4] 删除占位分段"
    )

    remove_placeholder(
        document_id
    )

    print(
        "  [4/4] 导入预切分 chunk"
    )

    mappings = add_segments(
        document_id=document_id,
        document_name=document_name,
        chunks=chunks,
        bundle_dir=bundle_dir,
    )

    print(
        f"  √ {document_name} "
        f"导入完成，"
        f"{len(mappings)} 个分段"
    )

    return mappings


# ============================================================
# main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "批量导入预处理后的 "
            "ZRDDS chunks.jsonl 到 Dify"
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "每个文档最多导入多少个 chunk。"
            "测试时可用 --limit 3；"
            "默认全部导入。"
        )
    )

    args = parser.parse_args()

    check_config()

    documents = discover_documents()

    print(
        "=" * 70
    )

    print(
        "ZRDDS 批量导入 Dify"
    )

    print(
        "=" * 70
    )

    print(
        f"项目目录：{PROJECT_ROOT}"
    )

    print(
        f"扫描目录：{HYBRID_ROOT}"
    )

    print(
        f"目标 dataset："
        f"{DATASET_ID}"
    )

    print(
        f"Embedding："
        f"{EMBEDDING_MODEL}"
    )

    print()

    if not documents:

        print(
            "没有找到任何 "
            "chunks.jsonl。"
        )

        return

    print(
        f"发现 {len(documents)} "
        f"个待导入文档："
    )

    for i, item in enumerate(
        documents,
        1
    ):
        print(
            f"  {i}. "
            f"{item['bundle_dir'].name}"
        )

    if args.limit is not None:

        print(
            f"\n测试模式："
            f"每个文档最多 "
            f"{args.limit} 个 chunk"
        )

    all_mappings = []

    success_documents = 0

    failed_documents = []

    for item in documents:

        try:

            mappings = (
                import_one_document(
                    item,
                    limit=args.limit
                )
            )

            all_mappings.extend(
                mappings
            )

            success_documents += 1

        except Exception as exc:

            print(
                "\n[导入失败]"
            )

            print(
                item[
                    "bundle_dir"
                ].name
            )

            print(
                str(exc)
            )

            failed_documents.append(
                {
                    "bundle_dir":
                        item[
                            "bundle_dir"
                        ].name,

                    "error":
                        str(exc)
                }
            )

    save_map(
        all_mappings
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "批量导入结束"
    )

    print(
        "=" * 70
    )

    print(
        f"成功文档："
        f"{success_documents}"
    )

    print(
        f"失败文档："
        f"{len(failed_documents)}"
    )

    print(
        f"成功分段："
        f"{len(all_mappings)}"
    )

    if failed_documents:

        print(
            "\n失败列表："
        )

        for item in failed_documents:

            print(
                f"  - "
                f"{item['bundle_dir']}"
            )

            print(
                f"    "
                f"{item['error']}"
            )


if __name__ == "__main__":
    main()