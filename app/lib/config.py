"""
Main configuration.

The configuration is, by default, stored in a JSON formatted file called `./config.json`.

Users can override the location of the configuration file by setting the environment variable `OMEN_CONFIG_FILENAME`.

Users can override any configuration value by passing the respective equivalent as environment variables. Option keys can be translated to environment variables by:
- Prefixing the key with `OMEN_`, e.g. `option key` => `OMEN_option key`.
- Replacing all spaces with underscores, e.g. `OMEN_option key` => `OMEN_option_key`.
- Converting the whole key to uppercase letters, e.g. `OMEN_option_key` => `OMEN_OPTION_KEY`.

"""
import json
import os

CFG_FILENAME = os.environ.get("OMEN_CONFIG_FILENAME", "./config.json")

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

def get_int(key, default_value=None, raise_missing=False):
    val = get(key, default_value, raise_missing)
    if val is not None:
        return int(val)

def get(key, default_value=None, raise_missing=False):
    cfg = load_config()
    if key is None:
        key = ""

    environ_value = os.environ.get("OMEN_%s" % key.replace(" ", "_").upper(), None)
    if not environ_value is None:
        return environ_value

    if not cfg or not key in cfg:
        if raise_missing:
            raise Exception("missing config parameter '%s'" % key)
        return default_value

    return cfg[key]

def store(key, val):
    cfg = load_config()
    cfg[key] = val
    store_config(cfg)
