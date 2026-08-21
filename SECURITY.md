# Security policy

Kotodama is an incomplete public preview. Do not include credentials, private
infrastructure identifiers, participant data, audio, transcripts, private
source bodies, or exploit details in a public issue or pull request.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting flow when the repository exposes
the **Security → Report a vulnerability** action. If that action is not
available, open a minimal issue that contains no sensitive details and asks a
maintainer to establish a private reporting channel.

Include only the affected revision, component, impact category, and a safe way
to reproduce the problem. Maintainers may request additional evidence through
the private channel. Never paste a live secret; revoke or rotate it first.

## Supported surface

Security reports are accepted for the current default branch and active pull
requests. Documentation, schemas, validators, and runtime artifacts in this
repository are candidate-only unless their own evidence says otherwise. A
local validation pass does not prove a deployed service or Public Beta.
