#!/bin/bash
# Test, commit, push, and deploy behind a smoke test.
#
#   ./ship.sh "commit message"     commit what's staged/modified, then ship
#   ./ship.sh                      ship what's already committed (no new commit)
#   ./ship.sh -y "message"         skip the confirmation prompt
#
# The new revision is deployed with NO traffic and smoke-tested on its own URL
# first. Production keeps serving the old revision until those checks pass, so a
# broken build never reaches you or anyone else.

set -euo pipefail
export PATH="$HOME/google-cloud-sdk/bin:$PATH"

PROJECT=taxi-log-app-494917
REGION=us-central1
SERVICE=taxilog
IMAGE=us-central1-docker.pkg.dev/$PROJECT/taxilog/app
TAG=next

ASSUME_YES=0
if [ "${1:-}" = "-y" ]; then ASSUME_YES=1; shift; fi
MESSAGE="${1:-}"

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

# ── 1. preflight ────────────────────────────────────────────────
say "Preflight"
[ -f .env.deploy ] || fail ".env.deploy not found."
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "master" ] || fail "on branch '$BRANCH', not master."

DIRTY=$(git status --porcelain | wc -l)
if [ "$DIRTY" -gt 0 ] && [ -z "$MESSAGE" ]; then
  git status --short
  fail "working tree has changes but no commit message was given."
fi
echo "  branch master, $DIRTY file(s) modified"

# ── 2. tests ────────────────────────────────────────────────────
say "Tests"
python3 -m pytest tests/ -q || fail "tests failed — nothing was committed or deployed."

# ── 3. what's about to happen ───────────────────────────────────
PREV=$(gcloud run services describe $SERVICE --region $REGION --project $PROJECT \
        --format='value(status.traffic[].revisionName)' | head -1)
say "Plan"
[ -n "$MESSAGE" ] && echo "  commit:  $MESSAGE" || echo "  commit:  (nothing to commit)"
echo "  push:    origin master"
echo "  deploy:  new revision with NO traffic, smoke-tested, then promoted"
echo "  current: $PREV  (rollback target)"
if [ "$ASSUME_YES" -eq 0 ]; then
  printf '\nProceed? [y/N] '
  read -r REPLY
  case "$REPLY" in [yY]*) ;; *) echo "aborted."; exit 1 ;; esac
fi

# ── 4. commit and push ──────────────────────────────────────────
if [ -n "$MESSAGE" ]; then
  say "Commit"
  git add -A
  git commit -q -m "$MESSAGE" || fail "commit failed."
  git log --oneline -1
fi
say "Push"
git push origin master

# ── 5. build and deploy with no traffic ─────────────────────────
say "Build"
gcloud builds submit --tag $IMAGE --project $PROJECT || fail "build failed."

say "Deploy (no traffic)"
source .env.deploy
gcloud run deploy $SERVICE \
  --image $IMAGE \
  --region $REGION \
  --project $PROJECT \
  --allow-unauthenticated \
  --memory 512Mi \
  --no-traffic --tag $TAG \
  --set-env-vars "GCS_BUCKET=${GCS_BUCKET},SECRET_KEY=${SECRET_KEY},ADMIN_SECRET=${ADMIN_SECRET},GOOGLE_MAPS_KEY=${GOOGLE_MAPS_KEY},ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" \
  || fail "deploy failed — production untouched, still serving $PREV."

CANARY=$(gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format=json \
  | python3 -c "import json,sys; print(next((t.get('url','') for t in json.load(sys.stdin)['status']['traffic'] if t.get('tag')=='$TAG'), ''))")
[ -n "$CANARY" ] || fail "could not find the '$TAG' URL — production untouched, still serving $PREV."

# ── 6. smoke test the new revision, not production ──────────────
say "Smoke test"
echo "  $CANARY"
check() {  # description, expected-status, curl args...
  local what="$1" want="$2"; shift 2
  local got
  got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$@") || got="000"
  if [ "$got" = "$want" ]; then
    printf '  ok    %-34s %s\n' "$what" "$got"
  else
    printf '  FAIL  %-34s got %s, wanted %s\n' "$what" "$got" "$want"
    return 1
  fi
}

SMOKE_OK=1
check "login page renders"        200 "$CANARY/login"                     || SMOKE_OK=0
check "root redirects to login"   303 "$CANARY/"                          || SMOKE_OK=0
check "parse-pickup needs auth"   401 -X POST "$CANARY/api/parse-pickup" \
        -H 'Content-Type: application/json' -d '{"text":"x"}'             || SMOKE_OK=0
check "unknown path is 404"       404 "$CANARY/nope"                      || SMOKE_OK=0

if [ "$SMOKE_OK" -ne 1 ]; then
  echo
  echo "  The new revision is live at the URL above but has NO traffic."
  echo "  Production is untouched, still serving $PREV."
  echo "  Inspect it, then either promote or delete it:"
  echo "    gcloud run services update-traffic $SERVICE --region $REGION --project $PROJECT --to-latest"
  fail "smoke test failed — not promoted."
fi

# ── 7. promote ──────────────────────────────────────────────────
say "Promote"
gcloud run services update-traffic $SERVICE --region $REGION --project $PROJECT --to-latest -q >/dev/null
NOW=$(gcloud run services describe $SERVICE --region $REGION --project $PROJECT \
       --format='value(status.traffic[].revisionName)' | head -1)
echo "  now serving: $NOW"

say "Shipped"
echo "  rollback:"
echo "    gcloud run services update-traffic $SERVICE --region $REGION \\"
echo "      --project $PROJECT --to-revisions=$PREV=100"
