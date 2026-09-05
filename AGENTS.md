# Kotodama contributor and agent entrypoint

This is a thin adapter. Product intent, source, Task state, deployment evidence,
and public access have different owners; do not create another status ledger here.

## Start and resume

1. Read [README.md](README.md), [STATUS.md](STATUS.md), and [ROADMAP.md](ROADMAP.md).
2. Use [the project map](docs/PROJECT-MAP.md) to select the relevant component,
   existing documentation, and PR dependency.
3. Read [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the
   component's instructions before editing.
4. Pin the repository, branch, HEAD, working-tree changes, intended outcome,
   owner, files, and verification boundary. Preserve existing work.
5. If the checkout contains `docs/PROJECT-TASK-OPERATIONS.md` and
   `projects/kotodama-project/`, follow their Task resolver, records, events, and
   restart checkpoint. Reuse the stable Task ID; a session or Markdown summary
   does not own Task state. If those files are absent, do not invent a second
   Task ledger or claim that the pending contract is integrated.

## Work and evidence

- Tie each change to one README outcome and one observable acceptance result.
- Keep source evidence, intent candidates, decisions, work orders, changes,
  verification, promotion, and Current Truth distinct.
- Read PR bodies and relevant changes, then refresh head, base, checks, and
  unresolved review threads. A SHA or CI result embedded in a description may
  belong to a predecessor. An outdated review thread can still be unresolved.
- A PR merged into another development branch is not merged into `main`.
  Respect the existing stack and required independent review.
- Keep one writer per checkout or shared resource. Use an isolated checkout
  for concurrent edits; never reset or move someone else's working tree.
- Private migration sources remain controlled inputs. Migrate one capability
  with provenance and review; do not copy a private repository or its history
  into public Git. Preserve source and deployed fixes until the destination is
  verified and adopted.
- Keep private absolute paths, host identifiers, credentials, conversations,
  audio, and deployment details out of public files and PRs.
- For information sharing, read [the access policy](docs/INFORMATION-ACCESS.md).
  Bind the existing information reference, classification, custodian and explicit
  reader/reviewer identities. Unknown classification never means public. Internal
  IDs and relationship metadata remain private; synthetic examples are labelled.
  Responsibility, read access, review and publication are separate permissions.
- Run checks appropriate to the changed surface and the contribution policy.
  Report what was actually tested; local tests do not prove live operation.
- End with the changed files, verification result, remaining boundary, and next
  action. Update the owning component document and link it from the map only
  when navigation changed; do not append a full history to this file.

The public preview remains `read-only/candidate-only` and
`NO_GO_UNPUBLISHED`. Public Beta access and Final Human GO require their own
candidate-bound evidence and decision.
