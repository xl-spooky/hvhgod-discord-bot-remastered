set -eu

echo "** Pulling changes from remote"
git pull

echo "** Building Docker Container"
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
COMMIT_HASH=$(git rev-parse --short HEAD)
export GIT_REVISION="$BRANCH_NAME/$COMMIT_HASH"

echo " * Revision: $GIT_REVISION"
docker compose build

echo "** Running Docker Container"
docker compose up -d bot
