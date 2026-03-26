#!/usr/bin/env python3
"""Worker 3: Generate solutions for assigned slugs."""

import asyncio
import json
import re
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
import leetcode
from config import SOLUTION_CACHE_FILE


SLUGS = [
    "3sum-closest",
    "letter-combinations-of-a-phone-number",
    "4sum",
    "remove-nth-node-from-end-of-list",
    "valid-parentheses",
]

API_URL = "https://llmbox.bytedance.net/v1/messages"
MODEL = "glm-5"
MAX_TOKENS = 8192


def get_api_key() -> str:
    result = subprocess.run(
        ["bash", "-c", "source ~/.llmbox/claude_byted_token.sh && echo $ANTHROPIC_API_KEY"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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


def build_prompt(problem: dict, slug: str) -> str:
    title = problem.get("title", "")
    difficulty = problem.get("difficulty", "")
    content = problem.get("content", "")

    # Extract description
    description = leetcode.extract_description(content)
    description = leetcode._strip_html(description)

    # Extract constraints
    constraints_list = leetcode.extract_constraints(content)
    constraints = "\n".join(f"- {c}" for c in constraints_list)

    return PROMPT_TEMPLATE.format(
        title=title,
        slug=slug,
        difficulty=difficulty,
        description=description,
        constraints=constraints or "None provided",
    )


def extract_json(text: str) -> dict:
    """Strip markdown fences and parse JSON."""
    # Remove ```json ... ``` fences
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()
    return json.loads(text)


def validate_response(data: dict) -> bool:
    """Validate that response has approaches with code in all 5 languages."""
    if "approaches" not in data:
        return False
    required_langs = {"python", "java", "cpp", "javascript", "go"}
    for approach in data["approaches"]:
        if "code" not in approach:
            return False
        code = approach["code"]
        if not isinstance(code, dict):
            return False
        missing = required_langs - set(code.keys())
        if missing:
            print(f"  Missing languages: {missing}")
            return False
    return True


async def process_slug(slug: str, api_key: str) -> tuple[str, bool, str]:
    """Process a single slug. Returns (slug, success, error_msg)."""
    print(f"Processing: {slug}")

    # Fetch problem
    problem = await leetcode.fetch_problem(slug)
    if problem is None:
        return slug, False, "Failed to fetch problem"

    prompt = build_prompt(problem, slug)

    # Call LLM API
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()
            content = result.get("content", [])
            if isinstance(content, list) and len(content) > 0:
                text = content[0].get("text", "")
            else:
                text = str(content)
    except Exception as e:
        return slug, False, f"API call failed: {e}"

    # Extract and parse JSON
    try:
        data = extract_json(text)
    except Exception as e:
        return slug, False, f"JSON parse failed: {e}"

    # Validate
    if not validate_response(data):
        return slug, False, "Validation failed: missing languages or malformed"

    # Save
    try:
        leetcode.save_solution(slug, data)
        print(f"  Saved: {slug}")
    except Exception as e:
        return slug, False, f"Save failed: {e}"

    return slug, True, ""


def update_progress(slugs_completed: list[str], slugs_failed: dict):
    """Atomically update solution_gen_progress.json."""
    progress_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json"
    )
    try:
        with open(progress_file) as f:
            progress = json.load(f)
    except Exception:
        progress = {}

    if "completed_slugs" not in progress:
        progress["completed_slugs"] = []

    for slug in slugs_completed:
        if slug not in progress["completed_slugs"]:
            progress["completed_slugs"].append(slug)

    if "failed_slugs" not in progress:
        progress["failed_slugs"] = {}

    for slug, reason in slugs_failed.items():
        progress["failed_slugs"][slug] = reason

    # Write atomically
    tmp = progress_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f)
    os.replace(tmp, progress_file)


async def main():
    api_key = get_api_key()
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found")
        sys.exit(1)

    succeeded = []
    failed = {}

    for slug in SLUGS:
        slug_out, ok, err = await process_slug(slug, api_key)
        if ok:
            succeeded.append(slug_out)
        else:
            failed[slug_out] = err
            print(f"  FAILED: {slug_out} - {err}")
        # Small delay between slugs
        await asyncio.sleep(1)

    print(f"\nWorker 3: processed {len(SLUGS)} slugs, {len(succeeded)} succeeded, {len(failed)} failed")

    if succeeded or failed:
        update_progress(succeeded, failed)
        print("Progress updated.")


if __name__ == "__main__":
    asyncio.run(main())
