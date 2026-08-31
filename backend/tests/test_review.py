import unittest
from types import SimpleNamespace

from app.services.rag import SourceReference
from app.services.review import parse_review_findings, retrieve_review_chunks


class ParseReviewFindingsTests(unittest.TestCase):
    def test_only_accepts_findings_referencing_provided_sources(self) -> None:
        sources = [SourceReference(chunk_id=9, path="app/main.py", start_line=10, end_line=18)]
        findings = parse_review_findings(
            """{
                "findings": [
                    {
                        "severity": "medium",
                        "category": "bugs",
                        "description": "The error is returned without a status code.",
                        "source_number": 1,
                        "suggested_improvement": "Return an explicit HTTP status code."
                    },
                    {
                        "severity": "high",
                        "category": "security",
                        "description": "Unsupported claim",
                        "source_number": 2,
                        "suggested_improvement": "Do something."
                    }
                ]
            }""",
            sources,
            maximum_findings=10,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].source.path, "app/main.py")
        self.assertEqual(findings[0].category, "bugs")


class RetrieveReviewChunksTests(unittest.TestCase):
    def test_caps_chunks_and_unique_files(self) -> None:
        responses = iter(
            [
                [match(1, "first.py"), match(2, "second.py")],
                [match(2, "second.py"), match(3, "third.py")],
                [match(4, "fourth.py")],
            ]
        )

        from app.services import review

        original = review.find_similar_chunks
        review.find_similar_chunks = lambda *_args: next(responses)
        try:
            matches = retrieve_review_chunks(None, 1, None, max_chunks=3, max_files=2)
        finally:
            review.find_similar_chunks = original

        self.assertEqual([item.chunk.id for item in matches], [1, 2])
        self.assertEqual([item.path for item in matches], ["first.py", "second.py"])


def match(chunk_id: int, path: str):
    return SimpleNamespace(chunk=SimpleNamespace(id=chunk_id), path=path)


if __name__ == "__main__":
    unittest.main()
