---
active: true
iteration: 1
session_id: 
max_iterations: 5
completion_promise: null
started_at: "2026-03-26T03:22:35Z"
---

You are running iteration {iteration} of 5 of the LeetCode solution generator. Your goal is to process a batch of LeetCode problems in parallel using Claude Code's TeamCreate and Agent tools.

FIRST: Check if solution_gen_progress.json exists. If it does, read it to determine which problems have already been completed and which batch to process next. This ensures we resume from where we left off.

Then:
1. Create a team called 'leetcode-solution-gen' with description 'Parallel LeetCode solution generator'
2. Load the problem list - if problem_cache.json exists and has slugs, use those. If not, use fetch_problems to get a batch of 50 slugs from LeetCode API.
3. Filter out already-completed slugs from previous iterations
4. If no slugs remain, report 'All problems processed!' and skip to verification
5. Create up to 10 worker subagents, each assigned ~5 slugs from the remaining batch
6. Each worker agent should: fetch problem details, generate 2-3 solution approaches with code in Python/Java/C++/JavaScript/Go using the Anthropic API (set ANTHROPIC_API_KEY env var), validate the JSON, and save to solution_cache.json using the save_solution function from leetcode.py
7. Wait for all workers to complete and report results
8. Update solution_gen_progress.json with completed slugs
9. Report: 'Iteration N complete: X solutions generated this batch, Y total cached, Z remaining'

IMPORTANT: Each worker subagent needs the full context of what to do. When spawning agents, include:
- The problem slug(s) to process
- The LLM prompt template from GENERATE_SOLUTION.md
- Instructions to use leetcode.py functions (fetch_problem, save_solution)
- Instructions to call the Anthropic API with the ANTHROPIC_API_KEY environment variable
- Instructions to validate JSON and handle errors gracefully

Use 10 workers for maximum parallelism. Each worker processes its slugs and saves results directly to solution_cache.json.

Start with batch 1, iteration 1. Work directory: /Users/bytedance/Documents/code/personal/leetcode-bot
