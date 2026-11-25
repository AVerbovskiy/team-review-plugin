# Team context sources

The team-brief builder reads this file, fetches every source listed here, condenses them into a team brief and
caches the result in `~/.cache/team-review/team-briefs/`. The cache is rebuilt when this file changes, when it is
older than 7 days, or when `--refresh-context` is passed.

Save a filled-in copy as `.claude/team-context.md` in a repository (shared with the team through git), or as
`~/.config/team-review/team-context.md` (personal, used in every repository that has no file of its own).
Every section is optional; delete what does not apply.

## Team

- Name: <team name>
- Domain: <one or two sentences on what the team owns>

## Default stack

Used when a repository has no `.claude/team-review.md` stating its stack.

- Languages: <e.g. TypeScript>
- Frameworks: <e.g. NestJS>
- Architecture: <e.g. event-driven services>
- Data: <e.g. PostgreSQL>

## Repositories

One per line: `owner/repo` — what it is — optional local path — optional files to read
(default: README.md, CLAUDE.md, docs/).

- <owner/repo> — <what it is> — (no local path) — README.md, CLAUDE.md, docs/

## Confluence pages

One per line: URL or page ID — why it matters for reviews. Needs the Atlassian connector in Claude.

- <https://your-site.atlassian.net/wiki/spaces/XYZ/pages/123/Code+Review> — the team's code review guidelines
- <https://your-site.atlassian.net/wiki/spaces/XYZ/pages/456/Definition+of+Ready> — what a ticket must contain

## Working agreements (inline)

Anything the team expects in review that is not written down elsewhere. Add bullets here.

- <e.g. A PR is small and has a single purpose.>
