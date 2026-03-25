# Testing Guide

This document describes the automated test suite for the LeetCode bot.

## Overview

The test suite validates:
- MarkdownV2 escaping for Telegram message formatting
- Proper handling of special characters in problem titles, content, tags, hints
- Code block preservation (backticks not escaped)
- Edge cases (empty inputs, None values, very long content)

## Running Tests

### Install dependencies
```bash
pip3 install pytest
```

### Run all tests
```bash
python3 -m pytest test_formatting.py -v
```

### Run specific test class
```bash
python3 -m pytest test_formatting.py::TestEscaping -v
python3 -m pytest test_formatting.py::TestFormatProblemDetail -v
```

### Run specific test
```bash
python3 -m pytest test_formatting.py::TestFormatProblemDetail::test_format_problem_detail_with_dots_in_content -v
```

## Pre-commit Hook

A pre-commit hook automatically runs tests before allowing commits. This prevents MarkdownV2 escaping bugs from being committed.

### Enable hook
The hook is already in `.git/hooks/pre-commit`. To enable it:
```bash
chmod +x .git/hooks/pre-commit
```

### Disable hook (temporary)
To commit without running tests (not recommended):
```bash
git commit --no-verify
```

## Test Coverage

### TestEscaping (4 tests)
- Validates `_esc()` escapes all MarkdownV2 reserved characters
- Validates `_esc_preserve_code()` preserves backticks while escaping other chars
- Tests mixed content (code + regular text)

### TestFormatProblems (2 tests)
- Tests `/problems` command output with special chars in titles
- Tests tag escaping

### TestFormatProblemDetail (5 tests)
- Tests content with periods (common in problem descriptions)
- Tests code blocks (backticks should be preserved)
- Tests special characters in hints
- Comprehensive test with ALL reserved characters

### TestMarkdownV2Validity (1 test)
- Validates output doesn't contain unescaped reserved chars in plain text

### TestEdgeCases (3 tests)
- Empty question object
- None values for all fields
- Very long content (truncation)

## Key Fixes

### Issue: Unescaped special characters in problem content
**Root cause**: `_strip_html()` removes HTML but doesn't escape special chars
**Fix**: Use `_esc_preserve_code()` to escape content while preserving code backticks

### Issue: `_esc()` crashes on None values
**Root cause**: Function doesn't validate input
**Fix**: Added `text = text or ""` to handle None gracefully

### Issue: Backticks escaped in code blocks
**Root cause**: `_esc()` escapes ALL reserved chars including backticks
**Fix**: Created `_esc_preserve_code()` that replaces backticks temporarily before escaping

### Issue: Invalid escape sequences in format strings
**Root cause**: Using `\+` instead of `\\+` in f-strings
**Fix**: Changed all `_\+` to `_\\+` for proper escaping

## Future Improvements

1. Add tests for other format_* functions (format_daily, format_weekly, format_leaderboard)
2. Add integration tests that simulate actual Telegram API calls
3. Create additional fixtures for common test cases
4. Add performance benchmarks for large data sets
5. Integrate with CI/CD pipeline (GitHub Actions)

## Debugging Test Failures

If a test fails:

1. Run the specific failing test with `-v` for verbose output:
   ```bash
   python3 -m pytest test_formatting.py::TestFormatProblemDetail::test_name -v
   ```

2. Add print statements or use pytest's `--pdb` flag:
   ```bash
   python3 -m pytest test_formatting.py::test_name -v --pdb
   ```

3. Check the actual vs expected output to identify what characters are missing escaping

4. Update the formatter function to fix the issue

5. Add a new test case to cover the bug (prevent regression)

## Contributing

When adding new formatting functions:

1. Add test cases for:
   - All MarkdownV2 reserved characters
   - Code blocks / inline code
   - None/empty values
   - Very long content

2. Run tests before committing:
   ```bash
   python3 -m pytest test_formatting.py -v
   ```

3. Don't use `--no-verify` to skip pre-commit checks
