"""Small Qwen3-VL client and conservative image-value handling."""

from __future__ import annotations

import base64
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - exercised by unconfigured environments
    httpx = None

IMAGE_TYPES = {
    "operation_screenshot", "configuration_screenshot", "code_or_config",
    "terminal_or_log", "table_image", "architecture_or_flow", "ignore", "unknown",
}
PROMPT_VERSION = "qwen-vl-json-v5.1-late-source-visual-fix"


def classify_image(raw_type: str | None, caption: str | None = None) -> str:
    value = f"{raw_type or ''} {caption or ''}".lower()
    if "table" in value:
        return "table_image"
    if "logo" in value or "装饰" in value:
        return "ignore"
    return "unknown"


def normalize_image_type(raw_type: Any) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(raw_type or "").lower()).strip("_")
    if value in {"table", "table_image", "table_figure"}:
        return "table_image"
    if value in {"installer", "installer_window", "installer_wizard", "dialog_box", "dialog", "screenshot", "operation_screenshot", "operation"} or "installer" in value or "dialog" in value:
        return "operation_screenshot"
    if value in {"configuration", "configuration_screenshot", "ide_configuration", "settings"} or "configuration" in value:
        return "configuration_screenshot"
    if value in {"terminal", "terminal_output", "console", "console_output", "log", "log_screenshot", "debug_log", "terminal_or_log", "shell_output"} or "terminal" in value or "console" in value or "debug_log" in value:
        return "terminal_or_log"
    if value in {"code", "code_screenshot", "code_snippet", "code_block", "configuration_snippet", "code_or_config", "command", "shell"} or "command" in value or "code_snippet" in value:
        return "code_or_config"
    if value in {"flowchart", "architecture", "architecture_or_flow", "diagram", "flow"}:
        return "architecture_or_flow"
    if value in {"ignore", "logo", "decorative", "decoration"}:
        return "ignore"
    return "unknown"


def _technical_values(value: Any, label: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        result = []
        for key, nested in value.items():
            result.extend(_technical_values(nested, str(key)))
        return result
    if isinstance(value, list):
        result = []
        for nested in value:
            result.extend(_technical_values(nested, label))
        return result
    if value is None:
        return []
    return [(label, str(value))]


def filter_images(images: list[Any], image_root: Path) -> list[Any]:
    """Keep every valid source occurrence; never deduplicate by image bytes.

    The same XObject/bitmap can legitimately occur multiple times, even on the
    same page and at overlapping coordinates.  Hash/path equality is therefore
    not a deletion rule.  Canonical occurrence identity is carried by
    image_id/order/source_occurrence_id downstream.
    """
    retained: list[Any] = []
    ignored_types = ("logo", "decorative", "decoration", "background", "watermark")
    for image in images:
        raw_type = (image.raw_type or "").lower()
        if not image.image_path:
            retained.append(image)
            continue
        path = Path(image.image_path)
        source = path if path.is_absolute() else image_root / path
        if raw_type in ignored_types or any(term in (image.caption or "").lower() for term in ignored_types):
            continue
        if not source.is_file():
            # Missing MinerU export is recoverable from the source PDF.
            retained.append(image)
            continue
        retained.append(image)
    return retained

def _parse_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S | re.I)
    if fenced:
        candidate = fenced.group(1)
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start:end + 1]
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("VLM response JSON must be an object")
    return value


def _technical_review(raw_ocr: str | None, values: list[Any], context: str = "") -> tuple[list[dict[str, Any]], bool]:
    raw = raw_ocr or ""
    result = []
    needs_review = False
    for label, text in _technical_values(values):
        normalized = _normalise_technical(text)
        evidence = _normalise_technical(f"{raw}\n{context}")
        verified = bool(normalized and normalized in evidence)
        needs_review = needs_review or not verified
        result.append({"label": label or None, "raw_ocr": raw or None, "vlm_value": text, "verified_value": text if verified else None, "needs_review": not verified})
    return result, needs_review


