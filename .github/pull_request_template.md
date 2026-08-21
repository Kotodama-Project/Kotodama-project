## Purpose

<!-- Describe the user-visible or operational problem. Link the authority record, issue, or approved decision that permits this change. -->

## Change summary

<!-- Explain what changed and what intentionally did not change. -->

## Trust-boundary review

- [ ] I identified whether this changes authentication, authorization, public access, billing, deployment, DNS, secrets, personal data, or an external provider.
- [ ] No live credential, session, private locator, customer data, or unredacted production evidence appears in commits, logs, screenshots, comments, or generated files.
- [ ] New inputs and external responses are bounded, validated, and fail closed where a permissive fallback could create security or cost exposure.
- [ ] GitHub Actions use reviewed full commit SHAs rather than mutable tags.
- [ ] Generated/SSOT files were updated through their authoritative generator rather than edited inconsistently by hand.

## Validation

<!-- List the exact commands, checks, and negative tests run on the final commit. -->

- [ ] Required repository tests and static checks pass on the final head.
- [ ] Relevant negative cases were tested, not only the successful path.
- [ ] Dependency and secret-scanning findings were reviewed.
- [ ] The changed-file set contains no unrelated generated or provider-state drift.

## Deployment and external state

- [ ] This change requires no provider/admin action; **or** the required action and accountable operator are linked below.
- [ ] A rollback or disablement path is documented for production-affecting changes.
- [ ] Provider-side settings, deployment revision, branch protection, DNS, billing controls, and secrets will be read back after mutation rather than inferred from the submitted source.
- [ ] Publication, repository transfer, production deployment, or paid capability enablement remains blocked until its explicit human/administrative gate is satisfied.

## Evidence and follow-up

<!-- Link sanitized evidence, deployment/readback issue, and any deliberately deferred work. Do not paste secrets. -->
