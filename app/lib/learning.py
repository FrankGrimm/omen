"""
Manages the active learning components of OMEN.

At the moment this only supports built-in models of spacy
but can later be adapted to support thinc/keras/spacy-transformers

@experimental
"""
import sys
import os
import os.path
import logging
import warnings
import time
from collections import defaultdict

import numpy as np

from spacy.cli.download import get_compatibility as spacy_model_compatibility
import spacy.util as spacy_utils
import spacy
import iso639

import app.lib.database as db
import app.lib.config as config

class LearningException(Exception):
    """Returned if any OMEN specific error occurred related to the learning component."""
    pass

class LearningBenchmark:
    def __init__(self, name):
        self.name = name
        self._start = None
        self._end = None

        self.start()

    def start(self):
        self._start = time.perf_counter()
        return self

    def end(self):
        self._end = time.perf_counter()
        return self

    def duration(self):
        return np.round(self._end - self._start, 2)

    def duration_str(self):
        if self._end is None:
            self.end()
        return f"{self.duration():0.4f}s ({self.name})"

_cached_model_compatibility = None
def model_compatibility():
    """caching for `spacy_model_compatibility`, since that makes a https request each time"""
    global _cached_model_compatibility

    if _cached_model_compatibility is None:
        logging.debug("model compatibility not cached yet, retrieving")
        _cached_model_compatibility = spacy_model_compatibility()

    return _cached_model_compatibility

def normalize_dist(d):
    valsum = sum(d.values())
    for k in d.keys():
        d[k] = np.round(d[k] / valsum, 3)
    return d

def get_split_data(dbsession, dataset, userobj):
    annocount = dataset.annocount(dbsession, userobj)
    anno_min_count = config.get_int("learning_min_annos", 10)
    anno_max_count = config.get_int("learning_max_annos", 1000)
    train_test_ratio = config.get("learning_train_test_ratio", 0.50)

    full_data, _, full_data_total_count = dataset.annotations(dbsession, page=1, page_size=anno_max_count, foruser=userobj,
                                                            user_column="label", only_user=True, with_content=True,
                                                            restrict_view="tagged",
                                                            order_by="random()")
    if full_data_total_count:
        logging.debug("not using %s samples, learning_max_annos (%s) was exceeded" %
                      (full_data_total_count - full_data.shape[0], anno_max_count))
    col_renames = {}
    col_renames[dataset.get_text_column()] = "text"
    full_data = full_data.rename(columns=col_renames)

    train_samples = int(full_data.shape[0] * train_test_ratio)
    test_samples = full_data.shape[0] - train_samples
    logging.debug("got %s samples (requested min: %s, max: %s), using %s as train, %s as test" %
                  (full_data.shape[0], anno_min_count, anno_max_count, train_samples, test_samples))

    train_split, test_split = [], []
    dist_train_split = defaultdict(int)
    dist_test_split = defaultdict(int)

    for _, row in full_data.iterrows():
        target = train_split
        target_dist = dist_train_split
        if len(train_split) >= train_samples:
            target = test_split
            target_dist = dist_test_split

        sample = [row["text"], {"cats": {row["label"]: True}}]
        target.append(sample)
        target_dist[row["label"]] += 1

    logging.debug("created train (%s) and test (%s) splits for user %s on dataset %s" %
                  (len(train_split), len(test_split), userobj, dataset))
    dist_train_split, dist_test_split = normalize_dist(dist_train_split), normalize_dist(dist_test_split)
    return train_split, dist_train_split, test_split, dist_test_split

