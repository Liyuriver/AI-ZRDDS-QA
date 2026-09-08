"""Small, dependency-free tokenizer for Chinese and technical documentation."""

import re
from typing import List


# Keep technical identifiers intact where possible: dots, underscores, plus and hyphen
# occur frequently in library names, flags, symbols and version strings.
_TECHNICAL_PHRASES = (
    "收不到数据", "配置检测", "网络环境", "故障排查", "匹配过程", "数据类型",
    "类型不一致", "类型一致", "反序列化", "序列化", "生成文件", "监听器",
    "可靠通信", "尽力而为", "死锁", "DomainParticipant", "take_next_sample",
    "return_loan", "DATA_AVAILABLE",
)
_TOKEN_RE = re.compile(
    "|".join(
        [
            *(re.escape(item) for item in sorted(_TECHNICAL_PHRASES, key=len, reverse=True)),
            r"[A-Za-z][A-Za-z0-9_.+\-]*",
            r"\d+(?:\.\d+)+(?:\.x)?",
            r"[\u4e00-\u9fff]",
        ]
    )
)


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [token.lower() for token in _TOKEN_RE.findall(str(text))]

