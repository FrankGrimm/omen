import json
import os

CFG_FILENAME="./config.json"

def load_config():
    obj = {}
    if os.path.exists(CFG_FILENAME):
        with open(CFG_FILENAME, "rt") as infile:
            obj = json.load(infile)
    else:
        print("WARN: config file not found at %s" % os.path.abspath(CFG_FILENAME))
    if not obj:
        obj = {}
    return obj

def store_config(cfg):
    with open(CFG_FILENAME, "wt") as outfile:
        json.dump(cfg, outfile)
    return cfg

def get(key, default_value = None, raise_missing = False):
    cfg = load_config()

    if not cfg or not key in cfg:
        if raise_missing:
            raise Exception("missing config parameter '%s'" % key)
        return default_value

    return cfg[key]

def set(key, val):
    cfg[key] = val
    store_config(cfg)

