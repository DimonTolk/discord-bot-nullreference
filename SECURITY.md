# Secrets and private data

Production credentials belong in runtime environment variables or a secret manager.
GitHub Actions secrets are only accessible to workflows that explicitly reference them;
they do not automatically configure the hosting provider.

Never commit `.env`, database exports, Discord interaction payloads, private flavour
exports, connection strings, logs, keys or real server/user configuration.
The bot stores Discord identifiers, game state and audit history in PostgreSQL only.
Do not give third parties access to database backups or production logs.

If a credential is accidentally published, revoke/rotate it immediately and remove it
from repository history. Removing a file in a later commit does not revoke the secret.

Report a security issue privately to the repository owner, without posting live secrets.
