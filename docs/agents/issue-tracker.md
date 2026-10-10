# Issue tracker: GitHub

Issues and specs for this repo live in GitHub Issues for
`nkurnia1031/dockter_bot_tdl`. Use the `gh` CLI from this clone.

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --json number,title,body,labels,comments`
- List: `gh issue list --state open --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body "..."`
- Apply/remove labels: `gh issue edit <number> --add-label "<label>"` /
  `--remove-label "<label>"`
- Close: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** External PRs are not included in issue triage
unless this setting is deliberately changed.

GitHub shares issue and PR numbers. Resolve a bare `#42` by checking
`gh pr view 42` first, then `gh issue view 42`.

## Publishing and fetching

When a skill says to publish work to the issue tracker, create a GitHub issue.
When it says to fetch a ticket, read it with `gh issue view`.

## Wayfinding operations

- Use one issue labelled `wayfinder:map` as the map, with child issues as tickets.
- Link children as GitHub sub-issues when available; otherwise include them in
  the map task list and put `Part of #<map>` at the top of each child.
- Use native GitHub issue dependencies for blockers. If unavailable, record
  `Blocked by: #<n>` in the issue body.
- The frontier is the first open, unassigned child without open blockers, in
  map order.
- Claim with `gh issue edit <n> --add-assignee @me`.
- Resolve by commenting with the answer, closing the issue, then adding a
  context pointer to the map's Decisions-so-far.
