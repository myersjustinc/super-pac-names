#!/usr/bin/env python
from copy import deepcopy
from datetime import date
import json
import logging
import os
import re
import requests
import sys
from time import sleep

logging.basicConfig(level=logging.WARNING)

# Useful calendar API constants
NYTCF_API_ENDPOINT = "http://api.nytimes.com/svc/elections/us/v3/finances/2012"
NYTCF_API_METHOD = "/committees/superpacs.json"
NYTCF_API_KEY = os.environ["NYTCF_API_KEY"]  # Get from developer.nytimes.com
NYTCF_API_PARAMS = {
    "api-key": NYTCF_API_KEY,
}

# Error handling
class OutOfRetries(Exception):
    pass

# Thanks: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry
def retry(tries=5, delay=1, factor=2):
    def decorated_retry(f):
        def function_retry(*args, **kwargs):
            tries_left = tries
            current_delay = delay
            
            while tries_left > 0:
                try:
                    return f(*args, **kwargs)  # Attempt decorated function
                except Exception:
                    tries_left -= 1
                    if tries_left > 0:
                        sleep(current_delay)
                        current_delay *= factor
                        logging.warning("Retrying...")
            
            raise OutOfRetries("Ran out of tries")
        
        return function_retry
    
    return decorated_retry

def get_superpac_info():
    items = []
    params = deepcopy(NYTCF_API_PARAMS)
    
    offset = 0
    NEXT_PAGE = True
    while NEXT_PAGE:
        params["offset"] = offset
        
        # Make the request and deserialize it.
        r = requests.get(
            NYTCF_API_ENDPOINT + NYTCF_API_METHOD, params=params
        )
        try:
            response = json.loads(r.text)
        except ValueError:
            logging.error("No page JSON object could be decoded: %s" % r.text)
            response = {"results": []}
        
        # Check whether there are more pages to request.
        if len(response["results"]) == 0:
            NEXT_PAGE = False
            logging.warning("Done!")
        
        full_results = []
        for initial_result in response["results"]:
            r2 = requests.get(
                NYTCF_API_ENDPOINT + initial_result["relative_uri"],
                params=NYTCF_API_PARAMS
            )
            if r2.status_code == 200:
                try:
                    secondary_response = json.loads(r2.text)
                except ValueError:
                    logging.error("No committee JSON object could be decoded: %s" % r2.text)
                    secondary_response = {"results": []}
                full_results.extend(secondary_response["results"])
            else:
                logging.warning("Could not load %s" % initial_result["id"])
                full_results.append(initial_result)
        
        items.extend(full_results)
        logging.warning("%s items added; have %s so far" % (
            len(response["results"]), len(items)
        ))
        offset += 20
    
    today = date.today().strftime("%Y%m%d")
    output_json = open(today + ".json", "w")
    json.dump(items, output_json)
    output_json.close()
    output_names = open(today + "-names.txt", "w")
    output_names.write("\n".join([item["name"] for item in items]))
    output_names.write("\n")
    output_names.close()
    
    return items

def load_superpac_info(date):
    input_filename = date + ".json"
    input_file = open(input_filename, 'r')
    items = json.load(input_file)
    input_file.close()
    return items

def main():
    today = date.today().strftime("%Y%m%d")
    try:
        items = load_superpac_info(today)
    except Exception:
        items = get_superpac_info()
    
    # Load just the names
    original_names = [item["name"] for item in items]
    names = deepcopy(original_names)
    
    # Move articles to the front
    names = [
        (
            "THE " + name.replace("; THE", "").replace(", THE", "")
            if (name.find("; THE") > -1 or name.find(", THE") > -1)
            else name
        ) for name in names
    ]
    
    # Remove punctuation
    names = [
        re.sub(r' +', ' ', re.sub(r'[,()/]', ' ', name)).strip() for name in names
    ]
    
    # Split strings
    by_length = {}
    for i in xrange(len(names)):
        name = names[i]
        original_name = original_names[i]
        
        name_words = name.split(' ')
        word_count = len(name_words)
        for n in xrange(1, word_count):  # Exclude entire name, of course
            ngrams = [
                ' '.join(name_words[x:x + n])
                for x in xrange(word_count - n + 1)
            ]
            
            if n not in by_length:
                by_length[n] = {}
            for ngram in ngrams:
                if ngram not in by_length[n]:
                    by_length[n][ngram] = []
                by_length[n][ngram].append(original_name)
    
    # Remove duplicates
    for n in by_length.keys():
        for ngram in by_length[n].keys():
            by_length[n][ngram] = list(set(by_length[n][ngram]))
            if len(by_length[n][ngram]) == 1:
                del by_length[n][ngram]
        if len(by_length[n]) == 0:
            del by_length[n]
    
    # Sort results
    def item_key(item):
        return len(item[1])
    top_ngrams = {}
    for n in by_length:
        # Sort by number of Super PACs with that fragment, descending
        sorted_results = sorted(
            by_length[n].iteritems(), key=item_key, reverse=True
        )
        # Sort list of Super PACs in reverse chronological order of first
        # filing (i.e., oldest committee first)
        top_ngrams[n] = [{
            "fragment": result[0],
            "names": sorted(result[1], key=original_names.index),
        } for result in sorted_results]
    
    output_json = open(today + '-ngrams.json', 'w')
    json.dump(top_ngrams, output_json)
    output_json.close()
    
    # Put together a file of total receipts by committee name, but only for
    # committees listed in the ngrams file.
    all_receipts = dict([(item["name"], (item["total_receipts"] if "total_receipts" in item else 0)) for item in items])
    specific_receipts = {}
    for n in top_ngrams:
        for ngram in top_ngrams[n]:
            for name in ngram["names"]:
                specific_receipts[name] = all_receipts[name]
    output_receipts_json = open(today + '-receipts.json', 'w')
    json.dump(specific_receipts, output_receipts_json)
    output_receipts_json.close()

if __name__ == '__main__':
    main()
