#!/bin/bash
set -e

declare QUOTE_JSON
QUOTE_JSON="https://raw.githubusercontent.com/mubaris/motivate/master/motivate/data_unique/unique_quotes.json"
wget "$QUOTE_JSON" -O "quotes.json"

echo 'ID,Quote,Author' > "quotes-2k.csv"
# shellcheck disable=SC2016
jq -r '.data | keys[] as $idx | [$idx, .[$idx].quote, .[$idx].author] | @csv' "quotes.json" >> "quotes-2k.csv"

QUOTE_JSON="https://raw.githubusercontent.com/JamesFT/Database-Quotes-JSON/master/quotes.json"
wget "$QUOTE_JSON" -O "quotes.json"

echo 'ID,Quote,Author' > "quotes-5k.csv"
# shellcheck disable=SC2016
jq -r '. | keys[] as $idx | [$idx, .[$idx].quoteText, .[$idx].quoteAuthor] | @csv' "quotes.json" >> "quotes-5k.csv"
