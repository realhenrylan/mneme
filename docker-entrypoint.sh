#!/usr/bin/env bash
# Docker entrypoint wrapper for Mneme.
#
# Problem: When using a bind mount (./models:/app/models), Docker creates
# an empty host directory on first run, which shadows the pre-downloaded
# model inside the image at /app/models.  This causes the application to
# re-download the model on every fresh deployment.
#
# Solution: Before starting the application, check if the mounted
# /app/models directory is empty and, if so, copy the image-bundled
# model from the backup location (/app/models-image) into it.
set -euo pipefail

MODELS_DIR="/app/models"
MODELS_IMAGE_DIR="/app/models-image"

# Restore pre-downloaded models if the mounted volume is empty
# but the image-bundled backup exists.
if [ -d "$MODELS_IMAGE_DIR" ] && [ -z "$(ls -A "$MODELS_DIR" 2>/dev/null)" ]; then
    echo "Restoring pre-downloaded models from image to mounted volume..."
    cp -a "$MODELS_IMAGE_DIR/." "$MODELS_DIR/"
    echo "Models restored successfully."
fi

# Execute the main container command
exec "$@"
