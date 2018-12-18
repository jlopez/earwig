#!/usr/bin/env python
import json
import logging
import os
import re
import requests
import sys
import time
import ujson

from selenium.webdriver.support.ui import WebDriverWait


ERR_RETRY_LIMIT = 1
ERR_HTTP = 2
ERR_XSRF = 3
ERR_CAPTCHA = 4


_ERROR_MESSAGES = {
    ERR_RETRY_LIMIT: 'Retry limit exceeded',
    ERR_HTTP: 'HTTP error',
    ERR_XSRF: 'XSRF missing',
    ERR_CAPTCHA: 'Received captcha'
}



class DriverException(Exception):
    def __init__(self, code, response):
        message = _ERROR_MESSAGES.get(code, 'Google error')
        msg = '%s: %s: %s' % (code, message, response)
        super(DriverException, self).__init__(self, msg)
        self.code = code
        self.response = response


class presence_of_all_cookies(object):
    """ An Expectation for checking if a set of cookies are set """
    def __init__(self, *cookies):
        self.cookies = set(cookies)

    def __call__(self, driver):
        return self.cookies.issubset(set(c['name'] for c in driver.get_cookies()))


def get_credentials(section='login'):
    import ConfigParser
    PATH = '~/.earwig/earwig.properties'
    PROPS = ('username', 'password')
    path = os.path.expanduser(PATH)
    ini = ConfigParser.ConfigParser()
    ini.read(path)
    for prop in PROPS:
        if not ini.has_option(section, prop):
            raise Exception('Unable to find %s in section %s at %s' % (prop, section, path))
    return tuple(ini.get(section, prop) for prop in PROPS)


def element(browser, field_id, timeout=10):
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    wait = WebDriverWait(browser, timeout)
    try:
        return wait.until(ec.element_to_be_clickable((By.ID, field_id)))
    except TimeoutException:
        url = browser.current_url
        browser.quit()
        raise Exception("Unable to locate field %s at %s" % (field_id, url))


def fetch_cookies():
    from selenium import webdriver
    from selenium.webdriver.common.keys import Keys

    user, password = get_credentials()

    URL = 'https://play.google.com/apps/publish/#ApiAccessPlace'
    browser = webdriver.Safari()
    browser.get(URL)
    element(browser, 'identifierId').send_keys(user + Keys.ENTER)

    element(browser, 'user_email').send_keys(user)
    element(browser, 'user_password').send_keys(password + Keys.ENTER)
    WebDriverWait(browser, 10).until(
        presence_of_all_cookies('SID', 'SSID', 'HSID',
                                'APISID', 'SAPISID', 'NID', 'SIDCC'))

    cookies = {c['name']: c['value'] for c in browser.get_cookies()
               if c['name'] in ('SID', 'SSID', 'HSID')}
    browser.quit()
    return cookies


def fetch_tokens(cookies):
    from bs4 import BeautifulSoup

    URL = 'https://play.google.com/apps/publish/#ApiAccessPlace'
    r = requests.get(URL, cookies=cookies)
    html = r.text

    STARTUP = 'startupData = '
    RE_STARTUP = re.compile('^' + STARTUP)
    RE_CACHE_JS = re.compile('.cache.js$')
    RE_GWT = re.compile('.*/fox/gwt/([0-9A-F]*)\.cache\.js$')

    soup = BeautifulSoup(html, 'html.parser')
    startupData = soup.find('script', string=RE_STARTUP)
    if startupData is None:
        curl = 'curl -b "%s" "%s"' % (_cookies_header(cookies), URL)
        raise Exception("Unable to find startupData script tag: %s" % curl)
    parser = json.JSONDecoder()
    data = parser.raw_decode(startupData.string[len(STARTUP):])[0]
    gwt_js = soup.find('script', src=RE_CACHE_JS)['src']

    xsrf_token = ujson.loads(data['XsrfToken'])['1']
    gwt = RE_GWT.match(gwt_js).group(1)
    return xsrf_token, gwt


def f(*args):
    return {str(ix + 1): e for ix, e in enumerate(args)
                           if e is not None }


def _cookies_header(cookies):
    return ';'.join('%s=%s' % e for e in cookies.iteritems())


def _load_json(path, default=None):
    try:
        with open(path, 'rb') as f:
            return ujson.load(f)
    except IOError:
        return default

def _save_json(path, data):
    with open(path, 'wb') as f:
        ujson.dump(data, f, indent=2, sort_keys=True)


def _interval(start_time, interval):
    if start_time is None:
        now = time.localtime()
        today = time.struct_time((now[0], now[1], now[2], 0, 0, 0, 0, 0, -1))
        start_time = time.mktime(today)
    start_time = int(start_time)
    return (str(start_time), str(start_time + interval))


ERROR_CRASH = 1
ERROR_ANR = 2


