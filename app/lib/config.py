"""
Main configuration.

The configuration is, by default, stored in a JSON formatted file called `./config.json`.

Users can override the location of the configuration file by setting the environment variable `OMEN_CONFIG_FILENAME`.

Users can override any configuration value by passing the respective equivalent as environment variables.
Option keys can be translated to environment variables by:
- Prefixing the key with `OMEN_`, e.g. `option key` => `OMEN_option key`.
- Replacing all spaces with underscores, e.g. `OMEN_option key` => `OMEN_option_key`.
- Converting the whole key to uppercase letters, e.g. `OMEN_option_key` => `OMEN_OPTION_KEY`.

"""
import json
import sys
import os
import logging

CFG_FILENAME = os.environ.get("OMEN_CONFIG_FILENAME", "./config.json")


def load_config():
    obj = {}
    if os.path.exists(CFG_FILENAME):
        with open(CFG_FILENAME, "rt") as infile:
            obj = json.load(infile)
    else:
        print("WARN: config file not found at %s" % os.path.abspath(CFG_FILENAME), file=sys.stderr)
    if not obj:
        obj = {}
    return obj


def store_config(cfg):
    with open(CFG_FILENAME, "wt") as outfile:
        json.dump(cfg, outfile, indent=4)
    logging.debug("written configuration to %s", CFG_FILENAME)
    return cfg


def get_int(key, default_value=None, raise_missing=False):
    val = get(key, default_value, raise_missing)
    if val is not None:
        return int(val)
    return default_value


def get_bool(key, default_value=False, raise_missing=False):
    val = get(key, default_value, raise_missing)
    if val is not None:
        return bool(val)
    return default_value


def get(key, default_value=None, raise_missing=False):
    cfg = load_config()
    if key is None:
        key = ""

    environ_value = os.environ.get("OMEN_%s" % key.replace(" ", "_").upper(), None)
    if environ_value is not None:
        return environ_value

    if not cfg or key not in cfg:
        if raise_missing:
            raise Exception("missing config parameter '%s'" % key)
        return default_value

    return cfg[key]


def store(key, val):
    logging.debug("config::value update %s", key)
    cfg = load_config()
    cfg[key] = val
    store_config(cfg)
