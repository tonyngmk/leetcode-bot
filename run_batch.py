#!/usr/bin/env python3
"""
Standalone batch solution generator.
Reads slugs from COMMAND LINE args (not stdin), generates solutions
via llmbox API, saves atomically to solution_cache.json.

Usage:
    python3 run_batch.py worker0 "slug1,slug2,slug3,..."
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from leetcode import extract_constraints, extract_description, fetch_problem

API_URL = "https://llmbox.bytedance.net/v1/messages"
DEFAULT_MODEL = "glm-5"
RETRY_BASE_DELAY = 2.0
RATE_LIMIT_DELAY = 0.5
MAX_RETRIES = 3


def get_api_key():
    try:
        r = subprocess.run(
            [os.path.expanduser("~/.llmbox/claude_byted_token.sh")],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
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


def build_prompt(problem):
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


def extract_json(raw):
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


def atomic_save(slug, data):
    """Load existing cache, merge new data, atomic write."""
    cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solution_cache.json")
    current = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            current = {}
    current[slug] = data
    dir_ = os.path.dirname(cache_file) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(current, f, separators=(",", ":"))
        os.replace(tmp, cache_file)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def validate(data):
    required_langs = {"python", "java", "cpp", "javascript", "go"}
    approaches = data.get("approaches")
    if not isinstance(approaches, list) or len(approaches) == 0:
        return False
    for a in approaches:
        if not isinstance(a, dict):
            return False
        for field in ("name", "explanation", "time_complexity", "space_complexity", "code"):
            if field not in a:
                return False
        code = a.get("code", {})
        if not isinstance(code, dict) or not required_langs.issubset(code):
            return False
    return True


async def generate(slug):
    api_key = get_api_key()
    if not api_key:
        return slug, None, "no API key"

    problem = await fetch_problem(slug)
    if problem is None:
        return slug, None, "fetch failed"

    prompt = build_prompt(problem)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(API_URL, headers=headers, json=body)
                resp.raise_for_status()
                raw_text = ""
                # Check for empty response first
                if not resp.text.strip():
                    print(f"[Worker] Empty response on attempt {attempt+1}", file=sys.stderr)
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                try:
                    data = resp.json()
                except json.JSONDecodeError as e:
                    print(f"[Worker] JSON decode error: {e} on attempt {attempt+1}", file=sys.stderr)
                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                # Handle different response formats
                if "content" in data:
                    for block in data.get("content", []):
                        if block.get("type") == "text":
                            raw_text += block.get("text", "")
                elif "choices" in data:
                    for choice in data.get("choices", []):
                        if "message" in choice:
                            raw_text += choice["message"].get("content", "")
                result = extract_json(raw_text)
                if result is not None and validate(result):
                    return slug, result, None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
        except httpx.RequestError:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
            continue
        except json.JSONDecodeError:
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
            continue

    return slug, None, "LLM failed after retries"


async def main():
    parser = argparse.ArgumentParser(description="Worker for LeetCode solution generation")
    parser.add_argument("worker_id", help="Worker ID (e.g., w0)")
    parser.add_argument("slugs", help="Comma-separated list of problem slugs")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"Model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    global MODEL
    MODEL = args.model

    worker_id = args.worker_id
    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]

    print(f"[Worker {worker_id}] Using model: {MODEL}", file=sys.stderr)
    print(f"[Worker {worker_id}] Processing {len(slugs)} slugs", file=sys.stderr)
    succeeded, failed = 0, 0

    for i, slug in enumerate(slugs):
        slug_key, data, err = await generate(slug)
        if data is not None:
            atomic_save(slug_key, data)
            succeeded += 1
            print(f"[Worker {worker_id}] OK: {slug_key} ({i+1}/{len(slugs)})", file=sys.stderr)
        else:
            failed += 1
            print(f"[Worker {worker_id}] FAIL: {slug_key} - {err} ({i+1}/{len(slugs)})", file=sys.stderr)
        if i < len(slugs) - 1:
            await asyncio.sleep(RATE_LIMIT_DELAY)

    print(f"[Worker {worker_id}] Done: {succeeded} succeeded, {failed} failed", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
