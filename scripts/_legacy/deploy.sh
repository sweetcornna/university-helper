#!/bin/bash
set -e

echo "=== Deployment Script ==="

# Configuration
ENVIRONMENT=${1:-production}
BACKUP_DIR="./backups"

echo "Deploying to: $ENVIRONMENT"

# Create backup before deployment
echo "Creating backup..."
./scripts/backup.sh

# Pull latest changes
if [ -d .git ]; then
    echo "Pulling latest changes..."
    git pull origin main
fi

# Update environment file
if [ -f ".env.$ENVIRONMENT" ]; then
    echo "Using environment-specific configuration..."
    cp ".env.$ENVIRONMENT" .env
fi

# Pull latest images
echo "Pulling latest Docker images..."
docker-compose pull

# Build new images
echo "Building containers..."
docker-compose build --no-cache

# Stop old containers
echo "Stopping old containers..."
docker-compose down

# Start new containers
echo "Starting new containers..."
docker-compose up -d

# Wait for services
echo "Waiting for services to start..."
sleep 10

# Run database migrations
echo "Running database migrations..."
docker-compose exec -T backend alembic upgrade head

# Health check
echo "Running health check..."
for i in {1..30}; do
    if curl -f http://localhost/health >/dev/null 2>&1; then
        echo "Health check passed!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "Health check failed after 30 attempts"
        echo "Rolling back..."
        docker-compose down
        exit 1
    fi
    echo "Waiting for services... ($i/30)"
    sleep 2
done

# Clean up old images
echo "Cleaning up old Docker images..."
docker image prune -f

echo ""
echo "=== Deployment Complete ==="
echo "Application is running at http://localhost"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To rollback: restore from $BACKUP_DIR"
