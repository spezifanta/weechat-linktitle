# -*- coding: utf-8 -*-
# vim: ts=4 et sw=4

# Copyright (C) 2011  Bluthund <bluthund23@gmail.com>
# Function for unescaping HTML entities by Fredrik Lundh <http://effbot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""WeeChat script that automatically fetches link titles for posted URLs."""

from __future__ import print_function

try:
    import weechat
except ImportError:
    weechat = None

import datetime
import HTMLParser
import json
import pickle
import re
import sys
import time
import urllib2

SCRIPT_NAME    = "linktitle"
SCRIPT_AUTHOR  = "Bluthund <bluthund23@gmail.com>"
SCRIPT_VERSION = "0.3"
SCRIPT_LICENSE = "GPL3"
SCRIPT_DESC    = "Show the title of incoming links."

SCRIPT_PREFIX = "[linktitle]"

TIMEOUT = 3 # seconds

weechat_encoding = "utf-8" # use utf-8 as fallback

# url cache: dict<str(url), (int(time.time()), str(title))>
url_cache = {}
# only re-retrieve titles of cached URLs after this lifetime (in s)
CACHE_LIFETIME = 6 * 60 * 60

# Unescape HTML Entities; thanks to Fredrik Lundh
# http://effbot.org/zone/re-sub.htm#unescape-html
import htmlentitydefs

def unescape(text):
    def fixup(m):
        text = m.group(0)
        if text[:2] == "&#":
            # character reference
            try:
                if text[:3] == "&#x":
                    return unichr(int(text[3:-1], 16))
                else:
                    return unichr(int(text[2:-1]))
            except ValueError:
                pass
        else:
            # named entity
            try:
                text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
            except KeyError:
                pass
        return text # leave as is
    return re.sub("&#?\w+;", fixup, text)

class MetaTagParser(HTMLParser.HTMLParser):
    # see "RFC 2616 - Hypertext Transfer Protocol -- HTTP/1.1"
    # NOTE omitted ASCII control characters
    token_class = r"[^()<>@,;:\\\"/[\]?={} \t]+"

    contenttype_re = "({0}/{0})(?:;.*charset=({0}))?".format(token_class)

    charset = ""
    contenttype = ""

    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)

    def _process_meta_tag(self, tag, attrs):
        def parse_http_equiv(attrs):
            for _, value in attrs:
                m = re.match(self.contenttype_re, value)
                if m:
                    return m.groups()
            return None, None

        for name, value in attrs:
            # HTML5 <meta charset="xxx">
            if name == "charset":
                self.charset = value
            # <meta http-equiv="content-type">
            elif name == "http-equiv" and value.lower() == "content-type":
                self.contenttype, self.charset = parse_http_equiv(attrs)

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            self._process_meta_tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        if tag == 'meta':
            self._process_meta_tag(tag, attrs)

def check_meta_info(headers, body):
    contenttype = headers.type
    charset = headers.getparam("charset")

    # if contenttype or charset is empty, try to find them
    # via the information given by the document
    if not contenttype or not charset:
        # TODO parse xml processing instruction for encoding-attribute
        p = MetaTagParser()
        p.contenttype = contenttype
        p.charset = charset
        try:
            p.feed(body)
            p.close()
        except HTMLParser.HTMLParseError:
            pass
        finally:
            contenttype, charset = p.contenttype, p.charset

    return contenttype, charset

def get_youtube_video_duration(video_url):
    videoid_re = r"""youtu(?:\.be/|be\.com              # domain
                     /(?:embed/|v/|watch\?(?:.*?&)?v=)) # path
                     \b([-\w]{11})\b                    # video id"""

    data_url = ("http://gdata.youtube.com/feeds/api/"
                "videos/{videoid}?v=2&alt=json")

    vidid = re.search(videoid_re, video_url, re.X)

    if vidid:
        data = urllib2.urlopen(data_url.format(videoid = vidid.group(1)))

        md = json.load(data)

        duration = int(md["entry"]["media$group"]["yt$duration"]["seconds"])
        duration = datetime.time(hour = duration // 60 // 60,
                                 minute = duration // 60 % 60,
                                 second = duration % 60).isoformat()

        # remove hours if duration < 1h
        if duration.startswith("00:"):
            duration = duration[3:]

        return duration
    else:
        return ""

