"""Small, dependency-free tokenizer for Chinese and technical documentation."""

import re
from typing import List


# Keep technical identifiers intact where possible: dots, underscores, plus and hyphen
# occur frequently in library names, flags, symbols and version strings.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+\-]*|\d+(?:\.\d+)+(?:\.x)?|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [token.lower() for token in _TOKEN_RE.findall(str(text))]