def training(dataset_id, user_id):
    # TODO make sure to exclude data that was already used in a previous training run
    #      maybe use and store the pagination data for this with a fixed ordering

    training_progress = []
    with db.session_scope() as dbsession:
        dataset = db.dataset_by_id(dbsession, dataset_id)
        userobj = db.User.by_id(dbsession, user_id)

        training_timer = LearningBenchmark("full_training")

        other_pipes = [pipe for pipe in nlp.pipe_names if pipe not in ["textcat"]]
        with nlp.disable_pipes(*other_pipes), warnings.catch_warnings():
            # show warnings for misaligned entity spans only once
            warnings.filterwarnings("once", category=UserWarning, module="spacy")

            optimizer = nlp.begin_training()

            n_total_iter = self._config.get("iterations", 2)
            train_data, dist_train, test_data, dist_test = get_split_data(dbsession, dataset, userobj)

            for n_iter in range(n_total_iter):
                logging.info("%s training, iteration: %s / %s" % (self, n_iter, n_total_iter))

                # TODO assemble training dataset
                #      make sure to restrict this to a number of samples and perform train/test split
                #      once a certain number of samples is reached
                train_timer = LearningBenchmark("training")
                losses = {}
                batches = spacy_utils.minibatch(train_data, size=spacy_utils.compounding(4.0, 32.0, 1.001))

                for batch in batches:
                    texts, annotations = zip(*batch)
                    nlp.update(
                        texts,
                        annotations,
                        drop=0.2,
                        losses=losses
                    )
                loss = losses["textcat"] if "textcat" in losses else "unknown"
                logging.info("%s training, iteration: %s / %s loss: %s" % (self, n_iter, n_total_iter, np.round(loss, 4)))
                logging.info("training iteration took: %s" % train_timer.end().duration())

                eval_timer = LearningBenchmark("evaluation")
                eval_accuracy = None
                # evaluate after each iteration
                with self._pipe.model.use_params(optimizer.averages):
                    gold = [list(goldlabels["cats"].keys())[0] for _, goldlabels in test_data]
                    predictions = [nlp(text).cats for text, _ in test_data]
                    predictions = list(map(lambda cats: max(cats, key=cats.get), predictions))
                    eval_accuracy = sum([1 for idx in range(len(predictions)) if gold[idx] == predictions[idx]]) / len(predictions)

                    logging.info("%s evaluation, iteration: %s / %s loss: %s accuracy: %s" % (self, n_iter, n_total_iter, np.round(loss, 4), np.round(eval_accuracy, 4)))
                logging.info("evaluation took: %s" % eval_timer.end().duration())

                training_progress_item = {
                        "iteration": n_iter,
                        "iterations": n_total_iter,
                        "train_size": len(train_data),
                        "test_size": len(test_data),
                        "distribution": {"train": dist_train, "test": dist_test},
                        "loss": np.round(loss, 6),
                        "accuracy": eval_accuracy,
                        "performance": {"train": train_timer.duration(), "eval": eval_timer.duration()}
                        }
                training_progress.append(training_progress_item)


        logging.info("full training took: %s" % training_timer.end().duration())
        self._status = "trained"
    return training_progress



class LearningModel:
    def __init__(self, filename, nlp, pipe, parameters, config, labels):
        self._filename = filename
        self._nlp = nlp  # spacy model
        self._pipe = pipe  # spacy textcat pipeline element
        self._parameters = parameters
        self._config = config
        self._labels = labels
        self._future = None

        self._status = "loaded"
        if os.path.exists(filename):
            self._status = "trained"

    def can_train(self, dbsession, dataset, userobj):
        """
        returns true if this model can be used to train on
            the provided dataset and user combination,
            provides a reason (string) otherwise
        """
        if dataset is None or userobj is None:
            return "invalid dataset or user"
        if dataset.get_size() <= 0:
            return "invalid dataset size %s" % dataset.get_size()
        if self.status() == "training":
            return "training currently in progress"

        user_annos = dataset.annocount(dbsession, userobj)
        min_anno_count = config.get_int("training_min_annotations", 5)
        if user_annos is None or user_annos < min_anno_count:
            return "not enough annotations for user %s on dataset %s yet: %s < %s" % (userobj, dataset, user_annos, min_anno_count)

        # TODO check when this dataset/user combination was last trained
        # TODO check how many annotations were present when
        #      this dataset/user combination was last trained
        # TODO check if training state has to be discarded because an annotation
        #      was changed or the uploaded data was manipulated

        return True

    def train(self, dbsession, dataset, userobj):
        if self._future is not None:
            raise LearningException("training already in progress")

        self._status = "training"
        self._future = training_pool.submit(training, dataset.dataset_id, userobj.uid)

        return self._future

    def can_predict(self, dataset, userobj):
        if not os.path.exists(self._filename):
            return False
        return self.status() == "trained"

    def status(self):
        if self._future is not None:
            if not self._future.done():
                return "training"
        return self._status

    def __repr__(self):
        return "<LearningModel %s>" % self._filename

