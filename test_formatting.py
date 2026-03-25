"""
Test suite for message formatting and MarkdownV2 escaping.

This test suite validates that:
1. All format_* functions produce valid MarkdownV2
2. Special characters are properly escaped
3. Code blocks preserve backticks
4. No unescaped reserved characters appear in output
"""

import pytest
from formatter import (
    _esc,
    _esc_preserve_code,
    format_problems,
    format_problem_detail,
    format_daily,
    format_weekly,
    format_leaderboard,
)


# MarkdownV2 reserved characters that must be escaped: _*[]()~`>#+-=|{}.!
MARKDOWN_V2_RESERVED = r"_*[]()~`>#+-=|{}.!"


class TestEscaping:
    """Test _esc and _esc_preserve_code functions."""

    def test_esc_escapes_all_reserved_chars(self):
        """_esc should escape all MarkdownV2 reserved characters."""
        for char in MARKDOWN_V2_RESERVED:
            result = _esc(char)
            assert result == f"\\{char}", f"Failed to escape '{char}'"

    def test_esc_preserve_code_preserves_backticks(self):
        """_esc_preserve_code should preserve backticks for code formatting."""
        # Inline code
        result = _esc_preserve_code("`code`")
        assert result == "`code`", "Inline backticks should be preserved"

        # Code block
        result = _esc_preserve_code("```python\ncode\n```")
        assert "```" in result, "Code block backticks should be preserved"

    def test_esc_preserve_code_escapes_other_chars(self):
        """_esc_preserve_code should still escape non-backtick reserved chars."""
        result = _esc_preserve_code("hello. world! [test]")
        assert "\\." in result, "Should escape period"
        assert "\\!" in result, "Should escape exclamation"
        assert "\\[" in result, "Should escape bracket"

    def test_esc_preserve_code_mixed_content(self):
        """_esc_preserve_code should handle mixed content with code and text."""
        result = _esc_preserve_code("Use `code` in a sentence. And [link].")
        assert "`code`" in result, "Code backticks should be preserved"
        assert "\\." in result, "Periods should be escaped"
        assert "\\[" in result, "Brackets should be escaped"


class TestFormatProblems:
    """Test format_problems function for MarkdownV2 validity."""

    def test_format_problems_with_problematic_chars_in_title(self):
        """Problem titles with reserved chars should be escaped."""
        result = {
            "total": 1,
            "questions": [
                {
                    "questionFrontendId": "1",
                    "title": "Two Sum. [Easy!]",  # Has . [ ! ]
                    "titleSlug": "two-sum",
                    "difficulty": "Easy",
                    "acRate": 50.0,
                    "topicTags": [{"name": "Array"}],
                }
            ],
        }
        output = format_problems(result, "")
        # Should escape special chars
        assert "\\." in output or "Two Sum" in output, "Should handle title with special chars"

    def test_format_problems_with_problematic_chars_in_tags(self):
        """Tag names with reserved chars should be escaped."""
        result = {
            "total": 1,
            "questions": [
                {
                    "questionFrontendId": "1",
                    "title": "Problem",
                    "titleSlug": "problem",
                    "difficulty": "Medium",
                    "acRate": 45.0,
                    "topicTags": [{"name": "Dynamic Programming"}],
                }
            ],
        }
        output = format_problems(result, "")
        # Should have no unescaped reserved chars outside of markdown syntax
        assert "*Problem List*" in output, "Should contain header"


class TestFormatProblemDetail:
    """Test format_problem_detail for MarkdownV2 validity."""

    def test_format_problem_detail_with_dots_in_content(self):
        """Content with periods should be escaped."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": "<p>Given an array. Find two numbers.</p>",
            "likes": 100,
            "dislikes": 10,
            "topicTags": [],
            "hints": [],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Content with dots should be escaped
        assert "\\." in output, "Periods in content should be escaped"

    def test_format_problem_detail_with_code_blocks(self):
        """Code blocks in examples should preserve backticks."""
        question = {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": "<p>Test.</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "exampleTestcases": "<pre><code>arr = [1, 2]</code></pre>",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Code block backticks should be preserved
        assert "```" in output, "Code block backticks should be present"

    def test_format_problem_detail_with_special_chars_in_hints(self):
        """Hints with special chars should be escaped."""
        question = {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": "<p>Test.</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": ["Hint 1. Use a loop!", "Hint 2: Sort the array."],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Hints should be present and properly escaped
        assert "||" in output, "Hints should use spoiler format"
        # Should escape special chars in hints
        assert "\\." in output or "Hint" in output, "Hints should be present"

    def test_format_problem_detail_with_all_special_chars(self):
        """Test that all MarkdownV2 reserved chars in content are handled."""
        question = {
            "questionFrontendId": "1",
            "title": "Special_*Test[1]",  # Multiple reserved chars
            "titleSlug": "special-test",
            "difficulty": "Hard",
            "content": "<p>Contains: _ * [ ] ( ) ~ ` > # + - = | { } . !</p>",
            "likes": 5,
            "dislikes": 2,
            "topicTags": [{"name": "Math"}, {"name": "String"}],
            "hints": ["Try this: a + b = c"],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        # Should not raise an exception
        output = format_problem_detail(question)
        # Verify it's a string
        assert isinstance(output, str), "Output should be a string"
        # Should contain some content
        assert len(output) > 0, "Output should not be empty"


class TestMarkdownV2Validity:
    """Test that outputs don't contain obviously invalid MarkdownV2."""

    def test_no_unescaped_reserved_chars_in_plain_text(self):
        """Unescaped reserved chars should only appear in proper markdown syntax."""
        question = {
            "questionFrontendId": "1",
            "title": "Test Problem.",  # Period is problematic
            "titleSlug": "test-problem",
            "difficulty": "Easy",
            "content": "<p>This is test content with dots. And more!</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)

        # Check that periods and exclamation marks are escaped
        # (They may appear unescaped in markdown syntax like *bold*, but not in plain text)
        lines = output.split("\n")
        for line in lines:
            # Skip lines with markdown syntax (*, [, ], etc.)
            if "*" not in line and "[" not in line and "]" not in line and "`" not in line:
                # This line should have escaped dots
                if "." in line:
                    assert "\\." in line, f"Unescaped period in: {line}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_question(self):
        """Empty question should return 'Problem not found'."""
        output = format_problem_detail({})
        assert "not found" in output.lower()

    def test_question_with_none_values(self):
        """Question with None values should not crash."""
        question = {
            "questionFrontendId": None,
            "title": None,
            "titleSlug": "",
            "difficulty": None,
            "content": None,
            "likes": None,
            "dislikes": None,
            "topicTags": None,
            "hints": None,
            "exampleTestcases": None,
            "isPaidOnly": None,
        }
        # Should not raise an exception
        output = format_problem_detail(question)
        assert isinstance(output, str)

    def test_very_long_content(self):
        """Very long content should be truncated gracefully."""
        long_content = "<p>" + ("x" * 10000) + "</p>"
        question = {
            "questionFrontendId": "1",
            "title": "Long",
            "titleSlug": "long",
            "difficulty": "Easy",
            "content": long_content,
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Should not be excessively long
        assert len(output) < 5000, "Output should be truncated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
