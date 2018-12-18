#!/usr/bin/env python
import ujson


_UNDEFINED = object()


def _abbreviated_json(data, max_length=None):
    txt = ujson.dumps(data)
    if max_length and len(txt) > max_length:
        h = (max_length - 3) / 2
        return txt[0:h] + '...' + txt[-h:]
    return txt


class FormatException(Exception):
    def __init__(self, msg, data, spec, path, leaf=None):
        message = 'At path %s: %s' % (path, msg)
        if leaf:
            message += ', leaf=%s' % _abbreviated_json(leaf, 16)
        super(FormatException, self).__init__(message)
        self.data = data
        self.spec = spec
        self.path = path
        self.leaf = leaf


class Flattener(object):
    def __init__(self, data, spec):
        self._validate_spec(spec, dict)
        self.data = data
        self.spec = spec
        self.path = ''
        self.result = {}

    def _validate_spec(self, spec, _type):
        if not isinstance(spec, _type):
            self._error("Invalid spec type %s != %s" %
                        type(spec).__name__, _type.__name__)

    def _error(self, msg, **kwargs):
        raise FormatException(msg, self.data, self.spec, self.path, **kwargs)

    def flatten(self):
        return self._flatten(self.spec, self.data, None, '')

    def _flatten(self, spec, src, dst, path):
        self.path = path + '['
        if isinstance(src, dict):
            self._validate_spec(spec, dict)
            if dst is None:
                dst = {}
            for k, v in src.iteritems():
                curr_path = path + k
                info = spec.get(k, _UNDEFINED)
                if info == _UNDEFINED:
                    self._error("Spec missing property %s" % k, leaf=v)
                if info is None:
                    continue
                new_val = self._flatten(info, v, dst, curr_path)
                self.path = curr_path
                if new_val != dst:
                    new_key = self._spec_key(info) or self._generate_key(curr_path)
                    if new_key in dst:
                        self._error("Key colision: %s" % new_key, leaf=v)
                    if new_key.startswith('i_'):
                        new_key = new_key[2:]
                        new_val = int(new_val)
                    dst[new_key] = new_val
            return dst
        elif isinstance(src, list) and not isinstance(src, basestring):
            array = []
            for elem in src:
                new_elem = self._flatten(spec, elem, None, path + '[')
                array.append(new_elem)
            return array
        else:
            return src

    def _spec_key(self, spec):
        if isinstance(spec, basestring):
            return spec
        elif isinstance(spec, dict):
            return spec.get('name')
        self._error("Invalid spec type %s" % type(spec).__name__)

    def _generate_key(self, path):
        return 'f' + path.rsplit('[', 1)[-1]


def flatten(data, spec):
    return Flattener(data, spec).flatten()


def generate_spec(data, path=""):
    """ Generate a spec template given sample data """
    if isinstance(data, dict):
        rv = { "0name": "" }
        for k, v in data.iteritems():
            rv[k] = generate_spec(v, path + k)
        return rv
    elif isinstance(data, list) and not isinstance(data, basestring):
        rv = None
        for ix, v in enumerate(data):
            spec = generate_spec(v, path + '[')
            if rv is None:
                rv = spec
            else:
                rv.update(spec)
        return rv
    else:
        return ""


REPORT_SPEC = {
    "name": "errors",
    "1": "id",
    "2": {
        "name": "timestamp",
        "1": "i_timestamp",
        "2": "timezoneOffset"
    },
    "3": {
        "name": "errorInfo",
        "2": {
            "name": "crashInfo",
            "1": "title",
            "2": "activity",
            "3": { # * 1 per thread
                "name": "threads",
                "1": "description",
                "2": { # * 1 per stack line
                    "name": "stackTrace",
                    "1": "function",
                    "2": "file",
                    "3": "line",
                    "4": "lockInfo",
                    "5": "library",
                    "6": "i_pc",
                    "7": "i_functionOffset",
                    "8": "isSystem",
                    "9": {
                        "name": "javaMethod",
                        "1": "javaClass",
                        "2": "javaMethod" # * why multiple??
                    }
                },
                "3": {
                    "name": "properties",
                    "1": "name",
                    "2": {
                        "name": "flags",
                        "2": "id",
                        "3": "isDaemon",
                        "4": "flags"
                    }
                },
                "4": {
                    "name": "waitingLock",
                    "1": "i_lockAddress",
                    "2": "lockClass",
                    "3": "lockOwningThreadId"
                },
                "5": "isSystem",
                "6": {
                    "name": "",
                    "1": ""
                }
            },
            "4": {
                "name": "",
                "2": {
                    "name": "",
                    "1": { "name": "", "1": ""},
                    "2": { "name": "", "1": "", "2": ""}
                }
            },
            "6": "",
            "7": "",
            "8": "intentComponent",
            "9": {
                "name": "",
                "1": "altTitle",
                "2": "location",
                "3": ""
            }
        }
    },
    "4": {
        "name": "appVersion",
        "1": "appVersion"
    },
    "5": "androidVersion",
    "6": "altDeviceId",
    "7": {
        "name": "deviceInfo",
        "1": "deviceId",
        "2": "deviceName", # * multiple
        "3": "deviceManufacturer",
        "4": "deviceChipset",
        "5": "deviceBoard",
        "7": "deviceDpi",
        "8": "deviceScreenWidth",
        "9": "deviceScreenHeight",
        "10": "deviceGlVersion"
    }
}
