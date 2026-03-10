# FAQ

## Is BananaWiki ready for production use?

Yes — for a typical self-hosted wiki deployment, BananaWiki is ready to run in production **when it is deployed the way this repository documents**:

- run it with **Gunicorn**, not the Flask development server
- place it behind **HTTPS** with nginx, Caddy, Cloudflare, or another reverse proxy
- keep **backups** enabled and tested
- apply **updates** regularly
- keep server access limited to the people who actually need it

The project already includes production-oriented pieces such as Gunicorn support, reverse-proxy guidance, security headers, CSRF protection, rate limiting, password hashing, safe file handling, and backup/update workflows.

That said, "production-ready" does **not** mean "zero maintenance" or "safe in every environment by default." If you are exposing the wiki to the public internet, storing especially sensitive material, or operating under strict compliance requirements, you should still do the usual operator work: server hardening, HTTPS, monitoring, backups, access reviews, and regular patching.

See also:

- [Deployment guide](deployment.md)
- [Configuration reference](configuration.md)
- [Update guide](updates.md)
- [Architecture overview](architecture.md)

## What about safety?

BananaWiki includes several important baseline protections:

- CSRF protection on forms and AJAX mutations
- Markdown sanitisation with Bleach
- rate limiting for login and mutation endpoints
- secure session cookie settings
- security headers on responses
- password hashing via Werkzeug
- access controls based on user roles and per-user permissions
- authenticated serving for page attachments and chat attachments

However, no web application should be treated as "automatically safe" just because these controls exist. You should still assume that safety depends on **how you deploy it** and **what you store in it**.

Before using BananaWiki for important data, the main things to review are:

1. **Backups** — make sure you have tested restore procedures, not just backup creation.
2. **TLS / HTTPS** — do not run production traffic over plain HTTP.
3. **Secrets handling** — protect `config.py`, `instance/.secret_key`, the database, and any Telegram backup destination.
4. **Account hygiene** — use strong passwords and limit who gets admin access.
5. **Server hardening** — keep the OS and Python dependencies patched, and restrict network exposure.

If you need a formally audited system, enterprise compliance guarantees, or hardened secret-management workflows, you should evaluate BananaWiki as part of a larger security program rather than assuming the app alone provides that.

## Is BananaWiki quantum resistant or "ready for quantum"?

No special post-quantum cryptography is built into BananaWiki today, and the project should **not** be described as "quantum resistant" in the strict cryptographic sense.

BananaWiki relies on standard, current web security building blocks:

- password hashing provided by Werkzeug
- TLS provided by your reverse proxy / hosting stack
- normal session, CSRF, and access-control protections

That is completely normal for a Flask application in 2026, but it is **not the same thing** as a post-quantum security design.

## Should I worry about quantum attacks now?

For most BananaWiki deployments, **probably not as an immediate priority**.

If you are running a private or internal wiki, the practical priorities today are usually:

1. using HTTPS correctly
2. keeping the server patched
3. enforcing strong passwords and limited admin access
4. keeping tested backups
5. reducing internet exposure when possible

Those measures matter far more right now than trying to retrofit post-quantum cryptography into a small self-hosted wiki.

You should start thinking harder about post-quantum planning **now** only if one or more of these are true:

- you store data that must remain confidential for many years
- you expect nation-state-level adversaries
- you have regulatory or customer requirements around post-quantum migration
- you are choosing a reverse proxy, TLS terminator, VPN, or identity provider and want to pick options that can adopt post-quantum standards over time

In other words: for most operators, the right answer is **be aware of the topic, but do not let it distract you from ordinary web security basics**.

## What should I do right now before going live?

Use this short checklist:

- deploy with **Gunicorn** and a reverse proxy
- enable **HTTPS**
- keep BananaWiki and the host OS **updated**
- protect backups and test **restore**
- review who has **admin** access
- keep the instance private unless you intentionally want it internet-facing
- avoid storing extremely sensitive long-term secrets unless you accept the operational risk

If you follow those basics, you will usually get much more practical security value than you would from worrying about quantum resistance today.
