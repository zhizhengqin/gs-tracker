#!/bin/bash
BACKUP_DIR="/opt/backups/gs-tracker"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

cd /opt/gs-tracker || exit 1
tar czf "$BACKUP_DIR/gs-tracker-backup-$DATE.tar.gz" data/ output/reports/ .env deploy/

# Keep last 30 days
find "$BACKUP_DIR" -name "gs-tracker-backup-*.tar.gz" -mtime +30 -delete

echo "Backup created: $BACKUP_DIR/gs-tracker-backup-$DATE.tar.gz"
