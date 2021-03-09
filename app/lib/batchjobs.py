"""
Manages when and how background tasks are executed.
"""
from concurrent import futures
from collections import defaultdict
import logging

from app.lib import config
import app.lib.database as db

_HANDLERS = {}
_MANAGED_JOBS = []
_COUNTERS = defaultdict(int)
batch_pool = None


# class Job(Base):
#     __tablename__ = 'jobs'
#
#     jobid = Column(Integer, primary_key=True)
#     target_fn = Column(String, nullable=False)
#     jobstate = Column(String, nullable=False, default="queued")
#     jobdata = Column(JSON, nullable=False)


def accepts_jobs():
    return batch_pool is not None


def tick():
    """
    invoked continously during the runtime of the server
    checks if the current process can accept jobs and
    if any are stored in the database
    """
    if not accepts_jobs():
        return
    with db.session_scope() as dbsession:
        for queued_job in db.queued_jobs():
            logging.debug(f"QUEUED JOB: {queued_job}")


def startup():
    """
    creates the pool of worker processes

    app.web is responsible for calling this method and ensures only one of these is active in a cluster setup
    """
    global batch_pool
    max_workers = config.get_int("batch_max_workers", 1)
    logging.debug("initializing pool of max %s batch workers" % max_workers)
    batch_pool = futures.ProcessPoolExecutor(max_workers=max_workers)


def teardown(reason=None):
    if batch_pool is None:
        return
    logging.debug("received shutdown signal (reason: %s)" % (reason if reason is not None else "none"))
    batch_pool.shutdown(wait=True)
    logging.debug("batch processing pool shut down")


class BatchJobException(Exception):
    pass


class BatchJob:
    def __init__(self, fn_name, metadata, *args, **kwargs):
        if batch_pool is None:
            raise BatchJobException("can only enqueue batch jobs in main worker process")
        if not fn_name in _HANDLERS:
            raise BatchJobException(f"requested to enqueue batch job for unknown target handler <{fn_name}>")

        self.metadata = metadata
        self.fn_name = fn_name
        self.args = args
        self.kwargs = kwargs
        self.future = None
        self.callbacks = []

        _MANAGED_JOBS.append(self)

        fn = _HANDLERS[fn_name]
        logging.debug("submitting function %s args: %s kwargs: %s" % (fn, args, kwargs))
        future = batch_pool.submit(fn, *args, *kwargs)
        logging.debug("submitted function %s" % (fn))
        self.set_future(future)
        _COUNTERS["jobs_enqueued"] += 1
        logging.debug(f"job enqueued: {self}")

    def done(self):
        return self.future.done()

    def exception(self, timeout=0):
        return self.future.exception(timeout)

    def result(self, timeout=0):
        return self.future.result(timeout)

    def set_future(self, future):
        self.future = future
        self.future.add_done_callback(self.__future_done)

    def add_done_callback(self, cb):
        logging.warning("DEBUG: a_d_c")
        self.callbacks.append(cb)
        if self.future.done():
            logging.warning("DEBUG: a_d_c immediate dispatch")
            cb(self)

    def __future_done(self, _):
        logging.debug(f"job completed: {self}")
        _COUNTERS["jobs_completed"] += 1
        if self.future.cancelled():
            _COUNTERS["jobs_cancelled"] += 1

        _MANAGED_JOBS.pop(_MANAGED_JOBS.index(self))
        for cb in self.callbacks:
            cb(self)


def status():
    statusinfo = {}

    for k, v in _COUNTERS.items():
        statusinfo[k] = v

    statusinfo["jobs_pool"] = len(batch_pool)
    statusinfo["jobs_managed"] = len(_MANAGED_JOBS)

    return statusinfo


def register(fn_name, fn):
    if batch_pool is None:
        return

    if fn_name in _HANDLERS:
        raise BatchJobException(f"handler for function <{fn_name}> was previously registered")
    if fn is None:
        raise BatchJobException(f"failed to register handler <{fn_name}>: expected function but received null")
    logging.debug("batchjob::register %s" % fn_name)
    _COUNTERS["handlers_registered"] += 1
    _HANDLERS[fn_name] = fn


def test_hello_batchjob(name_param):
    import time

    time.sleep(10)
    return f"hello {name_param}!"


register("hello_batchjob", test_hello_batchjob)


def schedule_test():
    testjob = BatchJob("hello_batchjob", {"meta": "data"}, "foobar")

    def tcb(job):
        logging.debug("CALLBACK " * 7 + " " + str(job.future.result(0)))
        # logging.debug(JOBRES: %s %s" % (job, job.future.result(0)))

    testjob.add_done_callback(tcb)
