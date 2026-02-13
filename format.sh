#!/bin/bash

composer install
chmod +x vendor/bin/*

# Run phpcbf directly: exit code 0 = fixes applied, 1 = errors, 2 = nothing to fix
vendor/bin/phpcbf --standard=phpcs.xml addons config index.php install lib tests dynamic_update.php
exit_code=$?
if [ $exit_code -eq 1 ]; then
    echo "phpcbf encountered errors"
    exit 1
fi

composer install --no-dev
./scripts/optimize-for-release.sh
git checkout -- vendor/composer/installed.php
