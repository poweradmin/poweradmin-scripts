#!/bin/sh

msgfmt 2>/dev/null

if [ "$?" = "127" ]
then
	echo "Error: can't find <msgfmt> executable!"
	exit
fi

# get list of available locales, excluding template
dirs=$(find ../locale -maxdepth 1 -type d ! -name 'pot' -exec basename {} \; | tail -n +2)

# update every messages.mo for every locale
for locale in $dirs; do
	echo "Updating $locale locale"

  msgfmt -v -C ../locale/"$locale"/LC_MESSAGES/messages.po
  msgfmt ../locale/"$locale"/LC_MESSAGES/messages.po -o ../locale/"$locale"/LC_MESSAGES/messages.mo
done
