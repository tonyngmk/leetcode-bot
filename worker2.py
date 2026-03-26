#!/usr/bin/env python3
"""Worker 2: generate solutions for a batch of LeetCode problem slugs."""

import asyncio
import json
import re
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from leetcode import fetch_problem, save_solution


API_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192

PROMPT_TEMPLATE = """You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {title} ({slug})
Difficulty: {difficulty}
Description: {description}
Constraints: {constraints}

Output format (valid JSON only, no markdown):
{{
  "approaches": [
    {{
      "name": "Short approach name (e.g. Brute Force, Two Pointers, Hash Map)",
      "explanation": "Clear explanation of the approach in 2-4 sentences. Describe the key insight, how the algorithm works, and why it achieves its complexity.",
      "time_complexity": "O(...)",
      "space_complexity": "O(...)",
      "code": {{
        "python": "class Solution:\\n    def methodName(self, ...) -> ...:\\n        ...",
        "java": "class Solution {{\\n    public ... methodName(...) {{\\n        ...\\n    }}\\n}}",
        "cpp": "class Solution {{\\npublic:\\n    ... methodName(...) {{\\n        ...\\n    }}\\n}};",
        "javascript": "var methodName = function(...) {{\\n    ...\\n}};",
        "go": "func methodName(...) ... {{\\n    ...\\n}}"
      }}
    }}
  ]
}}

Rules:
1. Include 2-3 approaches, from brute force to optimal
2. Code must be complete, correct, and directly submittable on LeetCode
3. Use the exact method signature LeetCode expects
4. No import statements unless strictly necessary
5. No markdown formatting in any field — plain text for explanation, raw code for code
6. Escape newlines as \\n and quotes as \\" in the JSON string values
7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go"""


def get_api_key() -> str:
    result = subprocess.run(
        ["bash", os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def strip_html(text: str) -> str:
    """Basic HTML stripping for description text."""
    if not text:
        return ""
    import html
    text = re.sub(r'<sup>(.*?)</sup>', r'^\1', text, flags=re.DOTALL)
    text = re.sub(r'<pre><code>(.*?)</code></pre>', r'```\1```', text, flags=re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>', r'`\1`', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text).strip()
    return text


def extract_constraints(content: str) -> str:
    """Extract constraint text from problem content."""
    if not content:
        return "No constraints provided."
    pattern = r'<p><strong[^>]*>Constraints'
    match = re.search(pattern, content, re.IGNORECASE)
    if not match:
        return "No constraints provided."
    start = match.start()
    follow_up = re.search(r'<p><strong[^>]*>(Follow[- ]?up|Notes?:)', content[start:], re.IGNORECASE)
    end = start + follow_up.start() if follow_up else len(content)
    section = content[start:end]
    items = re.findall(r'<li>(.*?)</li>', section, re.DOTALL)
    if items:
        cleaned = [strip_html(item) for item in items]
        return "\n".join(f"- {c}" for c in cleaned if c)
    return strip_html(section)


def extract_description(content: str) -> str:
    """Extract description paragraphs."""
    if not content:
        return ""
    section_pattern = r'<p><strong[^>]*>(Constraints|Example|Assumptions|Follow[- ]?up|Note:)'
    section_match = re.search(section_pattern, content, re.IGNORECASE)
    end = len(content) if not section_match else section_match.start()
    section = content[:end]
    paragraphs = re.findall(r'<p>(.*?)</p>', section, re.DOTALL)
    lines = []
    skip_patterns = [
        r'you\s+(may\s+assume|can\s+return)',
        r'note\s+that',
        r'you\s+can\s+modify',
    ]
    for para in paragraphs:
        para_lower = para.lower()
        if any(re.search(p, para_lower) for p in skip_patterns):
            break
        stripped = strip_html(para)
        if stripped:
            lines.append(stripped)
    return "\n\n".join(lines)


def validate_solution(data: dict) -> bool:
    """Validate that solution has all required languages in all approaches."""
    if "approaches" not in data:
        return False
    required_langs = {"python", "java", "cpp", "javascript", "go"}
    for approach in data["approaches"]:
        if "code" not in approach:
            return False
        if not required_langs.issubset(approach["code"].keys()):
            missing = required_langs - approach["code"].keys()
            print(f"  Missing languages: {missing}")
            return False
        for lang in required_langs:
            if not approach["code"].get(lang):
                print(f"  Missing code for language: {lang}")
                return False
    return True


def extract_json(text: str) -> dict:
    """Extract JSON from response text, stripping markdown fences."""
    text = text.strip()
    # Remove markdown fences
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    # Try to find JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(text)


async def generate_solution(slug: str, api_key: str) -> tuple[str, dict | None]:
    """Fetch problem and generate solution via LLM."""
    problem = await fetch_problem(slug)
    if problem is None:
        return slug, None

    title = problem.get("title", slug)
    difficulty = problem.get("difficulty", "Unknown")
    content = problem.get("content", "")
    description = extract_description(content)
    constraints = extract_constraints(content)

    prompt = PROMPT_TEMPLATE.format(
        title=title,
        slug=slug,
        difficulty=difficulty,
        description=description,
        constraints=constraints,
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            # The API returns {"content": [{"text": "...", "type": "text"}]}
            content = result.get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "")
            else:
                text = result.get("result", {}).get("text", result.get("text", ""))
            if not text:
                print(f"  No text in response for {slug}, full response: {str(result)[:200]}")
                return slug, None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print(f"  Rate limited, backing off for {slug}")
            await asyncio.sleep(10)
            return slug, None
        print(f"  HTTP error for {slug}: {e}")
        return slug, None
    except Exception as e:
        print(f"  API error for {slug}: {e}")
        return slug, None

    try:
        data = extract_json(text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error for {slug}: {e}")
        # Print first 200 chars of response for debugging
        print(f"  Response preview: {text[:200]}")
        return slug, None

    if not validate_solution(data):
        print(f"  Validation failed for {slug}")
        return slug, None

    return slug, data


def update_progress(slugs: list[str], succeeded: list[str], failed: list[str]) -> None:
    """Update solution_gen_progress.json atomically."""
    progress_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
    with open(progress_file) as f:
        progress = json.load(f)

    completed = progress.get("completed_slugs", [])
    failed_dict = progress.get("failed_slugs", {})

    for s in succeeded:
        if s not in completed:
            completed.append(s)
    for s in failed:
        if s not in failed_dict:
            failed_dict[s] = "unknown error"

    progress["completed_slugs"] = completed
    progress["failed_slugs"] = failed_dict

    tmp_file = progress_file + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(progress, f)
    os.replace(tmp_file, progress_file)


async def main():
    slugs = [
        "container-with-most-water",
        "integer-to-roman",
        "roman-to-integer",
        "longest-common-prefix",
        "3sum",
    ]

    api_key = get_api_key()
    if not api_key:
        print("Error: could not obtain API key")
        sys.exit(1)

    succeeded = []
    failed = []

    for slug in slugs:
        print(f"Processing: {slug}")
        result_slug, data = await generate_solution(slug, api_key)
        if data is not None:
            save_solution(result_slug, data)
            succeeded.append(result_slug)
            print(f"  SUCCESS: saved solution for {result_slug}")
        else:
            failed.append(result_slug)
            print(f"  FAILED: {result_slug}")

    update_progress(slugs, succeeded, failed)

    print(f"\nWorker 2: processed {len(slugs)} slugs, {len(succeeded)} succeeded, {len(failed)} failed")


if __name__ == "__main__":
    asyncio.run(main())
