#!/bin/bash

composer install
composer format:lib
composer format:tests
composer install --no-dev
./scripts/optimize-for-release.sh
