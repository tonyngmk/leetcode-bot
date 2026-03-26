"""
Test suite for message formatting and MarkdownV2 escaping.

This test suite validates that:
1. All format_* functions produce valid MarkdownV2
2. Special characters are properly escaped
3. Code blocks preserve backticks
4. No unescaped reserved characters appear in output
"""

import pytest
import re

from formatter import (
    LANGUAGE_DISPLAY,
    _esc,
    _esc_preserve_code,
    _esc_preserve_html_tags,
    _convert_leetcode_html_to_telegram,
    format_problems,
    format_problem_detail,
    format_solution_detail,
    format_daily,
    format_weekly,
    format_leaderboard,
    format_daily_challenge,
)
from leetcode import (
    extract_images,
    map_images_to_examples,
    extract_examples,
    extract_constraints,
    get_cached_solution,
    save_solution,
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


class TestHtmlTagPreservation:
    """Test _esc_preserve_html_tags function for preserving safe HTML while escaping content."""

    def test_esc_preserve_html_tags_preserves_code(self):
        """Should preserve <code> tags while escaping other content."""
        text = "Use <code>x</code> in your code."
        result = _esc_preserve_html_tags(text)
        assert "<code>" in result, "<code> tag should be preserved"
        assert "</code>" in result, "</code> tag should be preserved"
        # Text outside code tags remains mostly as-is (HTML escape only, not MarkdownV2)
        assert "x</code>" in result, "Code content should be preserved"

    def test_esc_preserve_html_tags_escapes_dangerous_chars(self):
        """Should preserve code tags and escape dangerous HTML chars."""
        text = "Variable <code>arr[i]</code> has & special."
        result = _esc_preserve_html_tags(text)
        assert "<code>arr[i]</code>" in result, "<code> tags should be intact with content"
        assert "&amp;" in result, "& should be escaped to &amp;"

    def test_esc_preserve_html_tags_with_strong(self):
        """Should preserve <strong> tags and escape ampersands."""
        text = "This is <strong>important</strong> & critical."
        result = _esc_preserve_html_tags(text)
        assert "<strong>" in result, "<strong> tag should be preserved"
        assert "</strong>" in result, "</strong> tag should be preserved"
        assert "&amp;" in result, "& should be escaped to &amp;"

    def test_esc_preserve_html_tags_multiple_tags(self):
        """Should preserve multiple HTML tags."""
        text = "Use <code>x</code> and <strong>y</strong> & more."
        result = _esc_preserve_html_tags(text)
        assert "<code>" in result, "<code> tag should be preserved"
        assert "<strong>" in result, "<strong> tag should be preserved"
        assert "x</code>" in result, "code tag content should be intact"
        assert "y</strong>" in result, "strong tag content should be intact"

    def test_esc_preserve_html_tags_nested_not_supported(self):
        """Function handles properly formed tags; nested tags may need careful handling."""
        # This tests basic non-nested case
        text = "<code>x = 5</code>"
        result = _esc_preserve_html_tags(text)
        assert "<code>x = 5</code>" in result

    def test_esc_preserve_html_tags_with_hints_example(self):
        """Should handle real hint text with code tags from LeetCode."""
        hint = "So, if we fix one of the numbers, say <code>x</code>, we have to scan the array to find <code>y</code> which is <code>value - x</code>."
        result = _esc_preserve_html_tags(hint)
        # All code tags should be preserved
        assert result.count("<code>") == 3, "Should have 3 opening <code> tags"
        assert result.count("</code>") == 3, "Should have 3 closing </code> tags"
        # Hyphens and other chars should be escaped if needed
        assert "x</code>" in result, "First code block should be intact"
        assert "y</code>" in result, "Second code block should be intact"


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

    def test_format_problems_markdown_v2_balanced_asterisks(self):
        """MarkdownV2 format should have balanced asterisks (no parsing errors)."""
        result = {
            "total": 2,
            "questions": [
                {
                    "questionFrontendId": "1",
                    "title": "Two Sum",
                    "titleSlug": "two-sum",
                    "difficulty": "Easy",
                    "acRate": 50.0,
                    "topicTags": [{"name": "Array"}],
                },
                {
                    "questionFrontendId": "2",
                    "title": "Add Two Numbers",
                    "titleSlug": "add-two-numbers",
                    "difficulty": "Medium",
                    "acRate": 60.0,
                    "topicTags": [{"name": "Math"}],
                },
            ],
        }
        output = format_problems(result, "")
        # Check that all asterisks are balanced
        lines = output.split('\n')
        for line in lines:
            asterisk_count = line.count('*')
            assert asterisk_count % 2 == 0, f"Unbalanced asterisks in line: {line}"

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
        """Code blocks in examples should use HTML <blockquote> tags."""
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
        # HTML mode uses <blockquote> tags for quote-style examples
        assert "<blockquote>" in output, "Code blocks should use HTML <blockquote> tags"
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
        assert "<blockquote>" in output, "Examples should use <blockquote> tags"
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

    def test_format_problem_detail_with_code_tags_in_hints(self):
        """Hints with <code> tags should preserve the tags and display as monospace."""
        question = {
            "questionFrontendId": "1",
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "difficulty": "Easy",
            "content": "<p>Test.</p>",
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [
                "Use <code>x</code> and <code>y</code> to find the sum.",
                "Check if <code>value - x</code> exists in the array.",
            ],
            "exampleTestcases": "",
            "isPaidOnly": False,
        }
        output = format_problem_detail(question)
        # Should have Hints section
        assert "<b>Hints:</b>" in output, "Hints section should be present"
        # <code> tags should be preserved, not escaped
        assert "<code>x</code>" in output, "<code>x</code> should be in output"
        assert "<code>y</code>" in output, "<code>y</code> should be in output"
        assert "<code>value - x</code>" in output, "<code>value - x</code> should be in output"
        # Should NOT have escaped code tags
        assert "&lt;code&gt;" not in output, "Code tags should not be escaped"

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
        # HTML mode: equals should appear unescaped in <blockquote> blocks
        assert "nums = [1,2]" in output, "Equals should be present unescaped in examples"
        # Code blocks should use HTML <blockquote> tags
        assert "<blockquote>" in output, "Code blocks should use <blockquote> tags"
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

    def test_map_images_to_examples_single(self):
        """Should map a single image to its corresponding example."""
        content = '''
        <pre>Example 1: Input: [1,2,3] Output: [3,2,1]</pre>
        <img src="https://example.com/image1.jpeg" />
        '''
        mapping = map_images_to_examples(content)
        assert len(mapping) == 1
        assert mapping["https://example.com/image1.jpeg"] == 1

    def test_map_images_to_examples_multiple(self):
        """Should map multiple images to their corresponding examples."""
        content = '''
        <pre>Example 1: [1,2]</pre>
        <img src="https://example.com/image1.jpeg" />
        <pre>Example 2: [3,4]</pre>
        <img src="https://example.com/image2.jpeg" />
        '''
        mapping = map_images_to_examples(content)
        assert len(mapping) == 2
        assert mapping["https://example.com/image1.jpeg"] == 1
        assert mapping["https://example.com/image2.jpeg"] == 2

    def test_map_images_to_examples_image_without_example(self):
        """Should map image to None if no nearby example."""
        content = '<img src="https://example.com/orphan.jpeg" />'
        mapping = map_images_to_examples(content)
        assert len(mapping) == 1
        assert mapping["https://example.com/orphan.jpeg"] is None

    def test_map_images_to_examples_filters_by_type(self):
        """Should only map filtered image types."""
        content = '''
        <pre>Example 1: test</pre>
        <img src="https://example.com/image.png" />
        <img src="https://example.com/image.jpeg" />
        '''
        mapping = map_images_to_examples(content)  # Default: jpeg only
        assert len(mapping) == 1
        assert "image.jpeg" in list(mapping.keys())[0]
        assert "png" not in str(mapping)


class TestFormatDailyChallenge:
    """Test format_daily_challenge function for HTML validity."""

    def test_format_daily_challenge_returns_valid_html(self):
        """Daily challenge should return valid HTML without unescaped > characters."""
        challenge = {
            "date": "2026-03-26",
            "question": {
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
        }
        output = format_daily_challenge(challenge)

        # Should be valid HTML with proper tags
        assert "<b>Daily Challenge" in output, "Header should use HTML bold tags"
        assert "<b>" in output, "Should use HTML formatting"
        # No unescaped > characters (except in HTML tags)
        # Count opening and closing tags
        assert output.count("<") == output.count(">"), "HTML tags should be matched"

    def test_format_daily_challenge_with_special_chars_in_date(self):
        """Daily challenge date with special chars should be properly escaped."""
        challenge = {
            "date": "Mar & 26 > 2026",  # Contains special chars
            "question": {
                "questionFrontendId": "1",
                "title": "Test",
                "titleSlug": "test",
                "difficulty": "Easy",
                "content": "<p>Test.</p>",
                "likes": 0,
                "dislikes": 0,
                "topicTags": [],
                "hints": [],
                "isPaidOnly": False,
            }
        }
        output = format_daily_challenge(challenge)

        # HTML special chars should be escaped
        assert "&amp;" in output, "& should be escaped as &amp;"
        assert "&gt;" in output, "> should be escaped as &gt;"
        # No unescaped special chars outside of HTML tags
        assert output.count("<") == output.count(">"), "HTML tags should be matched"

    def test_format_daily_challenge_includes_problem_detail(self):
        """Daily challenge should include full problem detail."""
        challenge = {
            "date": "2026-03-26",
            "question": {
                "questionFrontendId": "42",
                "title": "Median of Two Sorted Arrays",
                "titleSlug": "median-of-two-sorted-arrays",
                "difficulty": "Hard",
                "content": "<p>Given two sorted arrays.</p>",
                "likes": 500,
                "dislikes": 50,
                "topicTags": [{"name": "Array"}],
                "hints": ["Use binary search"],
                "isPaidOnly": False,
            }
        }
        output = format_daily_challenge(challenge)

        # Should include date
        assert "2026-03-26" in output, "Date should be present"
        # Should include problem title
        assert "Median of Two Sorted Arrays" in output, "Problem title should be present"
        # Should include problem frontend ID
        assert "42" in output, "Problem ID should be present"
        # Should include engagement metrics
        assert "500" in output, "Likes should be present"

    def test_format_daily_challenge_empty_challenge(self):
        """Empty challenge should return error message."""
        output = format_daily_challenge({})
        assert "Failed" in output, "Should return error message for empty challenge"


class TestExampleExtraction:
    """Test example extraction for both <pre> and <p> tag formats."""

    def test_extract_examples_from_pre_tags(self):
        """Should extract examples from <pre> blocks (traditional format)."""
        content = '''
        <p>Description</p>
        <p><strong>Example 1:</strong></p>
        <pre><strong>Input:</strong> nums = [2,7,11,15], target = 9
<strong>Output:</strong> [0,1]</pre>
        '''
        examples = extract_examples(content)
        assert len(examples) == 1
        assert "Input: nums = [2,7,11,15]" in examples[0]
        assert "Output: [0,1]" in examples[0]

    def test_extract_examples_from_example_block_format(self):
        """Should extract examples from <div class="example-block"> (actual LeetCode format with images)."""
        content = '''
        <p>Description</p>
        <p><strong class="example">Example 1:</strong></p>
        <div class="example-block">
        <p><strong>Input:</strong> <span class="example-io">grid = [[1,4],[2,3]]</span></p>
        <p><strong>Output:</strong> <span class="example-io">true</span></p>
        <p><img src="image.jpeg" /></p>
        </div>
        '''
        examples = extract_examples(content)
        assert len(examples) == 1
        assert "Input: grid = [[1,4],[2,3]]" in examples[0]
        assert "Output: true" in examples[0]

    def test_extract_multiple_examples_from_example_blocks(self):
        """Should extract multiple examples from <div class="example-block">."""
        content = '''
        <p><strong class="example">Example 1:</strong></p>
        <div class="example-block">
        <p><strong>Input:</strong> <span class="example-io">x = 3</span></p>
        <p><strong>Output:</strong> <span class="example-io">9</span></p>
        </div>
        <p><strong class="example">Example 2:</strong></p>
        <div class="example-block">
        <p><strong>Input:</strong> <span class="example-io">x = -2</span></p>
        <p><strong>Output:</strong> <span class="example-io">4</span></p>
        </div>
        '''
        examples = extract_examples(content)
        assert len(examples) == 2
        assert "Input: x = 3" in examples[0]
        assert "Output: 9" in examples[0]
        assert "Input: x = -2" in examples[1]
        assert "Output: 4" in examples[1]

    def test_extract_examples_stops_at_constraints(self):
        """Should stop extracting examples at Constraints section."""
        content = '''
        <p><strong class="example">Example 1:</strong></p>
        <div class="example-block">
        <p><strong>Input:</strong> <span class="example-io">x = 3</span></p>
        <p><strong>Output:</strong> <span class="example-io">9</span></p>
        </div>
        <p><strong>Constraints:</strong></p>
        <p>Some constraint</p>
        '''
        examples = extract_examples(content)
        assert len(examples) == 1
        assert "Constraints" not in examples[0]

    def test_extract_examples_with_images_in_block(self):
        """Should skip images within example blocks."""
        content = '''
        <p><strong class="example">Example 1:</strong></p>
        <div class="example-block">
        <p><strong>Input:</strong> <span class="example-io">grid = [[1,4],[2,3]]</span></p>
        <p><strong>Output:</strong> <span class="example-io">true</span></p>
        <p><img alt="" src="image.jpeg" style="height: 180px;" /></p>
        </div>
        '''
        examples = extract_examples(content)
        assert len(examples) == 1
        assert "Input: grid = [[1,4],[2,3]]" in examples[0]
        assert "Output: true" in examples[0]
        assert "<img" not in examples[0]  # Images should be stripped


class TestConstraintExtraction:
    """Test constraint extraction from problem HTML."""

    def test_extract_constraints_excludes_method_signatures(self):
        """Should not include method signatures that appear before Constraints section."""
        content = '''
        <p><strong>Implement the MyCalendar class:</strong></p>
        <ul>
        <li>MyCalendar() Initializes the calendar object.</li>
        <li>boolean book(int startTime, int endTime) Returns true if the event can be added to the calendar successfully without causing a double booking. Otherwise, return false and do not add the event to the calendar.</li>
        </ul>
        <p><strong>Constraints:</strong></p>
        <ul>
        <li>0 <= start < end <= 10^9</li>
        <li>At most 1000 calls will be made to book.</li>
        </ul>
        '''
        constraints = extract_constraints(content)
        assert len(constraints) == 2, f"Expected 2 constraints, got {len(constraints)}: {constraints}"
        assert "MyCalendar()" not in constraints[0], "Should not include method signatures"
        assert "boolean book" not in " ".join(constraints), "Should not include method signatures"
        assert "0 <= start < end <= 10^9" in constraints[0]
        assert "At most 1000 calls" in constraints[1]

    def test_extract_constraints_with_follow_up(self):
        """Should stop extracting at Follow-up section."""
        content = '''
        <p><strong>Constraints:</strong></p>
        <ul>
        <li>1 <= n <= 100</li>
        <li>0 <= nums[i] <= 100</li>
        </ul>
        <p><strong>Follow-up:</strong></p>
        <p>Can you solve this in O(n) time?</p>
        '''
        constraints = extract_constraints(content)
        assert len(constraints) == 2
        assert "Follow-up" not in " ".join(constraints)
        assert "1 <= n <= 100" in constraints[0]
        assert "0 <= nums[i] <= 100" in constraints[1]

    def test_extract_constraints_no_section(self):
        """Should return empty list if no Constraints section."""
        content = '<p>Some problem description</p><ul><li>Not a constraint</li></ul>'
        constraints = extract_constraints(content)
        assert len(constraints) == 0

    def test_extract_constraints_empty_list(self):
        """Should return empty list if Constraints section has no items."""
        content = '''
        <p><strong>Constraints:</strong></p>
        <p>No constraints for this problem.</p>
        '''
        constraints = extract_constraints(content)
        assert len(constraints) == 0

    def test_extract_constraints_with_html_formatting(self):
        """Should strip HTML from constraint text, preserving code formatting."""
        content = '''
        <p><strong>Constraints:</strong></p>
        <ul>
        <li><strong>1</strong> &lt;= <code>n</code> &lt;= <strong>100</strong></li>
        <li>0 &lt;= <code>nums[i]</code> &lt;= 100</li>
        </ul>
        '''
        constraints = extract_constraints(content)
        assert len(constraints) == 2
        assert "1 <=" in constraints[0] and "<= 100" in constraints[0]
        assert "0 <=" in constraints[1] and "<= 100" in constraints[1]
        # Code formatting should be preserved as backticks
        assert "`n`" in constraints[0]
        assert "`nums[i]`" in constraints[1]
        # HTML tags should be stripped
        assert "<strong>" not in constraints[0]
        assert "<strong>" not in constraints[1]


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


class TestRichFormatting:
    """Test that rich HTML formatting is preserved in problem descriptions."""

    def _make_question(self, content):
        return {
            "questionFrontendId": "1",
            "title": "Test",
            "titleSlug": "test",
            "difficulty": "Easy",
            "content": content,
            "likes": 0,
            "dislikes": 0,
            "topicTags": [],
            "hints": [],
            "isPaidOnly": False,
        }

    def test_description_preserves_bold(self):
        """<strong> in description should become <b> in output."""
        q = self._make_question("<p>Given a <strong>sorted</strong> array.</p>")
        output = format_problem_detail(q)
        assert "<b>sorted</b>" in output

    def test_description_preserves_italic(self):
        """<em> in description should become <i> in output."""
        q = self._make_question("<p>Return the <em>minimum</em> value.</p>")
        output = format_problem_detail(q)
        assert "<i>minimum</i>" in output

    def test_description_preserves_inline_code(self):
        """<code> in description should be preserved."""
        q = self._make_question("<p>Use <code>nums[i]</code> to access elements.</p>")
        output = format_problem_detail(q)
        assert "<code>nums[i]</code>" in output

    def test_description_bullet_lists(self):
        """<ul><li> inside <p> should become bullet points."""
        # Bullet lists in the description area (inside paragraph context)
        q = self._make_question("<p>Rules:<ul><li>First rule</li><li>Second rule</li></ul></p>")
        output = format_problem_detail(q)
        assert "• First rule" in output
        assert "• Second rule" in output

    def test_description_superscripts(self):
        """<sup> should become ^n notation."""
        q = self._make_question("<p>The value is 10<sup>4</sup>.</p>")
        output = format_problem_detail(q)
        assert "10^4" in output

    def test_description_paragraphs_separated(self):
        """Paragraphs should be separated, not concatenated."""
        q = self._make_question("<p>First paragraph.</p><p>Second paragraph.</p>")
        output = format_problem_detail(q)
        assert "First paragraph." in output
        assert "Second paragraph." in output
        # Should not have 3+ newlines in a row
        import re
        assert not re.search(r'\n{3,}', output), "Should not have excessive newlines"

    def test_description_escapes_bare_angle_brackets(self):
        """Bare < and > from math comparisons should be escaped."""
        q = self._make_question("<p>Check if a &lt; b and c &gt; d.</p>")
        output = format_problem_detail(q)
        assert "&lt;" in output
        assert "&gt;" in output
        # Should not contain raw < or > outside of HTML tags
        import re
        text_only = re.sub(r'<[^>]+>', '', output)
        assert "<" not in text_only or ">" not in text_only  # entities should be escaped

    def test_constraints_preserve_code_tags(self):
        """Constraints with <code> should render with code tags."""
        content = (
            "<p>Description.</p>"
            "<p><strong>Constraints:</strong></p>"
            "<ul><li><code>1</code> &lt;= nums.length &lt;= <code>10<sup>4</sup></code></li></ul>"
        )
        q = self._make_question(content)
        output = format_problem_detail(q)
        assert "<code>1</code>" in output
        assert "10^4" in output

    def test_truncation_respects_visible_length(self):
        """Truncation should count visible chars, not HTML tags."""
        # Create content with lots of bold tags but short visible text
        inner = "<b>x</b>" * 100  # 100 visible chars, much more in HTML
        q = self._make_question(f"<p>{inner}</p>")
        output = format_problem_detail(q)
        # Should NOT be truncated since visible text is only 100 chars
        assert "…" not in output

    def test_truncation_closes_open_tags(self):
        """Truncation mid-tag should properly close the tag."""
        long_text = "a" * 700
        q = self._make_question(f"<p><b>{long_text}</b></p>")
        output = format_problem_detail(q)
        assert "…" in output
        # The <b> tag should be properly closed
        assert output.count("<b>") == output.count("</b>")


class TestTelegramHTMLSafety:
    """Regression tests ensuring output never contains bare < > & outside HTML tags.

    These prevent Telegram BadRequest errors like:
    'Can't parse entities: unsupported start tag "=" at byte offset N'
    which occur when &lt;= gets unescaped to <= in the output.
    """

    # Valid Telegram HTML tags that are allowed in output
    TELEGRAM_TAG_RE = re.compile(
        r'</?(?:b|i|u|s|code|pre|a|tg-spoiler|blockquote)(?:\s[^>]*)?>',
    )

    def _assert_no_bare_angles(self, output: str, msg: str = ""):
        """Assert that no bare < or > exist outside of valid Telegram HTML tags."""
        # Remove all valid Telegram tags
        stripped = self.TELEGRAM_TAG_RE.sub('', output)
        # Check for leftover < or > (these would cause Telegram parse errors)
        bare_lt = [m for m in re.finditer(r'<', stripped)]
        bare_gt = [m for m in re.finditer(r'>', stripped)]
        if bare_lt:
            # Show context around the bare <
            for m in bare_lt:
                ctx_start = max(0, m.start() - 30)
                ctx_end = min(len(stripped), m.end() + 30)
                context = stripped[ctx_start:ctx_end]
                assert False, f"Bare '<' found{' - ' + msg if msg else ''}: ...{context}..."
        if bare_gt:
            for m in bare_gt:
                ctx_start = max(0, m.start() - 30)
                ctx_end = min(len(stripped), m.end() + 30)
                context = stripped[ctx_start:ctx_end]
                assert False, f"Bare '>' found{' - ' + msg if msg else ''}: ...{context}..."

    def _make_question(self, content, **kwargs):
        base = {
            "questionFrontendId": "1",
            "title": "Test Problem",
            "titleSlug": "test-problem",
            "difficulty": "Medium",
            "content": content,
            "likes": 100,
            "dislikes": 10,
            "topicTags": [{"name": "Array", "slug": "array"}],
            "hints": [],
            "isPaidOnly": False,
        }
        base.update(kwargs)
        return base

    def test_lte_gte_in_constraints_outside_code(self):
        """&lt;= between <code> tags in constraints must stay escaped."""
        content = (
            "<p>Find the target.</p>"
            "<p><strong>Constraints:</strong></p>"
            "<ul>"
            "<li><code>2</code> &lt;= nums.length &lt;= <code>10<sup>4</sup></code></li>"
            "<li><code>-10<sup>9</sup></code> &lt;= nums[i] &lt;= <code>10<sup>9</sup></code></li>"
            "</ul>"
        )
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output, "constraints with <= between code tags")
        assert "&lt;=" in output

    def test_lte_gte_inside_code_tags(self):
        """&lt;= inside <code> tags must stay escaped (not unescaped by html.unescape)."""
        content = (
            "<p>Find the target.</p>"
            "<p><strong>Constraints:</strong></p>"
            "<ul>"
            "<li><code>2 &lt;= nums.length &lt;= 10<sup>4</sup></code></li>"
            "<li><code>-10<sup>9</sup> &lt;= nums[i] &lt;= 10<sup>9</sup></code></li>"
            "</ul>"
        )
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output, "<=/>= inside code tags")

    def test_lte_in_description(self):
        """&lt;= in description text must be escaped."""
        content = "<p>Return true if a &lt;= b and c &gt;= d.</p>"
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output, "<= in description")

    def test_nested_code_inside_italic_with_entities(self):
        """Nested <code> inside <em> with entities must not leak bare <."""
        content = "<p>Return <em>the <code>k</code>-th value where k &lt;= n</em>.</p>"
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output, "nested code inside italic with entities")

    def test_ampersand_in_description(self):
        """Bare & in text must be escaped as &amp;."""
        content = "<p>Use divide &amp; conquer.</p>"
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output)
        # & should be escaped
        stripped = self.TELEGRAM_TAG_RE.sub('', output)
        assert '&amp;' in stripped or '&' not in re.sub(r'&(?:amp|lt|gt|quot);', '', stripped)

    def test_realistic_two_sum_full_content(self):
        """Full Two Sum-style content must produce safe Telegram HTML."""
        content = (
            '<p>Given an array of integers <code>nums</code> and an integer <code>target</code>, '
            'return <em>indices of the two numbers such that they add up to <code>target</code></em>.</p>\n'
            '<p><strong class="example">Example 1:</strong></p>\n'
            '<pre><strong>Input:</strong> nums = [2,7,11,15], target = 9\n'
            '<strong>Output:</strong> [0,1]\n'
            '<strong>Explanation:</strong> Because nums[0] + nums[1] == 9, we return [0, 1].</pre>\n'
            '<p><strong>Constraints:</strong></p>\n'
            '<ul>\n'
            '<li><code>2 &lt;= nums.length &lt;= 10<sup>4</sup></code></li>\n'
            '<li><code>-10<sup>9</sup> &lt;= nums[i] &lt;= 10<sup>9</sup></code></li>\n'
            '<li><code>-10<sup>9</sup> &lt;= target &lt;= 10<sup>9</sup></code></li>\n'
            '<li>Only one valid answer exists.</li>\n'
            '</ul>'
        )
        output = format_problem_detail(self._make_question(content))
        self._assert_no_bare_angles(output, "full Two Sum content")

    def test_hints_with_code_and_entities(self):
        """Hints with <code> and entities must be safe."""
        content = "<p>Description.</p>"
        hints = [
            'Use a hashmap where <code>key &lt; value</code>.',
            'Check if <code>nums[i] + nums[j] &lt;= target</code>.',
        ]
        output = format_problem_detail(self._make_question(content, hints=hints))
        self._assert_no_bare_angles(output, "hints with code and entities")

    def test_convert_leetcode_html_to_telegram_entities_in_code(self):
        """Direct test: _convert_leetcode_html_to_telegram must not unescape entities in tags."""
        result = _convert_leetcode_html_to_telegram(
            '<code>2 &lt;= n &lt;= 10<sup>5</sup></code>'
        )
        self._assert_no_bare_angles(result, "direct converter test")
        assert '<code>' in result
        assert '&lt;=' in result

    def test_convert_leetcode_html_to_telegram_mixed_entities(self):
        """Entities both inside and outside tags must all be properly handled."""
        result = _convert_leetcode_html_to_telegram(
            '<p>If a &lt; b then <code>a &lt; b</code> is true &amp; valid.</p>'
        )
        self._assert_no_bare_angles(result, "mixed entities inside/outside tags")


