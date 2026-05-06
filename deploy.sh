#!/bin/bash
set -e
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
PROJECT=taxi-log-app-494917
IMAGE=us-central1-docker.pkg.dev/$PROJECT/taxilog/app

gcloud builds submit --tag $IMAGE --project $PROJECT && \
gcloud run deploy taxilog \
  --image $IMAGE \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=taxilog-data-genetownsend \
  --memory 512Mi \
  --project $PROJECT
