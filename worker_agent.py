#!/usr/bin/env python3
"""
Worker subprocess for parallel LeetCode solution generation.
Reads a JSON list of slugs from stdin, generates solutions via Anthropic LLM,
and writes results as JSON to stdout.

Usage:
    echo '["two-sum", "reverse-linked-list"]' | python worker_agent.py --worker-id 0 --batch-idx 0

Environment variables:
    ANTHROPIC_API_KEY - Anthropic API key for LLM calls
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from typing import Optional

import httpx

# Add parent directory to path so we can import from the bot package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from leetcode import extract_constraints, extract_description, fetch_problem

# ---------------------------------------------------------------------------
# Anthropic API config
# ---------------------------------------------------------------------------
ANTHROPIC_API_URL = "https://llmbox.bytedance.net/v1/messages"
ANTHROPIC_MODEL = "glm-5"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # exponential backoff: 2s, 4s, 8s
RATE_LIMIT_DELAY = 0.5  # gap between LLM calls within a worker


def _get_api_key() -> str:
    """Get API key from llmbox helper or environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # Try llmbox helper
    try:
        result = subprocess.run(
            [os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------
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
    """Build the LLM prompt from a problem dict."""
    content = problem.get("content", "") or ""
    title = problem.get("title", "")
    slug = problem.get("titleSlug", "")
    difficulty = problem.get("difficulty", "")

    description = extract_description(content) or "(no description)"
    constraints = "\n".join(f"- {c}" for c in extract_constraints(content)) or "(no constraints)"

    return PROMPT_TEMPLATE.format(
        title=title,
        slug=slug,
        difficulty=difficulty,
        description=description,
        constraints=constraints,
    )


def extract_json(raw: str) -> Optional[dict]:
    """Extract JSON dict from LLM response text.

    Tries:
    1. Strip markdown fences and json.loads
    2. Extract first {...} block with regex fallback
    """
    if not raw:
        return None

    # Try stripping markdown fences first
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON object with regex
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return None


async def call_anthropic(prompt: str) -> Optional[dict]:
    """Call Anthropic LLM API with retry and exponential backoff."""
    api_key = _get_api_key()
    if not api_key:
        print("[Worker] ERROR: could not get API key", file=sys.stderr)
        return None

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()

                # Extract text from response
                raw_text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        raw_text += block.get("text", "")

                result = extract_json(raw_text)
                if result is not None:
                    return result

                print(f"[Worker] Attempt {attempt+1}: LLM returned non-JSON, retrying...", file=sys.stderr)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[Worker] Rate limited (429), attempt {attempt+1}, sleeping {delay}s", file=sys.stderr)
                await asyncio.sleep(delay)
                continue
            print(f"[Worker] HTTP error {e.response.status_code}: {e}", file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None
        except httpx.RequestError as e:
            print(f"[Worker] Request error: {e}, attempt {attempt+1}", file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None
        except json.JSONDecodeError as e:
            print(f"[Worker] JSON decode error in response: {e}, attempt {attempt+1}", file=sys.stderr)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return None

    return None


def validate_solution(data: dict, slug: str) -> bool:
    """Validate that solution data has the required structure."""
    required_langs = {"python", "java", "cpp", "javascript", "go"}

    if not isinstance(data, dict):
        return False

    approaches = data.get("approaches")
    if not isinstance(approaches, list) or len(approaches) == 0:
        print(f"[Worker] Invalid: {slug} has no approaches", file=sys.stderr)
        return False

    for i, a in enumerate(approaches):
        if not isinstance(a, dict):
            print(f"[Worker] Invalid: approach {i} in {slug} is not a dict", file=sys.stderr)
            return False

        # Check required fields
        for field in ("name", "explanation", "time_complexity", "space_complexity", "code"):
            if field not in a:
                print(f"[Worker] Invalid: {slug} approach {i} missing '{field}'", file=sys.stderr)
                return False

        # Check all 5 languages present
        code = a.get("code", {})
        if not isinstance(code, dict):
            print(f"[Worker] Invalid: {slug} approach {i} code is not a dict", file=sys.stderr)
            return False

        missing = required_langs - set(code.keys())
        if missing:
            print(f"[Worker] Invalid: {slug} approach {i} missing languages: {missing}", file=sys.stderr)
            return False

    return True


async def generate_solution_for_slug(slug: str) -> tuple[str, Optional[dict], Optional[str]]:
    """Generate solution for a single slug. Returns (slug, solution_data, error_msg)."""
    # Fetch problem details
    problem = await fetch_problem(slug)
    if problem is None:
        return slug, None, "failed to fetch problem from LeetCode"

    # Build prompt
    prompt = build_prompt(problem)

    # Call LLM
    solution = await call_anthropic(prompt)
    if solution is None:
        return slug, None, "LLM returned invalid or empty response after retries"

    # Validate
    if not validate_solution(solution, slug):
        return slug, None, "solution validation failed"

    return slug, solution, None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Worker agent for LeetCode solution generation")
    parser.add_argument("--worker-id", type=int, required=True, help="Worker ID for logging")
    parser.add_argument("--batch-idx", type=int, required=True, help="Batch index for logging")
    args = parser.parse_args()

    worker_id = args.worker_id
    batch_idx = args.batch_idx

    # Read slugs from stdin
    try:
        slugs = json.loads(sys.stdin.buffer.read().decode())
    except Exception as e:
        print(f"[Worker {worker_id}] Failed to read slugs from stdin: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(slugs, list):
        print(f"[Worker {worker_id}] Expected list of slugs, got {type(slugs)}", file=sys.stderr)
        sys.exit(1)

    print(f"[Worker {worker_id}] Batch {batch_idx}: processing {len(slugs)} slugs", file=sys.stderr)

    results = {}

    for i, slug in enumerate(slugs):
        slug_clean = slug.strip()
        if not slug_clean:
            continue

        slug_key, data, error = await generate_solution_for_slug(slug_clean)

        if data is not None:
            results[slug_key] = data
            print(f"[Worker {worker_id}] OK: {slug_key} ({i+1}/{len(slugs)})", file=sys.stderr)
        else:
            results[f"_error_{slug_key}"] = error or "unknown error"
            print(f"[Worker {worker_id}] FAIL: {slug_key} - {error} ({i+1}/{len(slugs)})", file=sys.stderr)

        # Rate limiting: sleep between LLM calls
        if i < len(slugs) - 1:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    # Write results to stdout
    sys.stdout.buffer.write(json.dumps(results, separators=(",", ":")).encode())
    sys.stdout.buffer.flush()
    print(f"[Worker {worker_id}] Done. {len(results)} results written.", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