def print_title_cb(data, cmd, rc, stdout, stderr):
    buf, url = data.split("\t", 1)

    if stdout != "":
        url_cache[url]["data"] += stdout

    # NOTE rc is of type str; python example in the weechat docs is wrong
    if int(rc) >= 0 and url_cache[url]["data"]:
        url_cache[url]["data"] = pickle.loads(url_cache[url]["data"])

        # get out of here if http response code isn't OK
        if url_cache[url]["data"]["code"] != 200:
            url_cache[url]["data"] = ""
            return weechat.WEECHAT_RC_OK

        resp = url_cache[url]["data"]
        headers = resp["headers"]
        body = resp["body"]

        contenttype, charset = check_meta_info(headers, body)

        try:
            body = body.decode(charset);
        except (LookupError, TypeError):
            # couldn't find specified input encoding or None given
            # try to decode using standard encoding
            # and ignore byte-sequences that cannot be decoded
            body = body.decode(errors = "ignore")

        title = ""
        if "</title>" in body.lower():
            title = body[body.lower().find("<title>")+7:
                         body.lower().find("</title>")]
        elif contenttype == "text/plain":
            title = body
        title = re.sub(r"\s+", " ", title.strip())
        title = unescape(title)

        buf = data[:data.find("\t")]
        url = data[data.find("\t")+1:]

        video_duration = get_youtube_video_duration(url)
        if video_duration:
            title += " ({0})".format(video_duration)

        url_cache[url]["title"] = title
        url_cache[url]["data"] = ""

        if title:
            print_to_buffer(buf, title)

    return weechat.WEECHAT_RC_OK

def print_to_buffer(buf, msg):
    if len(msg) == 0:
        return # do not print empty messages

    msg = msg.encode(weechat_encoding)
    weechat.prnt(buf, "{pre}\t{msg}".format(pre = SCRIPT_PREFIX, msg = msg))

def fetch_url(url, timeout, cb, data):
    # NOTE this function is used via reflection, change with caution;
    #      see below for details
    def fetchit():
        import pickle
        import sys
        import urllib2

        data = dict()

        try:
            req = urllib2.Request("_SUB_url_")
            req.add_header("User-Agent", "WeeChat/_SUB_version_")
            resp = urllib2.urlopen(req, None, _SUB_timeout_)
        except urllib2.HTTPError, e:
            pass
        except urllib2.URLError, e:
            print(e.reason, file = sys.stderr)
            print("url was _SUB_url_", file = sys.stderr)
            sys.exit(1)

        data["code"] = resp.code
        data["headers"] = resp.info()

        contenttype = data["headers"].type

        data["body"] = ""
        if "html" in contenttype or "xml" in contenttype:
            while "</head>" not in data["body"].lower():
                s = resp.read(1024)
                if len(s) == 0:
                    break
                data["body"] += s
        elif contenttype == "text/plain":
            data["body"] = resp.readline()

        data["body"] = data["body"].replace("\r", "").replace("\n", "")

        pickle.dump(data, sys.stdout, protocol = 0)

    # let the voodoo begin
    # - read source code of fetchit()
    # - substitute def statement by future-import statement
    # - reindent
    # - replace placeholders w/ format()-able brace-expressions
    # - format() code
    import inspect
    code = inspect.getsource(fetchit)
    future_import = "from __future__ import print_function\n"
    code = re.sub(r"^.*\n", future_import, code, 1)
    code = re.sub(r"\n[ ]{8}", "\n", code)
    code = re.sub(r"_SUB_(\w+)_", lambda m: "{%s}" % m.group(1), code)
    code = code.format(url = url,
                       version = weechat.info_get("version", ""),
                       timeout = timeout)

    cmd = "{exe} -c '{0}'".format(code, exe = sys.executable)
    weechat.hook_process(cmd, 0, cb, data)

def print_link_title(buf, link):
    def expired(link):
        return time.time() > url_cache[link]["time"] + CACHE_LIFETIME

    if link in url_cache and not expired(link):
        print_to_buffer(buf, url_cache[link]["title"])
    else:
        url_cache[link] = {"time": time.time(),
                           "data": "",
                           "title": ""}
        fetch_url(link, TIMEOUT, "print_title_cb", buf + "\t" + link)

    return weechat.WEECHAT_RC_OK

def link_cb(data, buf, date, tags, displayed, hilight, prefix, message):
    # don't look at own output or output in core buffer
    if prefix == SCRIPT_PREFIX or buf == weechat.buffer_search_main():
        return weechat.WEECHAT_RC_OK

    # only fetch link titles for http|https schemas
    # no need for full RFC regex (RFC 3986); urllib2 takes care of the rest
    for link in re.findall("https?://[^ \">]+", message, re.I):
        print_link_title(buf, link)

    return weechat.WEECHAT_RC_OK

if __name__ == "__main__":
    if weechat:
        weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION,
                         SCRIPT_LICENSE, SCRIPT_DESC, "", "")

        weechat_encoding = weechat.info_get("charset_internal", "")

        weechat.hook_print("", "irc_privmsg", "://", 1, "link_cb", "")
    else:
        print("This script is supposed to be run in WeeChat.\n"
              "You can get WeeChat at http://weechat.org.\n\n"
              "Error: Failed to import weechat module.")

