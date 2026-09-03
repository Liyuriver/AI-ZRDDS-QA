import asyncio

from app.services.metadata.version_service import extract_version
from app.services.qa.answer_decision_service import REFUSAL_LOW, decide_answer
from app.services.qa.confidence_service import calculate_confidence
from app.services.qa.question_service import determine_version_status, is_version_sensitive, answer_question


def ev(score=0.9, version="2.0", content="evidence"):
    return {"content": content, "raw_score": score, "version": version, "document": "guide", "page": 1}


def test_version_extraction_is_conservative():
    assert extract_version("Psapi.lib in V2.0") == "V2.0"
    assert extract_version("ZRDDS 2.0 配置") == "V2.0"
    assert extract_version("错误码 404") is None


def test_version_statuses_and_sensitivity():
    assert determine_version_status([ev(version="2.0")], "2.0", True) == "MATCHED"
    assert determine_version_status([ev(version=None)], "2.0", True) == "UNKNOWN"
    assert determine_version_status([ev(version="2.0"), ev(version="3.0")], None, True) == "MIXED"
    assert determine_version_status([ev(version="3.0")], "2.0", True) == "MISMATCH"
    assert is_version_sensitive("how to configure the API", [])


def test_confidence_and_gate_are_evidence_based():
    assert calculate_confidence([ev(), ev(score=0.85)], "MATCHED", "2.0")["confidence_level"] == "HIGH"
    assert calculate_confidence([ev(score=0.1)], "UNKNOWN", None)["confidence_level"] == "LOW"
    assert calculate_confidence([{"content": "x"}], "UNKNOWN", None)["confidence_level"] == "LOW"
    assert decide_answer([], "LOW", "UNKNOWN", False, None) == ("NO_ANSWER", REFUSAL_LOW)
    assert decide_answer([ev(), ev(score=0.85)], "HIGH", "MISMATCH", True, "2.0")[0] == "VERSION_UNCERTAIN"


class FakeAI:
    async def query(self, question, **kwargs):
        return {"answer": "unsafe", "status": "answered", "sources": [ev()], "evidence": [ev()]}


def test_question_keeps_original_and_gates_result():
    result = asyncio.run(answer_question(" Psapi.lib? V2.0 ", ai_client=FakeAI()))
    assert result["original_query"] == " Psapi.lib? V2.0 "
    assert "Psapi.lib" in result["rag_query"]
    assert result["answer_status"] == "ANSWER"
