# LeetCode Solution Generator Prompt

Use this prompt template with an LLM to generate solutions for caching.

## Instructions

Given a LeetCode problem, generate a JSON object with multiple solution approaches. The output must be **valid JSON only** — no markdown fences, no commentary outside the JSON.

## Prompt

```
You are a LeetCode solution generator. Given the following problem, produce a JSON object with solution approaches ordered from least optimal to most optimal.

Problem: {problem_title} ({problem_slug})
Difficulty: {difficulty}
Description: {description}
Constraints: {constraints}

Output format (valid JSON only, no markdown):
{
  "approaches": [
    {
      "name": "Short approach name (e.g. Brute Force, Two Pointers, Hash Map)",
      "explanation": "Clear explanation of the approach in 2-4 sentences. Describe the key insight, how the algorithm works, and why it achieves its complexity.",
      "time_complexity": "O(...)",
      "space_complexity": "O(...)",
      "code": {
        "python": "class Solution:\n    def methodName(self, ...) -> ...:\n        ...",
        "java": "class Solution {\n    public ... methodName(...) {\n        ...\n    }\n}",
        "cpp": "class Solution {\npublic:\n    ... methodName(...) {\n        ...\n    }\n};",
        "javascript": "var methodName = function(...) {\n    ...\n};",
        "go": "func methodName(...) ... {\n    ...\n}"
      }
    }
  ]
}

Rules:
1. Include 2-3 approaches, from brute force to optimal
2. Code must be complete, correct, and directly submittable on LeetCode
3. Use the exact method signature LeetCode expects
4. No import statements unless strictly necessary
5. No markdown formatting in any field — plain text for explanation, raw code for code
6. Escape newlines as \n and quotes as \" in the JSON string values
7. Each approach must have code for ALL five languages: python, java, cpp, javascript, go
```

## Example Usage

1. Fetch the problem using `/problem <slug>` to get its details
2. Fill in the template above with the problem data
3. Send to LLM and capture the JSON response
4. Validate the JSON and add it to `solution_cache.json` under the problem slug key

## Cache File Format

`solution_cache.json` maps slug to the JSON object above:

```json
{
  "two-sum": {
    "approaches": [...]
  },
  "reverse-linked-list": {
    "approaches": [...]
  }
}
```
