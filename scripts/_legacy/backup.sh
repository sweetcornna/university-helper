#!/bin/bash
set -e

echo "=== Backup Script ==="

# Configuration
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="backup_$TIMESTAMP"

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "Creating backup: $BACKUP_NAME"

# Backup database
echo "Backing up PostgreSQL database..."
docker-compose exec -T postgres pg_dump -U signin unified_signin > "$BACKUP_DIR/${BACKUP_NAME}_db.sql"

# Backup Redis data
echo "Backing up Redis data..."
docker-compose exec -T redis redis-cli SAVE
docker cp unified-signin-platform-redis-1:/data/dump.rdb "$BACKUP_DIR/${BACKUP_NAME}_redis.rdb" 2>/dev/null || echo "Redis backup skipped"

# Backup environment file
echo "Backing up environment configuration..."
cp .env "$BACKUP_DIR/${BACKUP_NAME}_env" 2>/dev/null || echo ".env not found"

# Create archive
echo "Creating compressed archive..."
tar -czf "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" -C "$BACKUP_DIR" \
    "${BACKUP_NAME}_db.sql" \
    "${BACKUP_NAME}_redis.rdb" \
    "${BACKUP_NAME}_env" 2>/dev/null || true

# Clean up individual files
rm -f "$BACKUP_DIR/${BACKUP_NAME}_db.sql" \
      "$BACKUP_DIR/${BACKUP_NAME}_redis.rdb" \
      "$BACKUP_DIR/${BACKUP_NAME}_env"

# Remove backups older than 30 days
echo "Cleaning up old backups (>30 days)..."
find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +30 -delete

echo ""
echo "=== Backup Complete ==="
echo "Backup saved to: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
echo ""
echo "To restore:"
echo "  1. Extract: tar -xzf $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
echo "  2. Restore DB: docker-compose exec -T postgres psql -U signin unified_signin < ${BACKUP_NAME}_db.sql"
echo "  3. Restore Redis: docker cp ${BACKUP_NAME}_redis.rdb unified-signin-platform-redis-1:/data/dump.rdb"
echo "  4. Restart: docker-compose restart"
