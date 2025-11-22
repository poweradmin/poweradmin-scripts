#!/bin/bash

composer install
chmod +x vendor/bin/*
composer format:all
composer install --no-dev
./scripts/optimize-for-release.sh
git checkout -- vendor/composer/installed.php
