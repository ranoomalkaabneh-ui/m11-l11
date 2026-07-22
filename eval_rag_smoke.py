"""RAG smoke evaluator -- 3 pre-shipped questions, binary PASS/FAIL per question."""

import json
import os
import sys

import httpx


API_URL = os.environ.get("API_URL", "http://localhost:8000")


def score_grounding(response: dict, candidate_ids) -> bool:
    """Return True iff `response` is grounded per the Lab smoke methodology."""
    citations = response.get("citations", [])

    # Condition (a): at least one citation is present.
    if len(citations) < 1:
        return False

    cited_ids = {citation.get("chunk_id") for citation in citations}
    candidate_ids = set(candidate_ids)

    # Condition (b): every cited chunk_id is in the retrieved candidate set.
    return cited_ids.issubset(candidate_ids)


def evaluate_question(question: dict) -> bool:
    """Issue one POST /rag/answer; return True iff the response is grounded."""
    response = httpx.post(
        f"{API_URL.rstrip('/')}/rag/answer",
        json={
            "question": question["question"],
            "k": question.get("k", 4),
        },
        timeout=20,
    )
    response.raise_for_status()

    body = response.json()

    candidate_ids = {
        chunk.get("chunk_id")
        for chunk in body.get("retrieved", [])
    }

    return score_grounding(body, candidate_ids)


def main() -> int:
    """Iterate the three smoke questions, print PASS/FAIL, return 0 iff all PASS."""
    fixture_path = os.path.join(os.path.dirname(__file__), "data", "rag_smoke.json")
    with open(fixture_path) as fh:
        questions = json.load(fh)

    all_grounded = True

    for question in questions:
        grounded = evaluate_question(question)
        status = "PASS" if grounded else "FAIL"
        label = question.get("id", question.get("question", "question"))

        print(f"{status}: {label}")

        if not grounded:
            all_grounded = False

    return 0 if all_grounded else 1


if __name__ == "__main__":
    sys.exit(main())