#!/usr/bin/env python
import formats
import logging
import Queue
import threading
import ujson
import sys
import time

from driver import PlayDriver


def _thread_raise(thread, exception):
    import ctypes
    set_async_exc = ctypes.pythonapi.PyThreadState_SetAsyncExc
    ret = set_async_exc(ctypes.c_long(thread.ident),
                        ctypes.py_object(exception))
    if ret > 1:
        set_async_exc(thread.ident, 0)


class Earwig(object):
    def __init__(self, account_id, bundle_id, start_time, end_time,
                 max_clusters=500, max_reports=500, parallelism=1,
                 headless=False
                ):
        import Queue
        self.queue = Queue.Queue()
        self.lock = threading.Lock()
        self.account_id = account_id
        self.bundle_id = bundle_id
        self.start_time = start_time
        self.end_time = end_time
        self.max_clusters = max_clusters
        self.max_reports = max_reports
        self.parallelism = parallelism
        self.headless = headless
        self.logger = logging.getLogger('main')
        self.rc = 0

    def _yield(self, datum):
        self.queue.put(datum)

    def _next_cluster_index(self):
        with self.lock:
            cluster_ix = self.current_cluster_ix
            self.current_cluster_ix += 1
            return cluster_ix

    def terminate(self, rc):
        self.logger.error("Terminating: %s", rc)
        self.terminated = True
        for thread in self.threads:
            _thread_raise(thread, KeyboardInterrupt)
        self.rc = rc

    def _processor(self):
        try:
            self._processor_impl()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.logger.exception("Exception caught. Terminating...")
            self.terminate(3)

    def _processor_impl(self):
        driver = PlayDriver(self.account_id, headless=self.headless,
                            persistence=False)
        n = len(self.cluster_ids)
        while not self.terminated:
            ix = self._next_cluster_index()
            if ix >= n:
                break
            cluster_id = self.cluster_ids[ix]
            reports = driver.get_android_metrics_reports(
                bundle_id=self.bundle_id, cluster_id=cluster_id,
                start_time=self.start_time, end_time=self.end_time,
                limit=self.max_reports)
            if self.terminated:
                break
            self.logger.debug("%s/%s: Cluster %s got %s reports",
                              ix + 1, n, cluster_id, len(reports))
            try:
                flattened = formats.flatten(reports, formats.REPORT_SPEC)
            except formats.FormatException as e:
                with open("error.json", "wb") as f:
                    ujson.dump(e.data, f)
                if e.leaf:
                    with open("leaf.json", "wb") as f:
                        ujson.dump(e.leaf, f)
                self.logger.error("Format error: %s. File saved at error.json", e)
                self.terminate(1)
                break
            for report in flattened:
                self.logger.debug("Saving report %s", report['id'])
                report['bundleId'] = self.bundle_id
                report['clusterId'] = cluster_id
                self._yield(report)


    def reports_iterator(self):
            driver = PlayDriver(self.account_id, headless=self.headless)
            self.logger.info("Downloading hourly reports for %s",
                             time.ctime(self.start_time))
            clusters = driver.list_android_metrics_error_clusters(
                bundle_id=self.bundle_id, limit=self.max_clusters,
                start_time=self.start_time, end_time=self.end_time)
            self.current_cluster_ix = 0
            self.cluster_ids = [cluster['1'] for cluster in clusters]
            self.terminated = False
            self.threads = []
            for thread_ix in xrange(self.parallelism):
                name = 'earwig-%s' % thread_ix
                thread = threading.Thread(target=self._processor, name=name)
                thread.start()
                self.threads.append(thread)
            while any(t.is_alive() for t in self.threads):
                try:
                    yield self.queue.get(timeout=0.1)
                except Queue.Empty:
                    pass


def opt_timestamp(s):
    import dateparser
    return int(time.mktime(dateparser.parse(s).timetuple()))


def _previous_hour():
    return _truncate_to_hour(time.time() - 3600)


def _truncate_to_hour(ts):
    st = time.localtime(ts)
    truncated = time.struct_time((st[0], st[1], st[2], st[3], 0, 0, 0, 0, -1))
    return int(time.mktime(truncated))


def _error(msg):
    print >>sys.stderr, 'earwig: %s' % msg
    sys.exit(1)


def main():
    import argparse
    import os


    parser = argparse.ArgumentParser(description="Download Google Play ANR reports")
    parser.add_argument('-f', '--from', dest='from_time', type=opt_timestamp,
                        help='specify download start time '
                        '(defaults to the previous hour)')
    parser.add_argument('-t', '--to', dest='to_time', type=opt_timestamp,
                        help='specify download end time')
    parser.add_argument('-i', '--interval', type=int,
                        help='specify time period to download, in seconds '
                        '(defaults to 1 hour)')
    parser.add_argument('-o', '--output',
                        help='specify the output filename '
                        '(defaults to output/YYYYMMDD/HH.json.gz)')
    parser.add_argument('-j', '--threads', default=1, type=int,
                        help='set the parallelism (default: 1)')
    parser.add_argument('-H', '--headless', action='store_true',
                        help="run in headless mode, i.e. do not use Selenium "
                        "and expect a valid state file to be present")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='minimize execution output')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='report more information during execution')
    parser.add_argument('account_id',
                        help='the account id to download reports for')
    parser.add_argument('bundle_id',
                        help='the bundle id to download reports for')

    opts = parser.parse_args(sys.argv[1:])

    if opts.to_time and opts.interval:
        _error("only one of --to and --interval may be specified")

    fmt = 'output/%Y%m%d/%H.json.gz'

    interval = opts.interval or 3600
    start_time = opts.from_time or _previous_hour()
    end_time = opts.to_time or start_time + interval
    output_path = opts.output or time.strftime(fmt, time.localtime(start_time))

    if output_path != '-':
        subdir, _ = os.path.split(output_path)
        if subdir and not os.path.exists(subdir):
            os.makedirs(subdir)
        if not os.path.isdir(subdir):
            _error('%s is not a directory' % subdir)

    log_level = 10 if opts.verbose else 20 if not opts.quiet else 30
    logging.basicConfig(format="%(asctime)s [%(threadName)-10s] %(levelname)5s %(name)-8s %(message)s", level=log_level)

    wig = Earwig(opts.account_id, opts.bundle_id, start_time, end_time,
                 parallelism=opts.threads, headless=opts.headless)

    def sink(earwig, fp):
        try:
            logger = logging.getLogger('main')
            ix = 0
            for ix, report in enumerate(earwig.reports_iterator()):
                if ix and not ix % 100:
                    logger.info("%d reports processed", ix)
                ujson.dump(report, fp)
                fp.write('\n')
            logger.info("%d reports saved to %s", ix, output_path)
        except KeyboardInterrupt:
            earwig.terminate(2)

    if output_path == '-':
        sink(wig, sys.stdout)
    else:
        import gzip
        open_fn = gzip.open if output_path.endswith('.gz') else open
        with open_fn(output_path, 'wb') as output:
            sink(wig, output)

    sys.exit(wig.rc)
