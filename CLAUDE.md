# Working rules

These apply to every task in this repository.

## Before writing code

1. **Look first.** Read 2–3 files next to where the change belongs. Match their
   naming, their error handling, their test style. You are joining a codebase,
   not starting one.
2. **State a budget** in one line before the first edit:
   > `products.controller.ts` (+15), `products.routes.ts` (+1), one test (+35). ~50 lines.
3. **Over 150 lines or 3 new files → stop and ask.** A change that size is a
   design decision, and design decisions belong to the human.
4. **If the task does not fit this repo** — wrong language, missing framework,
   no such subsystem — say so and stop. Do not build the missing part uninvited.

## While writing

- **Edit before create.** A new file needs a reason you can say out loud.
- **No abstraction until the second caller.** No interface with one
  implementation. No wrapper around a single call. No option nobody passes.
  No "we might need this later."
- **Solve the case asked for**, not the general case.
- **Comments explain why, not what.** Code needing a paragraph should be
  rewritten instead.
- Use the errors, helpers and utilities the repo already has.

## Tests

- Cover exactly the cases the task names, at **one** level.
- Use the existing framework, helpers and fixtures.
- Never test the same behaviour twice at two layers.

## Before saying "done"

Run the repo's own checks and paste the real output. Then report:
files changed · lines added · assumptions made · what you left out.

Never claim a check passed without running it.

## The bar

A reviewer should read the whole diff in five minutes and hold it in their head.
If they cannot, it is too big — even if every line is correct.
