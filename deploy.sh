#!/bin/bash
set -e
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
PROJECT=taxi-log-app-494917
IMAGE=us-central1-docker.pkg.dev/$PROJECT/taxilog/app

# Load secrets from .env.deploy (not committed to git)
if [ ! -f .env.deploy ]; then
  echo "ERROR: .env.deploy not found. Copy .env.deploy.example and fill in values."
  exit 1
fi
source .env.deploy

gcloud builds submit --tag $IMAGE --project $PROJECT && \
gcloud run deploy taxilog \
  --image $IMAGE \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},SECRET_KEY=${SECRET_KEY},ADMIN_SECRET=${ADMIN_SECRET},GOOGLE_MAPS_KEY=${GOOGLE_MAPS_KEY},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" \
  --memory 512Mi \
  --project $PROJECT
