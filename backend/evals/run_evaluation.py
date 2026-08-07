import argparse
from pathlib import Path

import yaml

from app.db import SessionLocal
from app.services.rag import REFUSAL, answer_question
from app.services.retrieval import hybrid_retrieve


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval and optional refusal behavior")
    parser.add_argument("--answers", action="store_true", help="also call the chat model for refusal evaluation")
    args = parser.parse_args()
    cases = yaml.safe_load(Path(__file__).with_name("questions.yaml").read_text(encoding="utf-8"))["questions"]
    answerable = [case for case in cases if not case.get("unanswerable")]
    unanswerable = [case for case in cases if case.get("unanswerable")]
    retrieval_hits = 0
    refusal_hits = 0
    with SessionLocal() as db:
        for case in answerable:
            results = hybrid_retrieve(db, case["question"])[:5]
            titles = {item.document.title for item in results}
            if any(expected in title for expected in case["expected_titles"] for title in titles):
                retrieval_hits += 1
        if args.answers:
            for case in unanswerable:
                result = answer_question(db, case["question"], [], [], None)
                if result.content == REFUSAL or "没有足够证据" in result.content:
                    refusal_hits += 1
    recall = retrieval_hits / len(answerable) if answerable else 0
    print(f"Top-5 document recall: {recall:.1%} ({retrieval_hits}/{len(answerable)})")
    if args.answers:
        refusal = refusal_hits / len(unanswerable) if unanswerable else 0
        print(f"Unanswerable refusal rate: {refusal:.1%} ({refusal_hits}/{len(unanswerable)})")
        return 0 if recall >= 0.85 and refusal >= 0.90 else 1
    return 0 if recall >= 0.85 else 1


if __name__ == "__main__":
    raise SystemExit(main())

