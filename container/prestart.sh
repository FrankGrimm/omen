#! /usr/bin/env bash
set -e

# this file is automatically run when starting the
# Dockerfile.prod version of the OMEN build.

# give dependencies a chance to start
sleep 5;

# make sure the database schema is up to date
cd /home/omenuser/app/
echo "prestart: db upgrade"
flask db upgrade 2>&1
echo "prestart complete"
