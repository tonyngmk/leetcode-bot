#!/usr/bin/env python3
"""
Worker 9: Generate solutions for a batch of LeetCode problem slugs.
"""

import asyncio
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

import leetcode
from config import SOLUTION_CACHE_FILE


API_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192

SLUGS = [
    "permutations",
    "permutations-ii",
    "rotate-image",
    "group-anagrams",
    "powx-n",
]


def get_api_key() -> str:
    result = subprocess.run(
        ["bash", os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_prompt(problem: dict, description: str, constraints: list[str]) -> str:
    difficulty = problem.get("difficulty", "Unknown")
    title = problem.get("title", "")
    slug = problem.get("titleSlug", "")

    constraints_text = "\n".join(f"- {c}" for c in constraints) if constraints else "None provided"

    prompt = f"""You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {title} ({slug})
Difficulty: {difficulty}
Description: {description}
Constraints:
{constraints_text}

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
6. Escape newlines as \\n and quotes as \\\\" in the JSON string values
7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go
"""
    return prompt


def extract_json(text: str) -> str:
    """Strip markdown fences and extract JSON content."""
    # Remove ```json ... ``` fences
    text = re.sub(r"```json\s*", "", text, flags=re.DOTALL)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    return text


def validate_response(data: dict) -> tuple[bool, str]:
    """Validate that the response has all required languages in each approach."""
    if "approaches" not in data:
        return False, "Missing 'approaches' key"

    approaches = data["approaches"]
    if not approaches or not isinstance(approaches, list):
        return False, "'approaches' must be a non-empty list"

    required_langs = {"python", "java", "cpp", "javascript", "go"}

    for i, approach in enumerate(approaches):
        if "code" not in approach:
            return False, f"Approach {i} missing 'code' key"

        code = approach["code"]
        missing = required_langs - set(code.keys())
        if missing:
            return False, f"Approach {i} missing languages: {missing}"

        for lang in required_langs:
            if not code[lang] or not isinstance(code[lang], str):
                return False, f"Approach {i} '{lang}' code is empty or not a string"

    return True, "OK"


def load_progress() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_progress(progress: dict) -> None:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f)
    os.replace(tmp, path)


async def process_slug(slug: str, api_key: str) -> tuple[str, bool, str]:
    """Process a single slug. Returns (slug, success, error_message)."""
    try:
        # Step 1: Fetch problem
        problem = await leetcode.fetch_problem(slug)
        if problem is None:
            return slug, False, "Failed to fetch problem"

        # Step 2: Build description and constraints
        content = problem.get("content", "") or ""
        description = leetcode._strip_html(content) if content else ""

        raw_constraints = leetcode.extract_constraints(content)
        constraints = []
        for c in raw_constraints:
            # strip any residual HTML
            clean = re.sub(r'<[^>]+>', '', c).strip()
            if clean:
                constraints.append(clean)

        # Step 3: Build prompt
        prompt = build_prompt(problem, description, constraints)

        # Step 4: Call LLM API
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        # The API returns a flat response with "content" list, not "messages" array
        # Format: {"content": [{"type": "text", "text": "..."}], "id": "...", ...}
        content_blocks = result.get("content", [])
        if not content_blocks:
            return slug, False, "No content in API response"

        # Extract text from content blocks
        assistant_content = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                assistant_content += block.get("text", "")

        if not assistant_content:
            return slug, False, "Empty assistant response"

        # Step 5: Extract and parse JSON
        json_text = extract_json(assistant_content)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            # Try to find JSON within the text
            match = re.search(r"\{[\s\S]*\}", json_text)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return slug, False, f"JSON parse error after extraction: {e}"
            else:
                return slug, False, f"JSON parse error: {e}"

        # Step 6: Validate
        valid, msg = validate_response(data)
        if not valid:
            return slug, False, f"Validation failed: {msg}"

        # Step 7: Save
        leetcode.save_solution(slug, data)
        return slug, True, ""

    except httpx.HTTPStatusError as e:
        return slug, False, f"HTTP error: {e.response.status_code}"
    except Exception as e:
        return slug, False, f"Exception: {e}"


async def main():
    api_key = get_api_key()
    succeeded = []
    failed = []

    for slug in SLUGS:
        result_slug, ok, err = await process_slug(slug, api_key)
        if ok:
            succeeded.append(result_slug)
            print(f"  [OK] {result_slug}")
        else:
            failed.append((result_slug, err))
            print(f"  [FAIL] {result_slug}: {err}")

    n = len(SLUGS)
    m = len(succeeded)
    k = len(failed)
    print(f"\nWorker 9: processed {n} slugs, {m} succeeded, {k} failed")

    # Update progress
    if succeeded or failed:
        progress = load_progress()
        for s in succeeded:
            if s not in progress.get("completed_slugs", []):
                progress.setdefault("completed_slugs", []).append(s)
        for f_slug, _ in failed:
            progress.setdefault("failed_slugs", {})[f_slug] = "error"
        save_progress(progress)


if __name__ == "__main__":
    asyncio.run(main())
