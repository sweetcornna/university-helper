# Server Deployment Notes

## Current Production Topology

- Domain: `shuake.cornna.xyz`
- Host TLS termination: system Nginx on the server
- Application containers:
  - `easy-learning-app`
  - `easy-learning-nginx`
  - `easy-learning-db`

## Active Local Ports

- App container exposed on `127.0.0.1:8002`
- Frontend/Nginx container exposed on `0.0.0.0:18082`
- System Nginx proxies `shuake.cornna.xyz` to `127.0.0.1:18082`

## Migration State

- `users` table has been migrated from the legacy database into the new database
- Verified counts:
  - new `users`: `38`
  - old `users`: `38`
- Verified public tables on both sides:
  - `course_task_history`
  - `course_task_store`
  - `users`

## Legacy Backup

- Backup file created on server:
  - `/opt/easy_learning/backups/shuake-main_db-20260331-131733.sql.gz`

## Legacy Resources

- Removed:
  - old app container `shuake-easy-learning-app`
  - old DB container `shuake-easy-learning-db`

- Retained:
  - legacy volume `easy_learning_shuake-postgres-data`

The legacy volume is intentionally kept as the final rollback point.

## Automation

Server-side cutover helper:

- [server_finalize_shuake_cutover.sh](/Users/cornna/project/university-helper/university-helper/scripts/server_finalize_shuake_cutover.sh)
- [hotfix_publish.sh](/Users/cornna/project/university-helper/university-helper/scripts/hotfix_publish.sh)

This script covers:

- legacy DB backup
- `users` table migration
- host Nginx cutover
- legacy app cleanup
- optional legacy DB container removal

Hotfix helper covers:

- syncing a small set of changed files
- hot-updating backend Python files into the running app container
- rebuilding only the frontend Nginx container when needed
- app health verification after publish