def _normalise_technical(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("/", "\\").lower()



def _normalise_code_for_compare(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).replace("–", "-").replace("—", "-").replace("−", "-")
    value = value.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", "", value)


def _code_similarity(left: str | None, right: str | None) -> float:
    left_norm = _normalise_code_for_compare(left)
    right_norm = _normalise_code_for_compare(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()




def _technical_context_anchors(context: str) -> dict[str, set[str]]:
    """Extract only source-backed technical strings that may safely repair OCR typos.

    These anchors come exclusively from nearby selectable PDF source text.
    They are never invented from a product dictionary.
    """
    # Only selectable/source PDF text is trusted for correction anchors.
    # MinerU/OCR may contain the same typo as the VLM candidate and must never
    # become a correction source; it is used later for validation only.
    evidence = str(context or "")
    anchors: dict[str, set[str]] = {
        "env": set(),
        "identifier": set(),
        "library": set(),
        "keyword": set(),
    }
    anchors["env"].update(re.findall(r"\$\([A-Za-z_][A-Za-z0-9_]*\)", evidence))
    # Long technical identifiers are useful only when they are visibly/source-text
    # backed.  Restrict to ZRDDS/interface/macro-like names to avoid rewriting prose.
    for token in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]{5,}(?![A-Za-z0-9_])", evidence):
        if (
            "ZRDDS" in token.upper()
            or token.endswith("Interface")
            or token.startswith("_")
            or (token.isupper() and "_" in token)
        ):
            anchors["identifier"].add(token)
    for name in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_+-]*\.lib\b", evidence, re.I):
        anchors["library"].add(name[:-4])
    for keyword in ("QT", "TARGET", "CONFIG", "TEMPLATE", "SOURCES", "HEADERS", "INCLUDEPATH", "LIBS", "DEFINES"):
        if re.search(rf"(?<![A-Za-z0-9_]){keyword}(?![A-Za-z0-9_])", evidence):
            anchors["keyword"].add(keyword)
    return anchors


def _best_unique_anchor(token: str, anchors: set[str], *, threshold: float = 0.90) -> str | None:
    if not token or not anchors:
        return None
    scored = sorted(
        ((SequenceMatcher(None, token.lower(), anchor.lower()).ratio(), anchor) for anchor in anchors),
        reverse=True,
    )
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.035:
        return None
    return scored[0][1]


def correct_code_with_source_context(candidate: str, *, context: str = "", mineru_ocr: str | None = None) -> tuple[str, list[dict[str, str]]]:
    """Conservatively repair OCR substitutions using only source-backed anchors.

    The visual transcription remains the primary result.  This function may only
    replace a suspicious technical token when a unique, very similar token is
    already present in nearby selectable PDF source text.  MinerU/OCR is
    validation-only evidence and can never provide correction anchors.  It never inserts
    new lines or merges recognizer outputs.
    """
    text = str(candidate or "")
    if not text.strip():
        return text, []
    anchors = _technical_context_anchors(context)
    changes: list[dict[str, str]] = []

    def record(before: str, after: str, reason: str) -> str:
        if before != after:
            changes.append({"from": before, "to": after, "reason": reason})
        return after

    # Common OCR shape error around qmake environment variables.  Rewrite only
    # when the exact $(NAME) form exists in source evidence.
    env_names = {value[2:-1]: value for value in anchors["env"]}
    def fix_env(match: re.Match[str]) -> str:
        whole = match.group(0)
        name = match.group(1)
        best = _best_unique_anchor(name, set(env_names), threshold=0.88)
        if not best:
            return whole
        target = env_names[best]
        return record(whole, target, "source_env_anchor")
    text = re.sub(r"(?:\$\$?\(|\$\$?\{)([A-Za-z_][A-Za-z0-9_]*)(?:\)|\})", fix_env, text)

    # Repair long identifiers such as ZRDDSCozInterface / CPPIINTERFACE only
    # against uniquely matching identifiers that occur in source evidence.
    def fix_identifier(match: re.Match[str]) -> str:
        token = match.group(0)
        best = _best_unique_anchor(token, anchors["identifier"], threshold=0.90)
        if best and best != token:
            return record(token, best, "source_identifier_anchor")
        return token
    text = re.sub(r"(?<![-A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]{5,}(?![A-Za-z0-9_])", fix_identifier, text)

    # qmake libraries omit the .lib suffix.  Compare only the stem against .lib
    # names already present in source text.
    def fix_library(match: re.Match[str]) -> str:
        prefix, token = match.group(1), match.group(2)
        best = _best_unique_anchor(token, anchors["library"], threshold=0.90)
        if best and best != token:
            return prefix + record(token, best, "source_library_anchor")
        return match.group(0)
    text = re.sub(r"(?<![A-Za-z0-9_])(-l)([A-Za-z_][A-Za-z0-9_]*)", fix_library, text)

    # A single OCR stroke can appear immediately before a known qmake keyword.
    # Remove only | when the following keyword is source-backed.
    if anchors["keyword"]:
        keyword_alt = "|".join(sorted(map(re.escape, anchors["keyword"]), key=len, reverse=True))
        def fix_pipe(match: re.Match[str]) -> str:
            return record(match.group(0), match.group(1) + match.group(2), "source_keyword_anchor")
        text = re.sub(rf"(?m)^(\s*)\|({keyword_alt})\b", fix_pipe, text)

    return text, changes


