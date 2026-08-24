# Contributing

Kotodama welcomes narrowly scoped issues and pull requests that preserve the
project's evidence and authority boundaries.

## Before proposing a change

1. Read `README.md`, `STATUS.md`, and the documentation for the surface you are
   changing.
2. Keep source evidence, proposals, decisions, execution authority,
   verification receipts, promotion, and Current Truth distinct.
3. Do not add secrets, private identifiers, participant data, audio,
   transcripts, private absolute paths, or private source bodies.
4. Add or update a negative test for any security or authority boundary.

## Local checks

Use Python 3.12 and run the tracked credential gate before installing
dependencies:

```text
python -S -B tools/check_tracked_secret_hygiene.py
python -S -B tools/check_workflow_references.py
python -m pip install --require-hashes -r requirements-ci.txt
python -m unittest discover -s tests -v
```

The credential gate examines the current Git-tracked tree and reports only a
path, line number, and detector name. It does not print a detected value. A
passing result does not replace provider-side secret scanning, push protection,
or a historical repository scan.

`requirements-test.txt` is the small human-edited input. The generated
`requirements-ci.txt` locks its complete transitive graph and hashes for
reproducible CI installation. Update both together and include the dependency
audit result in the pull request.

Regenerate the lock with Python 3.12 and `pip-tools==7.6.1`:

```text
pip-compile --generate-hashes --output-file=requirements-ci.txt requirements-test.txt
```

Also run `git diff --check` and confirm the test run leaves the working tree
clean. A passing local suite is local evidence only; it must not be described
as provider, deployment, Public Beta, or Human approval evidence.

## Pull requests

Keep each pull request reviewable, explain the exact claim it changes, list the
checks that were actually run, and call out anything not tested. Do not bundle
provider writes, credential changes, publication, or destructive operations
into a code-only change.
