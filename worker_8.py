#!/usr/bin/env python3
"""Worker 8: Generate LeetCode solutions for assigned slugs."""

import asyncio
import json
import re
import subprocess
import sys
import os

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from leetcode import fetch_problem, save_solution, _strip_html, extract_constraints, extract_description

API_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192
TIMEOUT_SECS = 120

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_cache.json")

SLUGS = [
    "first-missing-positive",
    "trapping-rain-water",
    "multiply-strings",
    "wildcard-matching",
    "jump-game-ii",
]


def get_api_token() -> str:
    result = subprocess.run(
        ["bash", "-c", "source ~/.llmbox/claude_byted_token.sh && echo $ANTHROPIC_API_KEY"],
        capture_output=True, text=True
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("Could not obtain ANTHROPIC_API_KEY")
    return token


def build_prompt(title: str, slug: str, difficulty: str, content: str) -> str:
    """Build the LLM prompt from problem details."""
    description_html = extract_description(content) or content
    description = _strip_html(description_html)
    constraints = extract_constraints(content)
    constraints_str = "\n".join(f"- {c}" for c in constraints) if constraints else "N/A"

    return (
        'You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.\n\n'
        f"Problem: {title} ({slug})\n"
        f"Difficulty: {difficulty}\n"
        f"Description: {description}\n"
        f"Constraints:\n{constraints_str}\n\n"
        'Output format (valid JSON only, no markdown):\n'
        '{\n'
        '  "approaches": [\n'
        '    {\n'
        '      "name": "Short approach name (e.g. Brute Force, Two Pointers, Hash Map)",\n'
        '      "explanation": "Clear explanation of the approach in 2-4 sentences.",\n'
        '      "time_complexity": "O(...)",\n'
        '      "space_complexity": "O(...)",\n'
        '      "code": {\n'
        '        "python": "class Solution:\\n    def methodName(self, ...) -> ...:\\n        ...",\n'
        '        "java": "class Solution {\\n    public ... methodName(...) {\\n        ...\\n    }\\n}",\n'
        '        "cpp": "class Solution {\\npublic:\\n    ... methodName(...) {\\n        ...\\n    }\\n};",\n'
        '        "javascript": "var methodName = function(...) {\\n    ...\\n};",\n'
        '        "go": "func methodName(...) ... {\\n    ...\\n}"\n'
        "      }\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "1. Include 2-3 approaches, from brute force to optimal\n"
        "2. Code must be complete, correct, and directly submittable on LeetCode\n"
        "3. Use the exact method signature LeetCode expects\n"
        "4. No import statements unless strictly necessary\n"
        "5. No markdown formatting in any field — plain text for explanation, raw code for code\n"
        "6. Escape newlines as \\n and quotes as \\\" in the JSON string values\n"
        "7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go"
    )


def extract_json(text: str) -> str:
    """Strip markdown fences and extract JSON content."""
    # Remove markdown fences
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
    text = text.strip()
    # Remove trailing fences
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


def validate(data: dict) -> tuple[bool, str]:
    """Validate the solution JSON. Returns (ok, message)."""
    if "approaches" not in data:
        return False, "Missing 'approaches' key"

    approaches = data["approaches"]
    if not isinstance(approaches, list) or len(approaches) == 0:
        return False, "'approaches' must be a non-empty list"

    required_langs = {"python", "java", "cpp", "javascript", "go"}
    for i, app in enumerate(approaches):
        if "code" not in app:
            return False, f"Approach {i} missing 'code' key"
        code = app["code"]
        missing = required_langs - set(code.keys())
        if missing:
            return False, f"Approach {i} missing languages: {missing}"
        for lang in required_langs:
            if not code[lang] or not code[lang].strip():
                return False, f"Approach {i} '{lang}' code is empty"
    return True, "OK"


async def call_llm(prompt: str, token: str) -> dict:
    """Call the LLM API and return parsed JSON."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
        resp = await client.post(API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # Extract content from response
    content = data.get("content", [])
    if isinstance(content, list):
        text = "".join(block.get("text", "") for block in content if isinstance(block, dict))
    else:
        text = str(content)

    json_text = extract_json(text)
    return json.loads(json_text)


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"total_problems": 3879, "completed_slugs": [], "failed_slugs": {}, "batch": 0,
            "total_batches": 78, "last_updated": "2026-03-26T00:00:00Z"}


def save_progress(prog: dict) -> None:
    prog["last_updated"] = "2026-03-26T00:00:00Z"
    # Atomic write
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(prog, f)
    os.replace(tmp, PROGRESS_FILE)


async def process_slug(slug: str, token: str) -> tuple[str, bool, str]:
    """Process a single slug. Returns (slug, success, message)."""
    try:
        problem = await fetch_problem(slug)
        if problem is None:
            return slug, False, "Failed to fetch problem from LeetCode"

        title = problem.get("title", slug)
        difficulty = problem.get("difficulty", "Medium")
        content = problem.get("content", "")

        prompt = build_prompt(title, slug, difficulty, content)
        data = await call_llm(prompt, token)

        ok, msg = validate(data)
        if not ok:
            return slug, False, f"Validation failed: {msg}"

        save_solution(slug, data)
        return slug, True, "OK"
    except json.JSONDecodeError as e:
        return slug, False, f"JSON decode error: {e}"
    except httpx.HTTPStatusError as e:
        return slug, False, f"HTTP error: {e.response.status_code}"
    except Exception as e:
        return slug, False, f"{type(e).__name__}: {e}"


async def main() -> None:
    token = get_api_token()
    succeeded = []
    failed = {}

    for slug in SLUGS:
        slug_out, ok, msg = await process_slug(slug, token)
        if ok:
            succeeded.append(slug_out)
            print(f"  [OK] {slug_out}")
        else:
            failed[slug_out] = msg
            print(f"  [FAIL] {slug_out}: {msg}")

    # Update progress
    prog = load_progress()
    for s in succeeded:
        if s not in prog["completed_slugs"]:
            prog["completed_slugs"].append(s)
    for s, err in failed.items():
        prog["failed_slugs"][s] = err
    save_progress(prog)

    n = len(SLUGS)
    m = len(succeeded)
    k = len(failed)
    print(f"Worker 8: processed {n} slugs, {m} succeeded, {k} failed")


if __name__ == "__main__":
    asyncio.run(main())
