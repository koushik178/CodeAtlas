import unittest
from types import SimpleNamespace

from app.services.test_generation import detect_stack, select_file_chunks


def chunk(content: str):
    return SimpleNamespace(content=content)


class TestGenerationHelpersTests(unittest.TestCase):
    def test_detects_python_pytest_by_default(self) -> None:
        language, framework = detect_stack(
            SimpleNamespace(extension=".py", path="app/service.py", language="Python"),
            [chunk("def add(left, right):\n    return left + right")],
        )
        self.assertEqual((language, framework), ("Python", "pytest"))

    def test_prefers_chunks_matching_requested_focus(self) -> None:
        chunks = [
            SimpleNamespace(content="def unrelated(): pass", chunk_index=0),
            SimpleNamespace(content="def calculate_total(items): pass", chunk_index=1),
        ]
        selected = select_file_chunks(chunks, "calculate_total", maximum_chunks=8)
        self.assertEqual([item.chunk_index for item in selected], [1])


if __name__ == "__main__":
    unittest.main()