class LearningModels:
    """manages creationg and configuratio9n of learning models"""

    @staticmethod
    def get_model_info(model_id, local_only=True):
        for model in LearningModels.spacy_models(local_only=local_only):
            if model["model_id"] == model_id:
                return model
        return None

    @staticmethod
    def spacy_models(local_only=True):
        """
        Tries to gather data on the local spacy installation and figure out which models are available/installed.
        Most of this is implemented using suggestions from https://github.com/explosion/spaCy/issues/4592
        """
        spacy_model_data = model_compatibility()
        spacy_version = spacy.__version__

        modelinfo = []
        model_sizes = {"sm": "small", "md": "medium", "lg": "large"}

        for model_name in sorted(spacy_model_data.keys()):
            model_versions = spacy_model_data[model_name]
            model_supported = False
            model_installed = False

            if spacy_version in model_versions:
                model_supported = True

            if spacy_utils.is_package(model_name):
                model_installed = True

            if not model_supported and not model_installed:
                continue

            if local_only and not model_installed:
                continue

            model_locale = model_name.split("_", 2)[0]
            model_locale_long = model_locale
            try:
                model_locale_long = iso639.to_name(model_locale)
            except iso639.NonExistentLanguageError:
                pass

            current_model = {
                    "model_id": model_name,
                    "available": model_supported,
                    "installed": model_installed,
                    "version": spacy_version,
                    "locale_iso3166": model_locale,
                    "locale": model_locale_long,
                    "size": model_sizes.get(model_name.split("_")[-1], "unknown")
                    }

            modelinfo.append(current_model)

        return modelinfo

    @staticmethod
    def model_architectures():
        """
        returns available model architectures and their parameters (with possible values)
        """
        return {
                "ensemble": {
                    "pipe": "textcat",
                    "description": "Stacked ensemble of bag-of-words and a neural network model.",
                    "parameters": {
                        "textcat": {
                            "ngram_size": {
                                "description": "Which n-grams to compute.",
                                "values": [2, 3, 4],
                                "default_value": 2
                            },
                            "attr": {
                                "description": "Which preprocessing to apply.",
                                "values": [None, "lower"],
                                "default_value": "lower"
                                }
                            }
                        }
                },
                "simple_cnn": {
                    "pipe": "textcat",
                    "description": "Simple CNN model with mean pooled tokens.",
                    "parameters": {}
                },
                "bow": {
                    "pipe": "textcat",
                    "description": "Fast n-gram based bag-of-words model.",
                    "parameters": {
                        "textcat": {
                            "ngram_size": {
                                "target": "textcat",
                                "description": "Which n-grams to compute.",
                                "values": [2, 3, 4],
                                "default_value": 2
                            },
                            "attr": {
                                "target": "textcat",
                                "description": "Which preprocessing to apply.",
                                "values": [None, "lower"],
                                "default_value": "lower"
                                }
                            }
                        }
                    }
                }

