# Security Policy

## Supported scope

This repository is currently intended for:

- Local-first personal deployments on `localhost`
- Small self-hosted experiments
- Developer tooling and orchestration workflows

Hosted multi-user deployments should be treated as advanced setups and reviewed carefully before production use.

## Reporting a vulnerability

Please do not open a public GitHub issue for security-sensitive reports.

Instead, contact the maintainer privately with:

- A short description of the issue
- Reproduction steps
- Expected impact
- Any suggested mitigation

If you already know the affected routes, files, or configuration, include them too.

## Current trust model

Local mode is intentionally optimized for developer ergonomics:

- No bearer token is required on `localhost`
- Agent identity is explicit by name, not by secret
- The dashboard auto-authenticates as the local operator

That means local mode should only be used on trusted machines and trusted local networks.

If you want remote access or stronger authentication, disable local mode and use the hosted bearer-token flow instead.
