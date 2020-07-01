#!/bin/bash
set -e

declare QUOTE_JSON
QUOTE_JSON="https://raw.githubusercontent.com/mubaris/motivate/master/motivate/data_unique/unique_quotes.json"
wget "$QUOTE_JSON" -O "quotes.json"
jq ".data[] | [.quote, .author] | @csv" "quotes.json" > "quotes.csv"

