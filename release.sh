#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: ./release.sh [patch | minor | major]"
    exit 1
fi

BUMP_TYPE=$1

if [ -n "$(git status --porcelain)" ]; then
    echo "Error: You have uncommitted changes. Please commit them first."
    exit 1
fi

echo "Bumping version ($BUMP_TYPE)..."
uv version --bump "$BUMP_TYPE"

echo "Synchronizing uv.lock..."
uv lock

NEW_VERSION=$(uv version --short)

echo "Creating git commit and tag for $NEW_VERSION..."
git add pyproject.toml uv.lock
git commit -m "bump version to $NEW_VERSION"
git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION"

#echo "Pushing to repo..."
#git push origin main --tags

echo "$NEW_VERSION has been successfully bumped, locked, and tagged!"
