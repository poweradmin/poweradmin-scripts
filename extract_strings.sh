#!/bin/sh
YEAR=$(date "+%Y")
VERSION=$(cat ../lib/Version.php | grep VERSION | cut -d "'" -f2)

cd ..
# extract strings from php files
find . -name "*.php" | \
	xargs xgettext \
		--no-wrap \
		-L PHP \
		--copyright-holder="Poweradmin Development Team" \
		--msgid-bugs-address="edmondas@girkantas.lt" \
		-o locale/i18n-template-php.pot \
		--package-name=Poweradmin \
		--package-version="$VERSION" \
&& sed -i -e 's/SOME DESCRIPTIVE TITLE/Poweradmin translation/' locale/i18n-template-php.pot \
&& sed -i -e 's/Language: /Language: en_EN/' locale/i18n-template-php.pot \
&& sed -i -e 's/PACKAGE/Poweradmin/' locale/i18n-template-php.pot \
&& sed -i -e 's/(C) YEAR/(C) '"$YEAR"'/' locale/i18n-template-php.pot \
&& sed -i -e 's/CHARSET/UTF-8/' locale/i18n-template-php.pot

# extract strings from database structure
cat install/database-structure.inc.php | grep "array([0-9]" | \
	awk -F\' '{ print "msgid \""$4"\"\nmsgstr \"\"\n"; }' >>locale/i18n-template-db.pot
