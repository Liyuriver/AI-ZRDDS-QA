import asyncio

from app.services.metadata.version_service import extract_version
from app.services.qa.answer_decision_service import REFUSAL_LOW, REFUSAL_VERSION, decide_answer
from app.services.qa.confidence_service import calculate_confidence, normalize_evidence
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


def test_quote_evidence_is_not_misclassified_as_no_evidence():
    evidence = [
        {"quote": "listener evidence", "score": 0.5172, "version": None},
        {"quote": "supporting evidence", "score": 0.44, "version": None},
        {"quote": "supporting evidence 2", "raw_score": 0.40, "version": None},
        {"quote": "supporting evidence 3", "rerank_score": 0.35, "version": None},
    ]
    normalized = normalize_evidence(evidence)
    result = calculate_confidence(normalized, "UNKNOWN", "2.0")
    assert len(normalized) == 4
    assert result["confidence_score"] > 0
    assert result["confidence_reasons"] != ["no_evidence"]
    assert "version_unknown" in result["confidence_reasons"]


def test_missing_score_is_still_evidence():
    result = calculate_confidence([{"quote": "known evidence", "version": None}], "UNKNOWN", None)
    assert result["confidence_score"] > 0
    assert "missing_retrieval_score" in result["confidence_reasons"]
    assert "no_evidence" not in result["confidence_reasons"]


class FakeAI:
    async def query(self, question, **kwargs):
        return {"answer": "unsafe", "status": "answered", "sources": [ev()], "evidence": [ev()]}


def test_question_keeps_original_and_gates_result():
    result = asyncio.run(answer_question(" Psapi.lib? V2.0 ", ai_client=FakeAI()))
    assert result["original_query"] == " Psapi.lib? V2.0 "
    assert "Psapi.lib" in result["rag_query"]
    assert result["answer_status"] == "ANSWER"


class ScenarioAI:
    def __init__(self, evidence):
        self.evidence = evidence

    async def query(self, question, **kwargs):
        return {"answer": "Dify 原始猜测答案", "evidence": self.evidence}


def test_no_evidence_returns_no_answer_and_hides_raw_answer():
    result = asyncio.run(answer_question("未知问题", ai_client=ScenarioAI([])))
    assert result["answer_status"] == "NO_ANSWER"
    assert result["confidence_score"] == 0
    assert result["confidence_level"] == "LOW"
    assert "no_evidence" in result["confidence_reasons"]
    assert result["answer"] == REFUSAL_LOW
    assert "Dify 原始猜测答案" not in result["answer"]
    assert result["evidence"] == []


def test_weak_evidence_returns_low_confidence_refusal():
    evidence = [ev(score=0.30, content="weak 1"), ev(score=0.28, content="weak 2")]
    result = asyncio.run(answer_question("普通问题", ai_client=ScenarioAI(evidence)))
    assert len(result["evidence"]) == 2
    assert result["answer_status"] == "LOW_CONFIDENCE"
    assert result["confidence_level"] == "LOW"
    assert 0 < result["confidence_score"] < 0.50
    assert "no_evidence" not in result["confidence_reasons"]
    assert result["answer"] == REFUSAL_LOW


def test_version_mismatch_returns_version_uncertain():
    evidence = [ev(score=0.90, version="1.0")]
    result = asyncio.run(answer_question("API 配置问题", version="V2.0", ai_client=ScenarioAI(evidence)))
    assert result["requested_version"] == "V2.0"
    assert result["effective_version"] == "V2.0"
    assert result["version_status"] == "MISMATCH"
    assert result["answer_status"] == "VERSION_UNCERTAIN"


def test_mixed_versions_return_version_uncertain():
    evidence = [ev(score=0.90, version="1.0"), ev(score=0.85, version="2.0")]
    result = asyncio.run(answer_question("API 配置问题", version="V2.0", ai_client=ScenarioAI(evidence)))
    assert result["version_status"] == "MIXED"
    assert result["answer_status"] == "VERSION_UNCERTAIN"


def test_normal_evidence_still_returns_answer():
    result = asyncio.run(answer_question("API 配置问题", version="V2.0",
                                         ai_client=ScenarioAI([ev(), ev(score=0.85)])))
    assert result["version_status"] == "MATCHED"
    assert result["answer_status"] == "ANSWER"
    assert result["answer"] == "Dify 原始猜测答案"


def test_null_evidence_version_remains_unknown():
    result = asyncio.run(answer_question("API 配置问题", version="V2.0",
                                         ai_client=ScenarioAI([ev(version=None)])))
    assert result["version_status"] == "UNKNOWN"
    assert result["evidence"][0]["version"] is None


def test_answer_decision_priority_matrix():
    assert decide_answer([ev()], "LOW", "MISMATCH", True, "1.0")[0] == "VERSION_UNCERTAIN"
    assert decide_answer([ev()], "LOW", "MIXED", True, "2.0")[0] == "VERSION_UNCERTAIN"
    assert decide_answer([ev()], "LOW", "MATCHED", True, "2.0")[0] == "LOW_CONFIDENCE"
    assert decide_answer([ev()], "LOW", "UNKNOWN", True, "2.0")[0] == "LOW_CONFIDENCE"
    assert decide_answer([], "LOW", "UNKNOWN", False, None) == ("NO_ANSWER", REFUSAL_LOW)
    assert decide_answer([ev()], "MEDIUM", "MATCHED", True, "2.0")[0] == "ANSWER"
    assert decide_answer([ev()], "HIGH", "MATCHED", True, "2.0")[0] == "ANSWER"


def test_chat_handler_exposes_version_uncertain_as_standard_answer_status(monkeypatch):
    from types import SimpleNamespace
    from app.api import chat as chat_api
    from app.schemas.chat import ChatRequest

    conversation = SimpleNamespace(id="00000000-0000-0000-0000-000000000001",
                                   user_id="u1", dify_conversation_id=None)

    class FakeConversationService:
        def create_conversation(self, user_id, version=None):
            return conversation
        def save_dify_conversation_id(self, *_args): pass
        def save_user_message(self, *_args): pass
        def save_ai_message(self, *_args, **_kwargs): pass

    async def fake_answer_question(**_kwargs):
        return {"answer": REFUSAL_VERSION, "status": "insufficient_evidence",
                "answer_status": "VERSION_UNCERTAIN", "sources": [], "images": [],
                "evidence": [{"content": "x", "version": "V2.0"}],
                "confidence_score": 0.252, "confidence_level": "LOW",
                "confidence_reasons": ["version_conflict"],
                "requested_version": "V1.0", "effective_version": "V1.0",
                "version_status": "MISMATCH", "original_query": "q", "rag_query": "q"}

    monkeypatch.setattr(chat_api, "answer_question", fake_answer_question)
    response = asyncio.run(chat_api.chat(
        ChatRequest(question="q", version="V1.0", user_id="u1"), FakeConversationService()
    ))
    assert response.data.answer_status == "VERSION_UNCERTAIN"
    assert response.data.version_status == "MISMATCH"
    assert response.data.status == "insufficient_evidence"
