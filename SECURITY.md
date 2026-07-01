# Security Policy

## Scope

RobinhoodTrader stores Robinhood OAuth tokens encrypted at rest and communicates with the Anthropic API and Robinhood MCP. Security issues in these areas are taken seriously.

In scope:
- OAuth token storage or exposure
- Authentication bypass (dashboard Basic Auth)
- Guardrail bypass that could cause unintended trades
- Dependency vulnerabilities with a realistic exploit path
- CSRF or injection issues in the web UI or API

Out of scope:
- Issues that require physical access to the machine running the agent
- Issues in Robinhood's or Anthropic's own infrastructure

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **mandar4tech@gmail.com** with:
- A description of the vulnerability
- Steps to reproduce or a proof of concept
- The potential impact (what an attacker could do)

You will receive a response within 72 hours. If the issue is confirmed, a fix will be prioritised and you will be credited in the changelog unless you prefer to remain anonymous.

## Supported versions

Only the latest commit on `main` is supported. There are no versioned releases at this time.
