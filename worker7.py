#!/usr/bin/env python3
"""
Worker 7: Generate LeetCode solutions for a batch of slugs.
"""
import asyncio
import json
import re
import sys
import os

# Add project dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
import leetcode
from leetcode import fetch_problem, save_solution, extract_constraints, extract_description, _strip_html


LLMBOX_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192
TIMEOUT = 120.0

SLUGS = [
    "valid-sudoku",
    "sudoku-solver",
    "count-and-say",
    "combination-sum",
    "combination-sum-ii",
]

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")


def get_api_token() -> str:
    token_path = os.path.expanduser("~/.llmbox/claude_byted_token.sh")
    result = os.popen(f"bash {token_path}").read().strip()
    if not result:
        raise RuntimeError("Failed to get API token from ~/.llmbox/claude_byted_token.sh")
    return result


def build_prompt(title: str, slug: str, difficulty: str, content: str, constraints: list[str]) -> str:
    desc = _strip_html(extract_description(content) or content)
    cons = "\n".join(f"- {c}" for c in constraints)
    return f"""You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {title} ({slug})
Difficulty: {difficulty}
Description: {desc}
Constraints:
{cons}

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
7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go
"""


def extract_json(text: str) -> str:
    """Strip markdown fences and extract JSON content."""
    text = text.strip()
    # Remove ```json fences
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    # Remove trailing ``` if any
    text = re.sub(r'\s*```\s*$', '', text)
    return text.strip()


def validate(data: dict) -> tuple[bool, str]:
    """Validate that the response has approaches with all 5 language codes."""
    if "approaches" not in data:
        return False, "Missing 'approaches' key"

    approaches = data["approaches"]
    if not isinstance(approaches, list) or len(approaches) == 0:
        return False, "approaches must be a non-empty list"

    required_langs = ["python", "java", "cpp", "javascript", "go"]
    for i, app in enumerate(approaches):
        if "code" not in app:
            return False, f"Approach {i} missing 'code'"
        for lang in required_langs:
            if lang not in app["code"]:
                return False, f"Approach {i} missing code for '{lang}'"
            code = app["code"][lang]
            if not code or not isinstance(code, str) or not code.strip():
                return False, f"Approach {i} has empty code for '{lang}'"

    return True, "OK"


async def call_llm(prompt: str, token: str) -> str:
    """Call the LLM API and return the response text."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "user", "content": prompt}
        ],
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(LLMBOX_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # The API returns content as [{"text": "..."}] at top level
        content = data.get("content", [])
        if isinstance(content, list) and content:
            return content[0].get("text", "")
        return ""


async def process_slug(slug: str, token: str) -> tuple[str, bool, str]:
    """Process a single slug. Returns (slug, success, error_message)."""
    try:
        problem = await fetch_problem(slug)
        if problem is None:
            return slug, False, "Failed to fetch problem"

        title = problem.get("title", slug)
        difficulty = problem.get("difficulty", "Medium")
        content = problem.get("content", "")
        constraints = extract_constraints(content)

        prompt = build_prompt(title, slug, difficulty, content, constraints)
        response_text = await call_llm(prompt, token)

        if not response_text:
            return slug, False, "Empty LLM response"

        json_text = extract_json(response_text)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            return slug, False, f"JSON parse error: {e}"

        valid, msg = validate(data)
        if not valid:
            return slug, False, f"Validation failed: {msg}"

        save_solution(slug, data)
        return slug, True, ""

    except Exception as e:
        return slug, False, str(e)


def update_progress(slugs: list[str], succeeded: list[str], failed: dict[str, str]):
    """Atomically update solution_gen_progress.json."""
    try:
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
    except Exception:
        progress = {"total_problems": 3879, "completed_slugs": [], "failed_slugs": {}, "batch": 0, "total_batches": 78, "last_updated": ""}

    for s in succeeded:
        if s not in progress["completed_slugs"]:
            progress["completed_slugs"].append(s)
    for s, err in failed.items():
        progress["failed_slugs"][s] = err

    progress["last_updated"] = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Atomic write
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f, separators=(",", ":"))
    os.replace(tmp, PROGRESS_FILE)


async def main():
    token = get_api_token()
    succeeded = []
    failed = {}

    for slug in SLUGS:
        print(f"Processing: {slug}")
        slug_out, ok, err = await process_slug(slug, token)
        if ok:
            succeeded.append(slug_out)
            print(f"  OK: {slug_out}")
        else:
            failed[slug_out] = err
            print(f"  FAILED: {slug_out} — {err}")

    update_progress(SLUGS, succeeded, failed)

    n = len(SLUGS)
    m = len(succeeded)
    k = n - m
    print(f"Worker 7: processed {n} slugs, {m} succeeded, {k} failed")


if __name__ == "__main__":
    asyncio.run(main())
