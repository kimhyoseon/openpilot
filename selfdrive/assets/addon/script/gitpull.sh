#!/usr/bin/bash

export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
export HOME=/data/data/com.termux/files/home
export PATH=/usr/local/bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/sbin:/data/data/com.termux/files/usr/bin/applets:/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin/python
export PYTHONPATH=/data/openpilot
export GIT_TERMINAL_PROMPT=0

cd /data/openpilot

REMOVED_BRANCH=$(git branch -vv | grep ': gone]' | awk '{print $1}')
if [ "$REMOVED_BRANCH" != "" ]; then
  if [ "$REMOVED_BRANCH" == "*" ]; then
    REMOVED_BRANCH=$(git branch -vv | grep ': gone]' | awk '{print $2}')
  fi
  git remote prune origin --dry-run
  echo $REMOVED_BRANCH | xargs git branch -D
  sed -i "/$REMOVED_BRANCH/d" .git/config
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
HASH=$(git rev-parse HEAD)

if [ "$BRANCH" == "HEAD" ]; then
  echo -n "DETACHED_HEAD" > /data/params/d/GitCommitRemote
  exit 1
fi

if ! /data/data/com.termux/files/usr/bin/git fetch origin "$BRANCH:refs/remotes/origin/$BRANCH"; then
  echo -n "FETCH_FAIL" > /data/params/d/GitCommitRemote
  exit 1
fi

REMOTE_HASH=$(git rev-parse --verify "origin/$BRANCH")
echo -n "$REMOTE_HASH" > /data/params/d/GitCommitRemote

if ! /data/data/com.termux/files/usr/bin/git pull origin "$BRANCH"; then
  exit 1
fi

if [ "$HASH" != "$REMOTE_HASH" ]; then
  touch /data/opkr_compiling
  sleep 1
  reboot
fi
