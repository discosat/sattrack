#!/bin/bash

if [ -z "$1" ] 
    then
        echo "No argument supplied"
        exit 1
fi

# URL to fetch the TLE data
TLE_URL="https://celestrak.org/NORAD/elements/gp.php?NAME=$(echo $1 | sed 's/ /%20/g')&FORMAT=TLE"

# Fetch the TLE data and store it in a variable
TLE_DATA=$(curl -s "$TLE_URL")

ACTUAL_NAME=$1
NAME_LENGTH=$(echo -n "$ACTUAL_NAME" | wc -m)

# Check if first line matches the name provided
RECV_SAT_NAME=`echo "${TLE_DATA}" | head -1`
RECV_SAT_NAME="${RECV_SAT_NAME:0:$NAME_LENGTH}"

if [[ "$RECV_SAT_NAME" != "$ACTUAL_NAME" ]]; then
    echo "WARNING: The received satellite name does not match the provided name. Updating anyway"
fi

# Check if we got data - Tightly coupled with celestrak
if [[ "$TLE_DATA" = "No GP data found" ]]; then
    echo "No data found, TLE update was unsuccessful"
    exit 1
fi

# Write the TLE data to the file "disco.tle"
SCRIPT_DIR=$(dirname "$0")
echo "$TLE_DATA" > "$SCRIPT_DIR/app/config/disco.tle"
echo "Successfully updated TLE data for $1"
