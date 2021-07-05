"""
JSON serialization helper
"""
import json
import numpy as np


class NpEncoder(json.JSONEncoder):
    """
    numpy safe JSON converter
    adapted from https://stackoverflow.com/a/57915246
    """
    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.bool_):
            return bool(o)
        return super(NpEncoder, self).default(o)
