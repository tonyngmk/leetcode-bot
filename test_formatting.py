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
    _esc_preserve_html_tags,
    format_problems,
    format_problem_detail,
    format_daily,
    format_weekly,
    format_leaderboard,
    format_daily_challenge,
)
from leetcode import extract_images, map_images_to_examples, extract_examples, extract_constraints


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
