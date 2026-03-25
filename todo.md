# LeetCode Bot — Feature Todo

Track iterative development. Each feature is broken into sub-tasks.
Mark with [x] when done, [-] when in-progress, [ ] when pending.

---

## Feature 1: Fix /problems multi-word tag search

**Problem**: `/problems Dynamic Programming` splits into 2 separate tags `["dynamic", "programming"]`
instead of the single slug `dynamic-programming`. Also, difficulty ordering is confusing for users.

### Sub-tasks
- [ ] 1a. Parse raw message text using `shlex.split()` to support quoted tags
      e.g. `/problems "dynamic programming" easy` → tags=["dynamic-programming"], difficulty=EASY
- [ ] 1b. Auto-convert spaces-to-hyphens within quoted strings (LeetCode uses kebab-case slugs)
- [ ] 1c. Update help text to show correct usage: `/problems [easy|medium|hard] [tag]`
      with example: `/problems easy "dynamic programming"` or `/problems easy dynamic-programming`

---

## Feature 2: /problems problem title as clickable /problem command

**Problem**: Problem titles in `/problems` link to LeetCode website, but users want to click
and see bot's `/problem <slug>` details (to iterate through the list without leaving the bot).

### Sub-tasks
- [ ] 2a. Store bot username at startup (via `app.bot.username` in `post_init`)
- [ ] 2b. Generate deep links `https://t.me/{bot_username}?start=problem_{slug}` for each problem
- [ ] 2c. Update `format_problems()` to accept optional `bot_username` param; use deep link when available
- [ ] 2d. Update `cmd_start` to parse `start=problem_{slug}` payload and show problem detail
- [ ] 2e. Pass `bot_username` through from `cmd_problems` and `cmd_problems_page`

---

## Feature 3: Improve /problem detail formatting

**Problem**: Multiple formatting issues in `/problem` output:
- Inline code backticks get escaped and don't render as monospace
- Examples have many line breaks; blockquote format would be cleaner
- Constraints not in bullet point format
- Hints not hidden (should use Telegram spoiler `||text||`)
- Too many unnecessary blank lines

### Sub-tasks
- [ ] 3a. Fix inline code: process HTML→MarkdownV2 without escaping code content
      - Parse `<code>` tags separately; wrap content in `` ` `` without escaping inner text
      - Parse `<pre>` blocks → triple backtick code blocks
- [ ] 3b. Format examples as blockquotes: prefix each line with `> `
      - Extract examples from content HTML `<pre>` blocks
      - Apply `> ` prefix to each line
- [ ] 3c. Format constraints as bullet points
      - Parse `<ul><li>` lists from content HTML
      - Render as `• constraint` lines
- [ ] 3d. Format hints as spoiler text
      - Change hints rendering from `• hint` to `||hint||` (Telegram spoiler)
- [ ] 3e. Reduce unnecessary blank lines and tighten overall layout
- [ ] 3f. Parse HTML content more robustly (handle `<p>`, `<ul>`, `<li>`, `<strong>`, `<em>`)

---

## Feature 4: Research - Problem images

**Problem**: Some LeetCode problems include images (e.g. tree diagrams). Does the API return image URLs?

### Sub-tasks
- [ ] 4a. Research: Are image URLs embedded in problem `content` HTML as `<img src="...">` tags?
- [ ] 4b. If yes: Extract image URLs from HTML content; send as separate media messages
- [ ] 4c. Research: Are LeetCode's image URLs public/accessible without auth?
- [ ] 4d. Decision: Implement or skip based on findings

**Status**: Research needed

---

## Feature 5: Research - Solutions API + /solution command

**Problem**: Users want to see solutions for problems via `/solution <slug> <language>`.

### Sub-tasks
- [ ] 5a. Research: Does LeetCode GraphQL have a public community solutions endpoint?
- [ ] 5b. Research: What authentication is required for solutions API?
- [ ] 5c. If public API exists: Add `SOLUTIONS_QUERY` to config.py
- [ ] 5d. If public API exists: Implement `fetch_solutions(slug, language)` in leetcode.py
- [ ] 5e. If public API exists: Implement `format_solution()` in formatter.py
- [ ] 5f. If public API exists: Add `/solution <slug> [language]` command to bot.py
- [ ] 5g. If public API exists: Add to help text and register handler

**Status**: Research needed

---

## Completed Features

- [x] Basic user tracking (/add_user, /remove_user, /users)
- [x] Daily progress (/daily) with submissions-based counting
- [x] Weekly progress (/weekly) with sparkline chart
- [x] Leaderboard (/summary) with daily + weekly ranking
- [x] Auto-summary scheduling (/interval)
- [x] Problem browsing (/problems) with difficulty/tag filters
- [x] Problem detail (/problem <slug>)
- [x] Daily challenge (/challenge)
- [x] Pagination for /problems with Prev/Next inline keyboard
- [x] Slug display in /problems list
- [x] Fix unescaped # in problem tags
- [x] Midnight snapshot job for accurate daily counts
