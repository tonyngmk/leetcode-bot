#!/usr/bin/env python3
"""Worker 1: Generate LeetCode solutions for zigzag batch."""

import asyncio
import json
import os
import re
import subprocess
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from leetcode import fetch_problem, save_solution, _strip_html, extract_constraints


API_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192
TIMEOUT = 120.0

SLUGS = [
    "zigzag-conversion",
    "reverse-integer",
    "string-to-integer-atoi",
    "palindrome-number",
    "regular-expression-matching",
]

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
PROGRESS_LOCK_FILE = PROGRESS_FILE + ".lock"


def get_api_key() -> str:
    result = subprocess.run(
        ["bash", os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def build_prompt(title: str, slug: str, difficulty: str, content: str) -> str:
    """Build the LLM prompt from problem details."""
    description = _strip_html(content)
    constraints = extract_constraints(content)
    constraints_text = "\n".join(f"- {c}" for c in constraints)

    return f"""You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {title} ({slug})
Difficulty: {difficulty}
Description: {description}

Constraints: {constraints_text}

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


async def call_llm(prompt: str, api_key: str) -> str:
    """Call the LLM API and return the text response."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # Support both standard and GLM-style response formats
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        elif "content" in data:
            return data["content"][0]["text"]
        else:
            raise ValueError(f"Unknown response format: {list(data.keys())}")


def extract_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    # Remove markdown code fences
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()
    return json.loads(text)


def validate(data: dict) -> bool:
    """Validate the response has approaches with all 5 language codes."""
    if "approaches" not in data:
        return False
    for ap in data["approaches"]:
        if "code" not in ap:
            return False
        code = ap["code"]
        for lang in ("python", "java", "cpp", "javascript", "go"):
            if lang not in code:
                return False
            if not code[lang] or not code[lang].strip():
                return False
    return True


def load_progress() -> dict:
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"total_problems": 3879, "completed_slugs": [], "failed_slugs": {}, "batch": 0, "total_batches": 78, "last_updated": ""}


def save_progress(data: dict) -> None:
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, separators=(",", ":"))


async def process_slug(slug: str, api_key: str) -> bool:
    """Process a single slug. Returns True on success."""
    print(f"[worker1] Fetching problem: {slug}")
    problem = await fetch_problem(slug)
    if problem is None:
        print(f"[worker1] FAILED to fetch: {slug}")
        return False

    title = problem.get("title", slug)
    difficulty = problem.get("difficulty", "Medium")
    content = problem.get("content", "")

    prompt = build_prompt(title, slug, difficulty, content)

    print(f"[worker1] Calling LLM for: {slug}")
    try:
        response_text = await call_llm(prompt, api_key)
        if not response_text:
            print(f"[worker1] Empty response for: {slug}")
            return False
    except Exception as e:
        print(f"[worker1] LLM call failed for {slug}: {e}")
        import traceback
        traceback.print_exc()
        return False

    try:
        data = extract_json(response_text)
    except Exception as e:
        print(f"[worker1] JSON parse failed for {slug}: {e}")
        # Print first 200 chars of response for debugging
        print(f"[worker1] Response preview: {response_text[:200]}")
        return False

    if not validate(data):
        print(f"[worker1] Validation failed for: {slug}")
        return False

    save_solution(slug, data)
    print(f"[worker1] Saved solution for: {slug}")
    return True


async def main():
    api_key = get_api_key()
    if not api_key:
        print("[worker1] ERROR: Could not get API key")
        return

    succeeded = []
    failed = []

    for slug in SLUGS:
        try:
            ok = await process_slug(slug, api_key)
            if ok:
                succeeded.append(slug)
            else:
                failed.append(slug)
        except Exception as e:
            print(f"[worker1] Unexpected error for {slug}: {e}")
            failed.append(slug)

        # Small delay between slugs to be polite
        await asyncio.sleep(1)

    # Update progress file
    progress = load_progress()
    for s in succeeded:
        if s not in progress["completed_slugs"]:
            progress["completed_slugs"].append(s)
    for f in failed:
        if f not in progress["failed_slugs"]:
            progress["failed_slugs"][f] = "worker1 error"
    from datetime import datetime, timezone
    progress["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress)

    n = len(SLUGS)
    m = len(succeeded)
    k = len(failed)
    print(f"Worker 1: processed {n} slugs, {m} succeeded, {k} failed")
    if failed:
        print(f"  Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