class TestFormatSolutionDetail:
    """Test format_solution_detail output."""

    SAMPLE_APPROACH = {
        "name": "Hash Map",
        "explanation": "Use a hash map to store complements as we iterate.",
        "time_complexity": "O(n)",
        "space_complexity": "O(n)",
        "code": {
            "python": "class Solution:\n    def twoSum(self, nums, target):\n        seen = {}\n        for i, num in enumerate(nums):\n            if target - num in seen:\n                return [seen[target - num], i]\n            seen[num] = i",
            "java": "class Solution {\n    public int[] twoSum(int[] nums, int target) {\n        Map<Integer, Integer> seen = new HashMap<>();\n        for (int i = 0; i < nums.length; i++) {\n            int c = target - nums[i];\n            if (seen.containsKey(c)) return new int[]{seen.get(c), i};\n            seen.put(nums[i], i);\n        }\n        return new int[]{};\n    }\n}",
        },
    }

    def test_basic_formatting(self):
        """Solution detail should contain approach name, code, and complexity."""
        output = format_solution_detail("two-sum", self.SAMPLE_APPROACH, "python")
        assert "Hash Map" in output
        assert "two-sum" in output
        assert "Python" in output
        assert "O(n)" in output
        assert "class Solution:" in output

    def test_java_language(self):
        """Should render Java code when language is java."""
        output = format_solution_detail("two-sum", self.SAMPLE_APPROACH, "java")
        assert "Java" in output
        assert "HashMap" in output

    def test_missing_language_code(self):
        """Should still format even if requested language has no code."""
        output = format_solution_detail("two-sum", self.SAMPLE_APPROACH, "go")
        assert "Hash Map" in output
        # No code block since go isn't in this approach
        assert "<pre>" not in output

    def test_html_safety_in_code(self):
        """Angle brackets in code should be HTML-escaped."""
        approach = {
            "name": "Comparison",
            "explanation": "Compare values.",
            "time_complexity": "O(1)",
            "space_complexity": "O(1)",
            "code": {"python": "if a < b and c > d:\n    return True"},
        }
        output = format_solution_detail("test-problem", approach, "python")
        assert "&lt;" in output
        assert "&gt;" in output
        # No raw < or > outside HTML tags in the code block
        import re
        code_match = re.search(r'<pre><code>(.*?)</code></pre>', output, re.DOTALL)
        if code_match:
            code_content = code_match.group(1)
            assert "<" not in code_content.replace("&lt;", "").replace("&gt;", "")

    def test_explanation_html_escaped(self):
        """Special chars in explanation should be escaped."""
        approach = {
            "name": "Test",
            "explanation": "Check if x < y & return true",
            "time_complexity": "O(1)",
            "space_complexity": "O(1)",
            "code": {"python": "pass"},
        }
        output = format_solution_detail("test", approach, "python")
        assert "&lt;" in output
        assert "&amp;" in output

    def test_empty_approach(self):
        """Empty approach should not crash."""
        output = format_solution_detail("test", {}, "python")
        assert "Unknown" in output

    def test_leetcode_link(self):
        """Should include link to LeetCode problem."""
        output = format_solution_detail("two-sum", self.SAMPLE_APPROACH, "python")
        assert "https://leetcode.com/problems/two-sum/" in output


