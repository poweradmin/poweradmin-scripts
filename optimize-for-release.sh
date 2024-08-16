#!/bin/sh

composer install --no-dev
composer dump-autoload --optimize
