See AGENTS.md. It is the single agent guide for this repo.

## Coding guidelines (Karpathy)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Reel-Watcher Model and Engineering Workflow

### Model responsibilities

- Use Fable or Opus for architecture, planning, complex debugging and independent reviews.
- Use Sonnet for implementation, tests, routine bug fixes and refactoring.
- Never implement a feature before its plan is approved.

### Engineering rules

- Read the existing implementation before proposing changes.
- Preserve existing functionality.
- Work on isolated Git branches.
- Never modify the default branch directly.
- Never silently delete user data.
- Run relevant tests and report actual results.
- Do not claim physical Android testing when only cloud tests were performed.
- Create pull requests; do not merge without approval.
- Prefer minimal, incremental changes over rewrites.

### Project constraints

- Local-first AI processing.
- No mandatory paid APIs.
- No mandatory cloud LLM.
- No hardcoded or bundled API keys. Optional user-entered API keys for existing integrations are permitted.
- Preserve user privacy and explicit media permissions.
- Keep temporary media cleanup reliable.
- Maintain compatibility with the existing Android application.
