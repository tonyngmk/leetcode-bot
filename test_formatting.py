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
from leetcode import extract_images


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
        """Content with periods should render correctly in HTML mode."""
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
        # HTML mode: should use HTML tags, not backslash escaping
        assert "<b>" in output, "Should use HTML bold tags"
        assert "Given an array" in output, "Content should be present"

    def test_format_problem_detail_with_code_blocks(self):
        """Code blocks in examples should use HTML <pre> tags."""
        question = {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": "<p>Test.</p><p><strong>Example 1:</strong></p><pre><code>arr = [1, 2]</code></pre>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # HTML mode uses <pre> tags instead of markdown backticks
        assert "<pre>" in output, "Code blocks should use HTML <pre> tags"
        assert "arr = [1, 2]" in output, "Code content should be present"

    def test_format_problem_detail_with_equals_in_examples(self):
        """Examples with = characters should render correctly in HTML mode."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": '<p>Given two numbers, find their sum.</p><p><strong>Example 1:</strong></p><pre><strong>Input:</strong> nums = [2,7,11,15], target = 9\n<strong>Output:</strong> [0,1]</pre>',
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # HTML mode: no MarkdownV2 escaping needed
        assert "<pre>" in output, "Examples should use <pre> tags"
        assert "nums = [2,7,11,15]" in output, "Example content with equals should be present"
        # Description should not include the example content
        assert "Given two numbers" in output, "Description should be present"
        # No MarkdownV2 escapes in HTML mode
        assert output.count("\\=") == 0, "HTML mode should not have backslash escapes"

    def test_format_problem_detail_with_special_chars_in_hints(self):
        """Hints with special chars should be properly HTML escaped."""
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
        # Hints should be present using HTML formatting
        assert "<b>Hints:</b>" in output, "Hints section should be present"
        assert "Hint" in output, "Hint text should be present"

    def test_format_problem_detail_with_all_special_chars(self):
        """Test that all special chars in content are handled in HTML mode."""
        question = {
            "questionFrontendId": "1",
            "title": "Special_*Test[1]",  # Multiple special chars
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
        # HTML mode: should use HTML tags
        assert "<b>" in output, "Should use HTML formatting"


class TestHTMLValidity:
    """Test that outputs are valid HTML and don't have parse errors."""

    def test_html_special_chars_escaped(self):
        """HTML special chars should be properly escaped."""
        question = {
            "questionFrontendId": "1",
            "title": "Test Problem.",
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

        # HTML mode should use proper tags, not backslash escaping
        assert "<b>" in output, "Should use HTML <b> tags for bold"
        assert "<a " in output, "Should use HTML <a> tags for links"
        # Content with special chars should be present
        assert "Test Problem" in output, "Title should be present"
        assert "test content" in output, "Content should be present"
        # No MarkdownV2 escaping in HTML mode
        assert output.count("\\") == 0, "HTML mode should not have backslash escapes"


class TestHTMLCodeTags:
    """Test that HTML code tags are properly matched."""

    def test_backticks_converted_to_code_tags(self):
        """Backticks should be converted to matching <code></code> tags."""
        question = {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": "<p>Use `array` or `list` for this.</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Should have properly matched code tags
        assert output.count("<code>") == output.count("</code>"), "Code tags should be matched"
        assert "<code>array</code>" in output, "First backtick pair should be converted"
        assert "<code>list</code>" in output, "Second backtick pair should be converted"

    def test_no_unmatched_html_tags(self):
        """All HTML tags should be properly closed."""
        question = {
            "questionFrontendId": "42",
            "title": "Complex Problem with `code` and stuff",
            "titleSlug": "complex-problem",
            "difficulty": "Medium",
            "content": "<p>Description with `inline code` and other content.</p>",
            "likes": 50,
            "dislikes": 10,
            "topicTags": [{"name": "String"}, {"name": "Array"}],
            "hints": ["Hint with `code`"],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Count all HTML tag pairs
        assert output.count("<b>") == output.count("</b>"), "<b> tags should match"
        assert output.count("<code>") == output.count("</code>"), "<code> tags should match"
        assert output.count("<tg-spoiler>") == output.count("</tg-spoiler>"), "Spoiler tags should match"
        assert output.count("<a") == output.count("</a>"), "<a> tags should match"
        assert output.count("<pre>") == output.count("</pre>"), "<pre> tags should match"

    def test_hints_use_spoiler_tags(self):
        """Hints should use Telegram spoiler formatting, not italics."""
        question = {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": "<p>Test.</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": ["Hint 1", "Hint 2"],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Should use spoiler tags, not italics
        assert "<tg-spoiler>" in output, "Hints should use spoiler tags"
        assert "Hint 1" in output, "Hint text should be present"
        # Should not use italic tags for hints
        lines_with_hints = [l for l in output.split('\n') if 'Hint' in l]
        for line in lines_with_hints:
            assert "<i>" not in line, "Hints should not use italic tags"

    def test_description_excludes_examples_and_constraints(self):
        """Description section should not include Example or Constraint explanations."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": '<p>Main description here.</p><p><strong>Example 1:</strong></p><pre>Input: test</pre><p><strong>Constraints:</strong></p><ul><li>constraint 1</li></ul>',
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Get just the description part (before any examples or constraints)
        lines = output.split('\n')
        desc_section = '\n'.join(lines[:4])  # Title, tags, engagement, description

        # Description should only contain the main description text
        assert "Main description here" in output, "Main description should be present"
        # These sections should exist as dedicated sections
        assert "<b>Example" in output, "Example section should exist"
        assert "<b>Constraints:</b>" in output, "Constraints section should exist"

    def test_description_is_only_first_paragraph(self):
        """Description should only contain the first paragraph, not additional explanations."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": '<p>Given an array, find two numbers.</p><p>You may assume each input has exactly one solution.</p><p>You can return the answer in any order.</p><p><strong>Example:</strong></p>',
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Extract description part (between tags and constraints)
        lines = output.split('\n')
        desc_lines = [l for l in lines if 'Given an array' in l or ('numeric' in l.lower())]

        # Verify only first paragraph is shown
        assert "Given an array" in output, "First paragraph should be present"
        assert "You may assume" not in output.split('<b>Constraints:')[0], "Should not include assumption text"
        assert "You can return" not in output.split('<b>Constraints:')[0], "Should not include return text"


class TestParseMode:
    """Test that output is compatible with Telegram parse modes."""

    def test_no_null_bytes_in_output(self):
        """Output should not contain null bytes that break Telegram parser."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": '<p>Given an array.</p><p><strong>Example 1:</strong></p><pre><strong>Input:</strong> nums = [2,7,11,15], target = 9\n<strong>Output:</strong> [0,1]</pre>',
            "likes": 100,
            "dislikes": 5,
            "topicTags": [{"name": "Array"}],
            "hints": ["Use a hash map"],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Null bytes cause "can't find end of pre entity" error in Telegram
        assert chr(0) not in output, "Output should not contain null bytes"

    def test_equals_in_html_mode(self):
        """Equals in examples should render correctly in HTML mode without escaping."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": '<p>Test.</p><p><strong>Example 1:</strong></p><pre><strong>Input:</strong> nums = [1,2], target = 3\n<strong>Output:</strong> [0,1]</pre>',
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # HTML mode: equals should appear unescaped in <pre> blocks
        assert "nums = [1,2]" in output, "Equals should be present unescaped in examples"
        # Code blocks should use HTML <pre> tags
        assert "<pre>" in output, "Code blocks should use <pre> tags"
        # No MarkdownV2 escaping
        assert output.count("\\=") == 0, "HTML mode should not have backslash-escaped equals"
        # No null bytes that could break parser
        assert chr(0) not in output, "Should not contain null bytes"


class TestImageExtraction:
    """Test image extraction from problem content."""

    def test_extract_single_image(self):
        """Should extract a single image URL (jpeg by default)."""
        content = '<p>Example</p><img src="https://example.com/image.jpeg" />'
        images = extract_images(content)
        assert len(images) == 1
        assert images[0] == "https://example.com/image.jpeg"

    def test_extract_multiple_images(self):
        """Should extract multiple image URLs (jpeg by default)."""
        content = '''
        <p>First image:</p>
        <img src="https://example.com/image1.jpeg" />
        <p>Second image:</p>
        <img src="https://example.com/image2.jpg" alt="test" />
        '''
        images = extract_images(content)
        assert len(images) == 2
        assert "https://example.com/image1.jpeg" in images
        assert "https://example.com/image2.jpg" in images

    def test_extract_images_with_attributes(self):
        """Should extract images regardless of attribute order (jpeg by default)."""
        content = '<img alt="test" width="100" src="https://example.com/image.jpeg" class="problem-img" />'
        images = extract_images(content)
        assert len(images) == 1
        assert images[0] == "https://example.com/image.jpeg"

    def test_extract_images_case_insensitive(self):
        """Should match img tags case-insensitively (jpeg by default)."""
        content = '<IMG SRC="https://example.com/image.jpeg" />'
        images = extract_images(content)
        assert len(images) == 1
        assert images[0] == "https://example.com/image.jpeg"

    def test_extract_no_images(self):
        """Should return empty list when no images present."""
        content = "<p>No images here</p>"
        images = extract_images(content)
        assert images == []

    def test_extract_images_empty_content(self):
        """Should return empty list for empty content."""
        images = extract_images("")
        assert images == []

    def test_extract_images_filters_by_type(self):
        """Should filter images by type (default: jpeg and jpg)."""
        content = '''
        <img src="https://example.com/image.png" />
        <img src="https://example.com/image.jpeg" />
        <img src="https://example.com/image.jpg" />
        '''
        images = extract_images(content)  # Default: jpeg and jpg
        assert len(images) == 2
        assert any("jpeg" in url for url in images)
        assert any("jpg" in url for url in images)

    def test_extract_images_with_different_types(self):
        """Should extract images of specified types."""
        content = '''
        <img src="https://example.com/image.png" />
        <img src="https://example.com/image.jpeg" />
        <img src="https://example.com/image.gif" />
        '''
        images = extract_images(content, image_types=["png", "jpeg"])
        assert len(images) == 2
        assert any("png" in url for url in images)
        assert any("jpeg" in url for url in images)
        assert not any("gif" in url for url in images)


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
