"""
Inter-Annotator Agreement calculations
"""

import logging

import numpy as np


def get_kappa_interpretation(kappa):
    if kappa is None or np.isnan(kappa):
        return "Invalid Value"

    if kappa < 0:
        return "Poor"
    if kappa <= 0.2:
        return "Slight"
    if kappa <= 0.4:
        return "Fair"
    if kappa <= 0.6:
        return "Moderate"
    if kappa <= 0.8:
        return "Substantial"
    # kappa > 0.8:
    return "Almost perfect"


def fleiss_kappa(df, tags, exclude_insufficient=False, filter_target=None):

    if df.shape[0] == 0:
        return {"type": "fleiss",
                "kappa": None,
                "interpretation": "Insufficient data"}

    # pivot by given tag
    df = df.pivot(index="sample_index", columns="anno_tag")
    # remove pivot level from dataframe
    df.columns = df.columns.droplevel(0)
    df.columns.name = None
    df = df.reset_index().set_index("sample_index")

    if filter_target is not None:
        df = df[df[filter_target] > 0]

    # replace all nan's in the count columns with 0.0
    tag_columns = df.columns.difference(["sample_index"])
    df[tag_columns] = df[tag_columns].fillna(value=0.0)

    k = len(tags)
    n = df[tag_columns].sum(axis=1).max()

    tag_totals = df[tag_columns].sum()
    total_sum = tag_totals.sum()

    # normalize rows to max number of annotators n
    # this makes the calculation easier later on
    # because it assumes that all annotators
    # have annotated every sample
    # or (exclude_insufficient=True): restrict calculation to samples
    # that were at least annotated by more than one user:
    if exclude_insufficient:
        df["row_total"] = df[tag_columns].sum(axis=1)
        df = df.loc[df.row_total > 1]
    else:
        df[tag_columns] = df[tag_columns].apply(
                lambda x: x/(x.sum()/n),
                axis=1)

    if df.shape[0] == 0:
        return {"type": "fleiss", "kappa": None,
                "interpretation": "Insufficient data"}

    df["row_total"] = df[tag_columns].sum(axis=1)

    df["p_i"] = np.NAN
    df.loc[df["row_total"] <= 1, "p_i"] = 1.0
    df.loc[df["row_total"] > 1, "p_i"] = \
        (1.0 / (df.row_total * (df.row_total - 1))) \
        * (
            df[tag_columns].pow(2).sum(axis=1) - df.row_total
        )

    p_avg = (1.0 / df.shape[0]) * df.p_i.sum(axis=0)

    p_j = (1.0 / (df.shape[0]*n)) * df[tag_columns].sum(axis=0)
    p_avg_e = p_j.pow(2).sum()

    logging.debug("N=%s, n=%s, k=%s, total_sum=%s", df.shape[0], n, k, total_sum)
    logging.debug("p_avg=%s, p_avg_e=%s", p_avg, p_avg_e)

    f_kappa = (p_avg - p_avg_e) / (1 - p_avg_e)
    f_kappa = np.round(f_kappa, 4)
    f_kappa_text = get_kappa_interpretation(f_kappa)

    logging.debug("Fleiss' Kappa %s (%s)", f_kappa, f_kappa_text)

    if np.isnan(f_kappa):
        f_kappa = None
        f_kappa_text = "Unknown"

    return {
            "type": "fleiss",
            "kappa": f_kappa,
            "interpretation": f_kappa_text
            }
