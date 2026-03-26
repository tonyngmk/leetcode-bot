#!/usr/bin/env python3
"""Worker 4: generate solutions for batch slugs."""

import asyncio
import json
import re
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
import leetcode
from leetcode import fetch_problem, save_solution
from leetcode import extract_constraints, extract_description

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
7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go
"""

LANGUAGES = ["python", "java", "cpp", "javascript", "go"]
SLUGS = [
    "merge-two-sorted-lists",
    "generate-parentheses",
    "merge-k-sorted-lists",
    "swap-nodes-in-pairs",
    "reverse-nodes-in-k-group",
]


def get_api_key() -> str:
    result = subprocess.run(
        ["bash", os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def build_prompt(problem: dict, slug: str) -> str:
    title = problem.get("title", "")
    difficulty = problem.get("difficulty", "")
    content = problem.get("content", "") or ""

    # Extract plain text description
    desc_html = extract_description(content)
    desc_plain = leetcode._strip_html(desc_html) if desc_html else content

    # Extract constraints
    constraints_list = extract_constraints(content)
    constraints_str = "\n".join(f"- {c}" for c in constraints_list)

    return PROMPT_TEMPLATE.format(
        title=title,
        slug=slug,
        difficulty=difficulty,
        description=desc_plain,
        constraints=constraints_str,
    )


def extract_json(text: str) -> str:
    """Strip markdown fences and extract JSON string."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
    return text.strip()


def validate(data: dict) -> list[str]:
    """Return list of missing languages."""
    missing = []
    for lang in LANGUAGES:
        for approach in data.get("approaches", []):
            if "code" not in approach or lang not in approach["code"]:
                missing.append(lang)
                break
    return missing


async def process_slug(slug: str, api_key: str) -> tuple[str, bool, str]:
    """Fetch problem, call LLM, validate, save. Returns (slug, success, error)."""
    try:
        # 1. Fetch problem
        problem = await fetch_problem(slug)
        if not problem:
            return slug, False, "Failed to fetch problem"

        # 2. Build prompt
        prompt_text = build_prompt(problem, slug)

        # 3. Call LLM API
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": MAX_TOKENS,
                    "messages": [
                        {"role": "user", "content": prompt_text}
                    ],
                },
            )
            resp.raise_for_status()
            resp_data = resp.json()
            content = resp_data.get("content", [])
            if isinstance(content, list) and len(content) > 0:
                llm_text = content[0].get("text", "")
            else:
                llm_text = str(resp_data.get("content", ""))

        # 4. Extract JSON
        json_str = extract_json(llm_text)
        data = json.loads(json_str)

        # 5. Validate
        missing = validate(data)
        if missing:
            return slug, False, f"Missing languages: {missing}"

        # 6. Save
        save_solution(slug, data)
        return slug, True, ""

    except json.JSONDecodeError as e:
        return slug, False, f"JSON decode error: {e}"
    except Exception as e:
        return slug, False, f"{type(e).__name__}: {e}"


async def main():
    api_key = get_api_key()
    succeeded = 0
    failed = 0
    failed_details = {}

    for slug in SLUGS:
        print(f"Processing: {slug}", flush=True)
        slug_ok, success, error = await process_slug(slug, api_key)
        if success:
            succeeded += 1
            print(f"  OK: {slug_ok}", flush=True)
        else:
            failed += 1
            failed_details[slug_ok] = error
            print(f"  FAILED: {slug_ok} — {error}", flush=True)

    # Update progress file
    progress_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_gen_progress.json")
    with open(progress_path) as f:
        progress = json.load(f)

    for slug in SLUGS:
        if slug not in progress["completed_slugs"]:
            if slug in failed_details:
                progress["failed_slugs"][slug] = failed_details[slug]
            else:
                progress["completed_slugs"].append(slug)

    # Atomic write
    tmp_path = progress_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(progress, f, separators=(",", ":"))
    os.replace(tmp_path, progress_path)

    print(f"\nWorker 4: processed {len(SLUGS)} slugs, {succeeded} succeeded, {failed} failed", flush=True)
    if failed_details:
        print(f"Failed details: {failed_details}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
