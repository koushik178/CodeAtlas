import unittest
from types import SimpleNamespace

from app.services.rag import build_context


def match(chunk_id: int, path: str, content: str, start_line: int, end_line: int):
    return SimpleNamespace(
        chunk=SimpleNamespace(
            id=chunk_id,
            content=content,
            start_line=start_line,
            end_line=end_line,
        ),
        path=path,
    )


class BuildContextTests(unittest.TestCase):
    def test_formats_source_metadata_and_preserves_retrieval_order(self) -> None:
        context, sources = build_context(
            [
                match(7, "app/main.py", "first chunk", 10, 15),
                match(8, "app/config.py", "second chunk", 2, 6),
            ],
            maximum_characters=1_000,
        )

        self.assertIn("[Source 1 | chunk_id=7 | path=app/main.py | lines=10-15]", context)
        self.assertIn("[Source 2 | chunk_id=8 | path=app/config.py | lines=2-6]", context)
        self.assertEqual([source.chunk_id for source in sources], [7, 8])

    def test_excludes_a_chunk_that_would_exceed_the_context_budget(self) -> None:
        first = match(7, "app/main.py", "short", 10, 10)
        second = match(8, "app/config.py", "x" * 500, 2, 6)
        context, sources = build_context([first, second], maximum_characters=100)

        self.assertIn("chunk_id=7", context)
        self.assertNotIn("chunk_id=8", context)
        self.assertEqual([source.chunk_id for source in sources], [7])


if __name__ == "__main__":
    unittest.main()
