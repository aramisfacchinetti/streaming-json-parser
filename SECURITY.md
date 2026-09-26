# Security Policy

## Supported releases

This project is pre-1.0. Security fixes target the latest published release of
`streaming-json-parser` and the latest published release of
`streaming-json-parser-native`. Older `0.x` releases are not maintained as
separate security branches; fixes may require upgrading, and backports are
considered case by case.

## Reporting a vulnerability

GitHub private vulnerability reporting is currently disabled for this
repository. Until it is enabled, contact the maintainer using the author
contact listed in the [core package's PyPI metadata](https://pypi.org/project/streaming-json-parser/).
Use an initial message to request private coordination; do not post vulnerability
details, exploit inputs, or sensitive data in a public issue or Discussion.

Reports may concern crafted input that causes a crash or resource exhaustion,
a security-relevant validation bypass or strictness discrepancy, or memory
safety problems in the native extension. This list describes relevant report
types; it does not indicate that any such issue is known.

Please include the affected package and version, Python version, operating
system and architecture, parser mode and relevant options, optional backend
versions, a minimal reproducer, expected and actual behavior, and the security
impact. Redact secrets and personal data from payloads, logs, and traces.

This is a small project with no response-time guarantee. The maintainer aims
to acknowledge reports within 14 days when possible. If you receive no
acknowledgment, follow up through the same contact without disclosing details
publicly. After acknowledgment, the maintainer will make a best-effort
assessment of impact and affected releases, but cannot promise a fix schedule
or disclosure date. The reporter and maintainer should coordinate any public
disclosure.
