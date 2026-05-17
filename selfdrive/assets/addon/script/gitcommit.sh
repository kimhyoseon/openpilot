#!/usr/bin/bash

export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
export HOME=/data/data/com.termux/files/home
export PATH=/usr/local/bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/sbin:/data/data/com.termux/files/usr/bin/applets:/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin/python
export PYTHONPATH=/data/openpilot
export GIT_TERMINAL_PROMPT=0

# acquire git hash from remote
cd /data/openpilot

/data/openpilot/selfdrive/assets/addon/script/git_remove.sh

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
LOCAL_HASH=$(git rev-parse HEAD)
echo -n "$LOCAL_HASH" > /data/params/d/GitCommit

if [ "$CURRENT_BRANCH" == "HEAD" ]; then
  echo -n "DETACHED_HEAD" > /data/params/d/GitCommitRemote
  exit 1
fi

if /data/data/com.termux/files/usr/bin/git fetch origin "$CURRENT_BRANCH:refs/remotes/origin/$CURRENT_BRANCH"; then
  REMOTE_HASH=$(git rev-parse --verify "origin/$CURRENT_BRANCH")
  echo -n "$REMOTE_HASH" > /data/params/d/GitCommitRemote
  if [ "$LOCAL_HASH" != "$REMOTE_HASH" ]; then
    wget --timeout=10 --tries=1 https://raw.githubusercontent.com/openpilotkr/openpilot/$CURRENT_BRANCH/OPKR_Updates.txt -O /data/OPKR_Updates.txt || rm -f /data/OPKR_Updates.txt
  elif [ -f "/data/OPKR_Updates.txt" ]; then
    rm -f /data/OPKR_Updates.txt
  fi
else
  echo -n "FETCH_FAIL" > /data/params/d/GitCommitRemote
  exit 1
fi
