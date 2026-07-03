# Backup and Restore Runbook

E0 establishes PostgreSQL as the production state store while preserving SQLite
for local-first development.

## Targets

- RPO: <= 5 minutes.
- RTO: <= 30 minutes.

## Local PostgreSQL Stack

Start the local PostgreSQL service when validating production-profile storage:

```bash
docker compose -f infrastructure/docker-compose.yml --profile postgres up -d postgres
```

Use this URL from containers on the Compose network:

```env
DATABASE_URL=postgresql://autodev:autodev@postgres:5432/autodev
```

Use this URL from the host:

```env
DATABASE_URL=postgresql://autodev:autodev@localhost:5432/autodev
```

## Backup

Run logical backups at least every five minutes in production:

```bash
pg_dump "$DATABASE_URL" --format=custom --file "autodev-$(date +%Y%m%d%H%M%S).dump"
```

Store backup artifacts outside the database host and verify retention policies
match the deployment's compliance requirements.

## Restore

Restore into a clean database:

```bash
createdb "$RESTORE_DATABASE_NAME"
pg_restore --dbname "$RESTORE_DATABASE_URL" --clean --if-exists autodev.dump
```

After restore, run the backend health check and a session/run listing smoke test.
