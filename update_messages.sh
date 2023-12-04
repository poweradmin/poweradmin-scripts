#!/bin/sh

result=`msgfmt 2>/dev/null`

if [ "$?" = "127" ]
then
	echo "Error: can't find <msgfmt> executable!"
	exit
fi

# get list of available locales, excluding english
dirs=`ls ../locale | grep -v pot`

# update every messages.mo for every locale
for locale in $dirs; do
	echo "Updating $locale locale"

	cd ../locale/$locale/LC_MESSAGES

	msgfmt -c messages.po
	msgfmt messages.po -o messages.mo

	cd ../../
done 