def _code_validation(primary: str, mineru_ocr: str | None, context: str = "", *, vlm_confidence: str = "") -> dict[str, Any]:
    """Validate one authoritative VLM transcription without editing or merging it.

    The VLM transcription is the only candidate allowed to become canonical code.
    MinerU/PDF text are evidence only: they may confirm or flag/reject the candidate,
    but they never contribute characters or lines to the generated code.
    """
    candidate = str(primary or "").strip()
    mineru = str(mineru_ocr or "").strip()
    context = str(context or "").strip()
    confidence = str(vlm_confidence or "").lower()
    mineru_similarity = _code_similarity(candidate, mineru) if mineru else None
    context_similarity = _code_similarity(candidate, context) if context else None

    if not candidate:
        return {
            "status": "primary_transcription_empty",
            "accepted": False,
            "needs_review": True,
            "mineru_similarity": mineru_similarity,
            "context_similarity": context_similarity,
            "vlm_confidence": confidence or None,
        }

    # Strong independent agreement: safe to publish.
    if mineru_similarity is not None and mineru_similarity >= 0.88:
        status, accepted, review = "verified_primary", True, False
    # Moderate support still publishes the single VLM candidate, but makes the
    # uncertainty explicit.  Evidence never rewrites the candidate.
    elif mineru_similarity is not None and mineru_similarity >= 0.68:
        status, accepted, review = "primary_review", True, True
    # If MinerU disagrees heavily, trust a high-confidence dedicated visual
    # transcription enough to keep it visible, but mark it for review.  Low
    # confidence + strong disagreement is rejected rather than guessed.
    elif mineru_similarity is not None:
        if confidence == "high":
            status, accepted, review = "primary_review", True, True
        else:
            status, accepted, review = "primary_rejected", False, True
    else:
        # Raster-only code often has no reliable PDF/MinerU text layer. A
        # dedicated high/medium-confidence VLM transcription may still be useful,
        # but remains explicitly unverified.
        if confidence in {"high", "medium"}:
            status, accepted, review = "primary_unverified", True, True
        else:
            status, accepted, review = "primary_rejected", False, True

    return {
        "status": status,
        "accepted": accepted,
        "needs_review": review,
        "mineru_similarity": round(mineru_similarity, 4) if mineru_similarity is not None else None,
        "context_similarity": round(context_similarity, 4) if context_similarity is not None else None,
        "vlm_confidence": confidence or None,
    }


def _image_mime(image_path: Path) -> str:
    suffix = Path(image_path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jp2": "image/jp2",
        ".jpx": "image/jp2",
    }.get(suffix, "application/octet-stream")


def _precise_code_payload(encoded: str, model: str, mime: str) -> dict[str, Any]:
    prompt = """Return JSON only. You are transcribing a code/configuration screenshot. Copy ONLY the visible code/configuration text exactly as shown. Preserve source line order, line breaks, indentation, underscores, dollar signs, parentheses, braces, backslashes, plus/minus/equal signs, hyphens, dots and letter case. Do not use surrounding document context. Do not merge repeated lines, do not add line numbers unless line numbers are visibly printed in the screenshot, and do not repair or normalize identifiers. If a character cannot be read reliably, keep the closest visible transcription and set confidence to low instead of inventing extra lines. Schema: {"code_content":"","confidence":"high|medium|low"}"""
    return {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}],
        "temperature": 0,
    }


def transcribe_code_image(image_path: Path, *, mineru_ocr: str | None = None, context: str = "", timeout: float = 60.0, retries: int = 2) -> dict[str, Any]:
    """Produce one authoritative visual transcription and validate it without merging evidence."""
    if os.getenv("ENABLE_VLM", "true").lower() in {"0", "false", "no", "off"} or os.getenv("TEST_MODE", "").lower() == "true":
        return {"code_content": None, "parse_status": "vlm_disabled", "needs_review": True, "code_verification": {"status": "vlm_disabled", "accepted": False, "needs_review": True}}
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    if httpx is None:
        raise RuntimeError("缺少依赖：httpx；用途：Qwen3-VL HTTP API 调用")
    model = os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus")
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    payload = _precise_code_payload(encoded, model, _image_mime(Path(image_path)))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for _attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
            raw = data["choices"][0]["message"]["content"]
            if isinstance(raw, list):
                raw = " ".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in raw)
            parsed = _parse_json(str(raw))
            candidate = str(parsed.get("code_content") or "").strip()
            confidence = str(parsed.get("confidence") or "").lower()
            corrected, corrections = correct_code_with_source_context(
                candidate, context=context, mineru_ocr=mineru_ocr
            )
            validation = _code_validation(corrected, mineru_ocr, context, vlm_confidence=confidence)
            validation["source_context_corrections"] = corrections
            if corrections and validation.get("status") in {"primary_review", "primary_unverified"}:
                validation["status"] = "primary_context_corrected"
            return {
                "code_content": corrected if validation.get("accepted") else None,
                "code_content_candidate": candidate or None,
                "code_content_corrected": corrected or None,
                "code_context_corrections": corrections,
                "code_transcription_confidence": confidence or None,
                "code_verification": validation,
                "code_transcription_raw_response": str(raw),
                "needs_review": bool(validation.get("needs_review")),
            }
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    return {
        "code_content": None,
        "code_content_candidate": None,
        "code_transcription_confidence": None,
        "code_verification": {
            "status": "primary_transcription_failed",
            "accepted": False,
            "needs_review": True,
            "error": str(last_error),
        },
        "needs_review": True,
    }


