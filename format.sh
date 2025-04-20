#!/bin/bash

composer install
composer format:all
composer install --no-dev
./scripts/optimize-for-release.sh
