#!/bin/bash

composer install
composer format:lib
composer install --no-dev
./scripts/optimize-for-release.sh
