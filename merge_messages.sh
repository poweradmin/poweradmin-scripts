#!/bin/sh

result=`msgmerge 2>/dev/null`

if [ "$?" = "127" ]
then
	echo "Error: can't find <msgmerge> executable!"
	exit
fi

# get list of available locales, excluding template
dirs=`ls ../locale | grep -v pot`

# update every messages.mo for every locale
for locale in $dirs; do
	echo "Updating $locale locale"

	cd ../locale/$locale/LC_MESSAGES

  msgmerge --backup=none -N -U messages.po ../../i18n-template-php.pot

	cd ../../
done 
