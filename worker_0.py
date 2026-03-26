#!/usr/bin/env python3
"""
Worker 0: Generate LeetCode solutions for a batch of slugs.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from leetcode import fetch_problem, save_solution, extract_constraints, extract_description
from config import SOLUTION_CACHE_FILE, PROBLEM_CACHE_FILE

LLM_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
RATE_LIMIT_DELAY = 0.5

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")

SLUGS = [
    "two-sum",
    "add-two-numbers",
    "longest-substring-without-repeating-characters",
    "median-of-two-sorted-arrays",
    "longest-palindromic-substring",
]

LANGUAGES = ["python", "java", "cpp", "javascript", "go"]


def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["bash", os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


PROMPT_TEMPLATE = """\
You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {title} ({slug})
Difficulty: {difficulty}
Description: {description}
Constraints: {constraints}

Output valid JSON only — no markdown fences, no commentary outside the JSON.

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
8. Output ONLY the JSON object, nothing else.
"""


def build_prompt(problem: dict) -> str:
    content = problem.get("content", "") or ""
    title = problem.get("title", "")
    slug = problem.get("titleSlug", "")
    difficulty = problem.get("difficulty", "")
    description = extract_description(content) or "(no description)"
    constraints = "\n".join(f"- {c}" for c in extract_constraints(content)) or "(no constraints)"
    return PROMPT_TEMPLATE.format(
        title=title, slug=slug, difficulty=difficulty,
        description=description, constraints=constraints,
    )


def extract_json(raw: str):
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def validate_solution(data: dict, slug: str) -> tuple[bool, str]:
    required_langs = {"python", "java", "cpp", "javascript", "go"}
    if not isinstance(data, dict):
        return False, "not a dict"
    approaches = data.get("approaches")
    if not isinstance(approaches, list) or len(approaches) == 0:
        return False, "no approaches"
    for i, a in enumerate(approaches):
        if not isinstance(a, dict):
            return False, f"approach {i} not a dict"
        for field in ("name", "explanation", "time_complexity", "space_complexity", "code"):
            if field not in a:
                return False, f"approach {i} missing '{field}'"
        code = a.get("code", {})
        if not isinstance(code, dict):
            return False, f"approach {i} code not a dict"
        missing = required_langs - set(code.keys())
        if missing:
            return False, f"approach {i} missing languages: {missing}"
    return True, "OK"


async def call_llm(prompt: str, api_key: str):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(LLM_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                raw_text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        raw_text += block.get("text", "")
                result = extract_json(raw_text)
                if result is not None:
                    return result
                print(f"[Worker 0] Attempt {attempt+1}: non-JSON response, retrying...")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[Worker 0] Rate limited (429), sleeping {delay}s")
                await asyncio.sleep(delay)
                continue
            print(f"[Worker 0] HTTP error {e.response.status_code}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None
        except httpx.RequestError as e:
            print(f"[Worker 0] Request error: {e}, attempt {attempt+1}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None
        except json.JSONDecodeError as e:
            print(f"[Worker 0] JSON decode error: {e}, attempt {attempt+1}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None
    return None


def load_progress() -> dict:
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"total_problems": 3879, "completed_slugs": [], "failed_slugs": {}, "batch": 0, "total_batches": 78, "last_updated": ""}


def save_progress(progress: dict) -> None:
    progress["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f, separators=(",", ":"))
    os.replace(tmp, PROGRESS_FILE)


async def process_slug(slug: str, api_key: str) -> tuple[str, bool]:
    """Process a single slug. Returns (slug, success)."""
    print(f"[Worker 0] Fetching: {slug}")
    problem = await fetch_problem(slug)
    if problem is None:
        print(f"[Worker 0] FAILED to fetch: {slug}")
        return slug, False

    prompt = build_prompt(problem)
    print(f"[Worker 0] Calling LLM for: {slug}")

    result = await call_llm(prompt, api_key)
    if result is None:
        print(f"[Worker 0] LLM failed for: {slug}")
        return slug, False

    valid, msg = validate_solution(result, slug)
    if not valid:
        print(f"[Worker 0] Validation failed for {slug}: {msg}")
        return slug, False

    save_solution(slug, result)
    print(f"[Worker 0] SUCCESS: {slug}")
    return slug, True


async def main():
    api_key = get_api_key()
    if not api_key:
        print("[Worker 0] ERROR: Could not get API token")
        return

    succeeded = []
    failed = []

    for slug in SLUGS:
        slug_clean = slug.lower().strip()
        slug_result, ok = await process_slug(slug_clean, api_key)
        if ok:
            succeeded.append(slug_result)
        else:
            failed.append(slug_result)

        if slug != SLUGS[-1]:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    # Update progress
    progress = load_progress()
    for s in succeeded:
        if s not in progress["completed_slugs"]:
            progress["completed_slugs"].append(s)
    for f in failed:
        if f not in progress["failed_slugs"]:
            progress["failed_slugs"][f] = "Worker 0 failed"
    save_progress(progress)

    print(f"\nWorker 0: processed {len(SLUGS)} slugs, {len(succeeded)} succeeded, {len(failed)} failed")


if __name__ == "__main__":
    asyncio.run(main())
