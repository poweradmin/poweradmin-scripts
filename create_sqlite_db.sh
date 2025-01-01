#!/bin/bash

set -euo pipefail

DB_PATH="../../db"
DB_FILE="powerdns.db"
SQLITE_BIN=sqlite3

# check if directory exists
if [ ! -d $DB_PATH ]
then
	mkdir -p $DB_PATH
fi

# check if db file exists
if [ -e $DB_PATH/$DB_FILE ]
then
	echo "Error: database file <$DB_PATH/$DB_FILE> already exists!"
	exit 1
fi

# import db scheme and data
$SQLITE_BIN $DB_PATH/$DB_FILE < ../sql/pdns/47/schema.sqlite3.sql

# change access rights
chmod 777 $DB_PATH
chmod 666 $DB_PATH/$DB_FILE