def enrich_image(image_path: Path, *, document: str, section: str | None, context_before: str, context_after: str, mineru_ocr: str | None, timeout: float = 60.0, retries: int = 2) -> dict[str, Any]:
    """Call Qwen only when explicitly configured; return auditable failures."""
    if os.getenv("ENABLE_VLM", "true").lower() in {"0", "false", "no", "off"} or os.getenv("TEST_MODE", "").lower() == "true":
        return {"image_type": "unknown", "raw_image_type": "unknown", "description": "", "key_information": [], "technical_values": [], "parse_status": "vlm_disabled", "needs_review": True, "verified_by_image": False, "supported_by_context": False}
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    if httpx is None:
        raise RuntimeError("缺少依赖：httpx；用途：Qwen3-VL HTTP API 调用")
    model = os.getenv("QWEN_VL_MODEL", "qwen3-vl-plus")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    prompt = f"""Return JSON only. Do not invent information. Judge the attached image itself first; document context is only for locating the figure and must not be used to invent pixels.

Classify image_type as one of: operation_screenshot, configuration_screenshot, code_or_config, terminal_or_log, table_image, architecture_or_flow, unknown.

Output policy:
- operation_screenshot / configuration_screenshot / architecture_or_flow / unknown: write one concise, concrete description and 2-6 key_information items containing the important visible buttons, labels, values, paths, nodes, states or relationships. Avoid generic phrases.
- terminal_or_log: this is runtime/console/log OUTPUT, not source code. Write a concise description plus 2-8 key_information items containing the important visible error/status/log lines and values. Set code_content to null.
- code_or_config: this is source code or configuration-file content. Return code_content as one exact multiline string copied from visible lines, preserving indentation, blank lines, equals signs, dollar signs, backslashes and continuation characters. Do not narrate the code; description may be empty.
- table_image: extract only clearly readable table facts; do not guess cells.

For technical values, include only values visibly readable in the image or independently present in the supplied OCR/context. If uncertain, omit rather than guess.
Document: {document}
Section: {section or ''}
Context before: {context_before}
Context after: {context_after}
MinerU OCR candidate: {mineru_ocr or ''}
Schema: {{"image_type":"unknown","caption":"","description":"","code_content":null,"key_information":[],"technical_values":[],"context_consistency":null,"context_conflict":null,"confidence":"uncertain"}}"""
    mime = _image_mime(image_path)
    payload = {"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}], "temperature": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                response_data = response.json()
            raw_response = response_data["choices"][0]["message"]["content"]
            if isinstance(raw_response, list):
                raw_response = " ".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in raw_response)
            parsed = _parse_json(str(raw_response))
            image_type = parsed.get("image_type", "unknown")
            parsed["raw_image_type"] = image_type
            parsed["image_type"] = normalize_image_type(image_type)
            code_keys = parsed.get("key_information", [])
            has_code_key = any(re.match(r"^[A-Z][A-Z0-9_]*(?:\s*(?:\+=|-=|:=|\?=|=)\s*)", str(value)) for value in code_keys)
            if parsed["image_type"] == "unknown" and (parsed.get("code_content") or has_code_key):
                parsed["image_type"] = "code_or_config"
            values, review = _technical_review(mineru_ocr, parsed.get("technical_values", []), f"{context_before}\n{context_after}")
            parsed["technical_values_review"] = values
            parsed["needs_review"] = bool(parsed.get("needs_review", False) or review)

            # V5: code/config uses exactly one dedicated, context-free visual
            # transcription as the canonical candidate. The general VLM pass
            # only classifies/describes the image; MinerU/PDF text validates but
            # never contributes characters or lines.
            if parsed["image_type"] == "code_or_config":
                parsed["classification_code_content"] = parsed.get("code_content")
                code_result = transcribe_code_image(
                    image_path,
                    mineru_ocr=mineru_ocr,
                    context=f"{context_before}\n{context_after}",
                    timeout=timeout,
                    retries=retries,
                )
                parsed.update(code_result)

            parsed["parse_status"] = "success"
            parsed["raw_response"] = str(raw_response)
            return parsed
        except (httpx.HTTPError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
    return {"image_type": "unknown", "parse_status": "failed", "needs_review": True, "error": str(last_error), "raw_response": None}


__all__ = ["PROMPT_VERSION", "classify_image", "correct_code_with_source_context", "enrich_image", "filter_images", "transcribe_code_image"]
