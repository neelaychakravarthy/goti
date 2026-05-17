# Security policy

## Reporting a vulnerability

If you discover a security issue in Goti, please report it privately
rather than opening a public issue. Email:

**nkchakra2@gmail.com**

We aim to respond within 72 hours and ship a fix within 14 days of
confirmation. Severe issues get faster turnaround.

When reporting, please include:

- A description of the issue
- Steps to reproduce (ideally a minimal repro)
- The affected version / commit hash
- Your assessment of severity + impact

## Scope

In-scope for security reports:

- Authentication / authorization bypass (Google OAuth, Actionbook OAuth)
- Data exposure across user boundaries (cross-tenant leaks)
- Remote code execution via any external integration surface
- Token / secret exfiltration paths

Out of scope:

- Issues with upstream APIs themselves (report to the upstream vendor)
- Rate-limit bypass via legitimate authenticated traffic
- Self-XSS in inputs where the user is the only victim
- Theoretical issues without a working repro

## Disclosure

After a fix lands, we publish a brief advisory in `CHANGELOG.md`
crediting the reporter (unless they prefer to stay anonymous).
