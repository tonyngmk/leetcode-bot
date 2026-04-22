# Visualisation Instructions for LLM Population

This file guides an LLM to populate the `visualisation` field for each solution approach in `solution_cache.json`.

## File Location

`/Users/tonyngmk/Documents/Code/project/leetcode-bot/solution_cache.json`

## Purpose

The `visualisation` field enables the `/visualise` command to show step-by-step interactive visualisations of algorithm execution.

## Schema

Each approach should have a `visualisation` object with this structure:

```json
{
  "visualisation": {
    "input": {
      "nums": [2, 7, 11, 15],
      "target": 9
    },
    "steps": [
      {
        "text": "Brief description of what happens in this step",
        "highlight": [0, 1],
        "map": {"2": 0, "7": 1},
        "result": [0, 1],
        "pass": "Short description of the pass or operation"
      }
    ]
  }
}
```

## Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `input` | object | Yes | Sample input data. Must include at least `nums` (array). Add `target` if applicable. |
| `steps` | array | Yes | Ordered array of step objects. Min 2, max 10 steps recommended. |
| `text` | string | Yes | Short description of what this step does (~50 chars max) |
| `highlight` | array | No | Array indices to highlight in the array display (use for current elements being processed) |
| `map` | object | No | Hash map state to display (key→value pairs). Omit if not applicable. |
| `result` | any | No | Final result. Include only on final step. |
| `pass` | string | No | Short description of the current pass/operation (~30 chars max). Shown with "📌 Pass:" label. |

## Guidelines

### 1. Choose Representative Input
- Use a small, meaningful input that demonstrates the algorithm clearly
- For two-sum: `[2, 7, 11, 15]` with target `9` (indices 0,1)
- Avoid edge cases; show the happy path

### 2. Step Count
- **Minimum**: 2 steps (start, finish/result)
- **Maximum**: 10 steps (prefer ≤5 for clarity)
- Each step should represent a meaningful state change

### 3. Highlighting
- Highlight indices currently being processed
- Use `highlight: [0]` for single element
- Use `highlight: [0, 1]` for pair being checked

### 4. Pass Descriptions (Mandatory)
- Each step MUST have a `pass` field (≈20-30 chars)
- Examples:
  - "Check complement in map"
  - "Build hash map"
  - "Verify pair sums to target"
  - "Return indices"

### 5. Explanation from /solution
- The approach's `explanation` field is automatically shown above the steps
- Do NOT duplicate the explanation in visualisation steps
- Steps should be concrete actions, not theoretical description

## Example: Two-Sum (Brute Force)

```json
{
  "name": "Brute Force",
  "explanation": "Check every pair of numbers using nested loops to find two that sum to target. Simple but inefficient for large inputs.",
  "visualisation": {
    "input": {"nums": [2, 7, 11, 15], "target": 9},
    "steps": [
      {"text": "Check i=0, j=1: 2 + 7 = 9 ✓ Found!", "highlight": [0, 1], "result": [0, 1], "pass": "Nested loop checking each pair"},
      {"text": "nums[0] + nums[1] = 2 + 7 = 9 == target (9)", "highlight": [0, 1], "result": [0, 1], "pass": "Verify pair sums to target"},
      {"text": "Return [0, 1]", "highlight": [0, 1], "result": [0, 1], "pass": "Return indices"}
    ]
  }
}
```

## Example: Two-Pass Hash Map

```json
{
  "name": "Two-Pass Hash Map",
  "explanation": "Build a hash map of number to index in one pass, then iterate through the array checking if the complement exists in the map.",
  "visualisation": {
    "input": {"nums": [2, 7, 11, 15], "target": 9},
    "steps": [
      {"text": "Build hash map {2:0, 7:1, 11:2, 15:3}", "highlight": [], "map": {"2": 0, "7": 1, "11": 2, "15": 3}, "pass": "Pass 1: Build map of num → index"},
      {"text": "For i=0, complement=9-2=7. Found at index 1!", "highlight": [0], "map": {"2": 0, "7": 1, "11": 2, "15": 3}, "result": [0, 1], "pass": "Pass 2: Look for complement"},
      {"text": "Return [0, 1]", "highlight": [0, 1], "result": [0, 1], "pass": "Return indices"}
    ]
  }
}
```

## Example: One-Pass Hash Map

```json
{
  "name": "One-Pass Hash Map",
  "explanation": "Iterate through the array once, checking if the complement is already in the hash map. If not, add the current number to the map. This achieves O(n) time with a single pass.",
  "visualisation": {
    "input": {"nums": [2, 7, 11, 15], "target": 9},
    "steps": [
      {"text": "num=2, complement=7. Not in map. Add {2:0}", "highlight": [0], "map": {"2": 0}, "pass": "Check complement in map"},
      {"text": "num=7, complement=2. Found at index 0!", "highlight": [1], "map": {"2": 0, "7": 1}, "result": [0, 1], "pass": "Check complement in map"},
      {"text": "Return [0, 1]", "highlight": [0, 1], "result": [0, 1], "pass": "Return indices"}
    ]
  }
}
```

## Output Format

Edit `solution_cache.json`, adding the `visualisation` field to each approach object. The file is large (~144k lines), so target only the specific problem/slug you are updating.

## Git Workflow

After populating visualisations:

```bash
cd /Users/tonyngmk/Documents/Code/project/leetcode-bot

# Check status
git status

# Add changes
git add solution_cache.json

# Commit with descriptive message
git commit -m "Add visualisation data for <problem-slug>"

# Push to remote
git push origin main
```

Replace `main` with your branch name if different.