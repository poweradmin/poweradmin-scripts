#!/bin/bash

# Download the file to data directory
wget -O data/public_suffix_list.dat https://publicsuffix.org/list/public_suffix_list.dat

# Add and commit the file
git add data/public_suffix_list.dat
git commit -m "chore: update public_suffix_list.dat" data/public_suffix_list.dat