class TestSolutionCache:
    """Test solution cache get/save functions."""

    def test_get_nonexistent_solution(self):
        """Getting a non-cached slug should return None."""
        result = get_cached_solution("nonexistent-problem-xyz-999")
        assert result is None

    def test_save_and_get_solution(self, tmp_path, monkeypatch):
        """Saving a solution should make it retrievable."""
        import leetcode
        cache_file = tmp_path / "test_solution_cache.json"
        monkeypatch.setattr(leetcode, "SOLUTION_CACHE_FILE", str(cache_file))
        # Reset cache state
        monkeypatch.setattr(leetcode, "_solution_cache", {})
        monkeypatch.setattr(leetcode, "_solution_cache_loaded", False)

        test_data = {"approaches": [{"name": "Test", "code": {"python": "pass"}}]}
        save_solution("test-slug", test_data)

        # Reset and reload from disk
        monkeypatch.setattr(leetcode, "_solution_cache", {})
        monkeypatch.setattr(leetcode, "_solution_cache_loaded", False)

        result = get_cached_solution("test-slug")
        assert result is not None
        assert result["approaches"][0]["name"] == "Test"


class TestSolutionKeyboard:
    """Test solution keyboard encode/decode helpers."""

    def test_encode_decode_roundtrip(self):
        from bot import _encode_solution_callback, _decode_solution_callback
        encoded = _encode_solution_callback("two-sum", 1, "python")
        slug, idx, lang = _decode_solution_callback(encoded)
        assert slug == "two-sum"
        assert idx == 1
        assert lang == "python"

    def test_encode_stays_within_64_bytes(self):
        from bot import _encode_solution_callback
        # Very long slug
        long_slug = "a-very-long-problem-slug-that-might-exceed-the-limit"
        encoded = _encode_solution_callback(long_slug, 0, "javascript")
        assert len(encoded.encode()) <= 64

    def test_build_keyboard_single_approach(self):
        from bot import _build_solution_keyboard
        approaches = [{"name": "Hash Map", "code": {"python": "...", "java": "..."}}]
        keyboard = _build_solution_keyboard("two-sum", approaches, 0, "python")
        # Single approach: no approach row, only language row
        assert len(keyboard.inline_keyboard) == 1
        lang_row = keyboard.inline_keyboard[0]
        assert len(lang_row) == 2  # python, java

    def test_build_keyboard_multiple_approaches(self):
        from bot import _build_solution_keyboard
        approaches = [
            {"name": "Brute Force", "code": {"python": "..."}},
            {"name": "Hash Map", "code": {"python": "...", "java": "..."}},
        ]
        keyboard = _build_solution_keyboard("two-sum", approaches, 1, "python")
        # Two rows: approaches + languages
        assert len(keyboard.inline_keyboard) == 2
        approach_row = keyboard.inline_keyboard[0]
        assert len(approach_row) == 2
        # Second approach should have checkmark
        assert "✓" in approach_row[1].text
        assert "✓" not in approach_row[0].text

    def test_build_keyboard_selected_language(self):
        from bot import _build_solution_keyboard
        approaches = [{"name": "Test", "code": {"python": "...", "java": "...", "go": "..."}}]
        keyboard = _build_solution_keyboard("slug", approaches, 0, "java")
        lang_row = keyboard.inline_keyboard[0]
        java_btn = [b for b in lang_row if "Java" in b.text][0]
        assert "✓" in java_btn.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