def init_model(target_filename, base_model, labels, architecture="ensemble", parameters={}, config={}, create_new=True):
    """

    target_filename -- the location on disk that is used to load or persist the model
    base_model -- the underlying spacy model (may be ignored depending on the chosen architecture)
    architecture -- default: ensemble, one of the keys returned by `LearningModels::model_architectures`
    create_new -- boolean, indicates whether the model located at `target_filename` should be recreated
    """

    architecture_config = LearningModels.model_architectures().get(architecture, None)
    if architecture_config is None:
        raise LearningException("Specified architecture (%s) was not found, possible values: %s." %
                                (architecture, ", ".join(LearningModels.model_architectures().keys())))

    if base_model is None:
        raise LearningException("base_model cannot be null")

    base_model_info = LearningModels.get_model_info(base_model)
    if base_model_info is None:
        raise LearningException("choice for base_model, %s, is not available" % (base_model))

    nlp = None
    if create_new or not os.path.exists(target_filename):
        logging.debug("model target file %s does not exist yet or create_new is true. creating base model %s instead" %
                      (target_filename, base_model))
        nlp = spacy.load(base_model)
    else:
        logging.debug("model target file %s does exist. loading." % (target_filename))
        nlp = spacy.load(target_filename)

    if nlp is None:
        raise LearningException("failed to create a language model")

    if create_new and nlp.has_pipe("textcat"):
        # make sure to discard pre-existing pipes if we are recreating them
        nlp.remove_pipe("textcat")
        logging.debug("removed existing pipeline step")

    parameters = parameters or {}

    # check given parameters
    textcat_param_config = architecture_config.get("parameters", {}).get("textcat", {})
    for arch_parameter, arch_parameter_config in textcat_param_config.items():
        if not arch_parameter in parameters and "default_value" in arch_parameter_config:
            parameters[arch_parameter] = arch_parameter_config.get("default_value")
        if arch_parameter not in parameters:
            raise LearningException("mandatory parameter %s was not provided and has no default value" % arch_parameter)

    parameters["exclusive_classes"] = False
    pipe = None
    if create_new or not nlp.has_pipe("textcat"):
        pipe = nlp.create_pipe(
                "textcat", config=parameters
                )
        nlp.add_pipe(pipe, last=True)
    else:
        pipe = nlp.get_pipe("textcat")

    for label in labels:
        pipe.add_label(label)

    loaded_model = LearningModel(target_filename, nlp, pipe, parameters, config, labels)
    return loaded_model

def status():
    """gathers information on active and finished training runs"""

    status_info = {}



    return status_info

def debug():
    with db.session_scope() as dbsession:
        debugdata = {
            "models": LearningModels.spacy_models(),
            "architectures": LearningModels.model_architectures(),
            }


        debugdata["test"] = {}
        dataset = db.dataset_by_id(dbsession, 1)
        anno_user = dataset.owner
        debugdata["test"]["ds"] = str(dataset)
        debugdata["test"]["user"] = str(anno_user)

        default_base_model = LearningModels.spacy_models()[0]["model_id"]
        base_model = dataset.dsmetadata.get("learning_model", default_base_model)
        model_architecture = dataset.dsmetadata.get("learning_architecture", "ensemble")
        model_params = dataset.dsmetadata.get("learning_parameters", {})

        training_config = {
                "iterations": config.get("learning_iterations", 5),
                "dropout": config.get("learning_dropout", 0.5)
                }

        debugdata["test"]["base_model"] = base_model
        catmodel = init_model("./testmodel.model",
                              base_model,
                              labels=dataset.get_taglist(),
                              architecture=model_architecture,
                              parameters=model_params,
                              config=training_config,
                              create_new=True)
        debugdata["test"]["res"] = str(catmodel)
        debugdata["test"]["status1"] = catmodel.status()

        debugdata["test"]["status1-cantrain"] = catmodel.can_train(dbsession, dataset, anno_user)
        debugdata["test"]["status1-canpredict"] = catmodel.can_predict(dataset, anno_user)

        if catmodel.can_train(dbsession, dataset, anno_user):
            debugdata["test"]["training"] = catmodel.train(dbsession, dataset, anno_user).result()

        debugdata["test"]["status2"] = catmodel.status()
        debugdata["test"]["status2-cantrain"] = catmodel.can_train(dbsession, dataset, anno_user)
        debugdata["test"]["status2-canpredict"] = catmodel.can_predict(dataset, anno_user)

        return debugdata