class PlayDriver(object):
    STATE_PATH = os.path.expanduser('~/.earwig/state.json')

    def __init__(self, account_id, persistence=True, headless=False):
        self.logger = logging.getLogger('driver')
        self.session = requests.Session()
        self.state = DriverState(self.STATE_PATH)
        self.account_id = account_id
        self.persistence = persistence
        self.headless = headless

    def _paginate(self, cmd, params, limit, page_size):
        rv = []
        offset = None
        while limit:
            n = min(page_size, limit)
            data = self._execute(cmd, params(offset, n))
            entries = data.get('1', [])
            offset = data.get('2')
            rv += entries
            limit -= len(entries)
            if offset is None:
                break
        return rv

    def list_android_metrics_error_clusters(self, bundle_id,
                                            start_time, end_time, versions=None,
                                            limit=25, android_versions=None,
                                            show_hidden=False, kind=ERROR_ANR,
                                            installed_from_play=False):
        def params(offset, limit):
            return f(bundle_id, f(str(start_time)), f(str(end_time)),
                     f(versions,
                       [1] if show_hidden else None,
                       None, android_versions, kind,
                       [3, 1] if installed_from_play else None),
                     None, limit, offset)

        return self._paginate('listAndroidMetricsErrorClusters', params, limit, 50)

    def get_android_metrics_reports(self, bundle_id, cluster_id,
                                    start_time, end_time,
                                    versions=None, limit=5,
                                    android_versions=None,
                                    installed_from_play=False):
        def params(offset, limit):
            return f(bundle_id, cluster_id, f(str(start_time)), f(str(end_time)),
                     limit, offset, [3, 1] if installed_from_play else None,
                     versions, android_versions)

        return self._paginate('getAndroidMetricsReports', params, limit, 10)

    def get_android_metrics_cluster_statistics(self, bundle_id, clusters,
                                               start_time, end_time,
                                               versions=None,
                                               android_versions=None,
                                               installed_from_play=False
                                              ):
        data = f(bundle_id, f(str(start_time)), f(str(end_time)), clusters, f(1, 1, 1),
                 f(versions, None, None, android_versions, None,
                   [3, 1] if installed_from_play else None
                  ))

        CMD = 'getAndroidMetricsClusterStatistics'
        return self._execute(CMD, data)

    def _execute(self, cmd, cmd_params):
        URL = 'https://play.google.com/apps/publish/errorreports'

        self._build_state()
        params = dict(account=self.account_id)
        headers = {
            'X-GWT-Permutation': self.state.gwt,
            'Content-Type': 'application/javascript; charset=UTF-8'
        }
        data = {
            'method': cmd,
            'params': ujson.dumps(cmd_params),
            'xsrf': self.state.xsrf
        }

        MAX_RETRIES = 10
        pause = 30
        for attempt in xrange(MAX_RETRIES):
            r = self.session.post(URL, params=params, headers=headers,
                                  cookies=self.state.cookies, json=data)
            sc = r.headers.get('set-cookie', '')
            if 'HSID=' in sc or 'SID=' in sc:
                self.logger.warn("Set-Cookie: %s", sc)
            if r.status_code != 200:
                if 'captcha' in self.text:
                    raise DriverException(ERR_CAPTCHA, response=r)
                raise DriverException(ERR_HTTP, response=r)
            response = r.json()
            error = response.get('error')
            if error is None:
                break
            if attempt == MAX_RETRIES - 1:
                raise DriverException(ERR_RETRY_LIMIT, response=r)
            code = error['code']
            if code != 6800004:
                raise DriverException(code, response=r)
            self.logger.warn("Error 6800004. Retrying after %s seconds", pause)
            time.sleep(pause)
            pause *= 1.5

        xsrf = response.get('xsrf')
        if not xsrf:
            raise DriverException(ERR_XSRF, response=r)
        self.state.xsrf = response['xsrf']
        if self.persistence:
            self.state.save()
        return response['result']

    def _build_state(self):
        state = self.state
        if state.is_valid:
            return
        if not self.persistence:
            raise Exception("Invalid state while running without persistence")
        if not state.cookies:
            if self.headless:
                raise Exception("Invalid state while running in headless mode")
            self.logger.info("Fetching cookies with Selenium")
            state.cookies = fetch_cookies()
            state.save()
        if not state.xsrf or not state.gwt:
            self.logger.info("Fetching xsrf and gwt tokens")
            state.xsrf, state.gwt = fetch_tokens(state.cookies)
            state.save()


class DriverState(object):
    def __init__(self, path):
        self.path = path
        self._load()

    def _load(self):
        data = _load_json(self.path, {})
        self.cookies = data.get('cookies')
        self.xsrf = data.get('xsrf')
        self.gwt = data.get('gwt')

    @property
    def is_valid(self):
        return self.cookies and self.xsrf and self.gwt

    def save(self):
        data = dict(cookies=self.cookies, xsrf=self.xsrf, gwt=self.gwt)
        _save_json(self.path, data)
