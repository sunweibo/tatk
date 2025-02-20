"""
"""
import json
import os


# loading databases
with open(os.path.join(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 
        'data/camrest/db/CamRestDB.json')) as f:
    dbs = json.load(f)

def query(constraints):
    """Returns the list of entities for a given domain
    based on the annotation of the belief state"""
    # query the db

    found = []
    for i, record in enumerate(dbs):
        for key, val in constraints:
            if val == "" or val == "dont care" or val == 'not mentioned' or val == "don't care" or val == "dontcare" or val == "do n't care":
                pass
            else:
                try:
                    record_keys = [k.lower() for k in record]
                    if key.lower() not in record_keys:
                        continue
                    else:
                        if val.strip() != record[key].strip():
                            break
                except:
                    continue
        else:
            record['Ref'] = f'{i:08d}'
            found.append(record)

    return found

