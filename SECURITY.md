# Security policy

Kotodama is an incomplete public preview. Do not include credentials, private
infrastructure identifiers, participant data, audio, transcripts, private
source bodies, or exploit details in a public issue or pull request.

## Reporting a vulnerability

Use a private GitHub Security Advisory through the repository's
**Security → Report a vulnerability** action. Do not open a public issue with
vulnerability details. If private vulnerability reporting is unavailable, open
only a minimal issue that contains no sensitive details and asks a maintainer
to establish a private reporting channel.

Include only the affected revision, component, impact category, a safe way to
reproduce the problem, and sanitized logs or screenshots. Maintainers may
request additional evidence through the private channel. Never paste a live
secret; revoke or rotate the secret before history cleanup.

## Credential hygiene

Store provider tokens and private keys only in a local environment or an
approved provider/GitHub secret store. Local `.env`, private-key, and common
credential files are ignored by the repository, but ignore rules are not a
security boundary.

Before every push, run:

```text
python -S -B tools/check_tracked_secret_hygiene.py
```

The command scans the current tracked tree with deterministic high-confidence
detectors and never prints a detected value. It does not scan Git history,
untracked files, provider configuration, or GitHub security settings. If a
secret has ever been committed, revoke or rotate it first and treat historical
removal as a separately reviewed incident-response change.
A deleted file or rewritten commit does not invalidate a credential.

## Supported surface

Security reports are accepted for the current default branch and active pull
requests. Documentation, schemas, validators, and runtime artifacts in this
repository are candidate-only unless their own evidence says otherwise. A
local validation pass does not prove a deployed service or Public Beta.
