#!/usr/bin/env python
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

import HTMLParser
import datetime
import json
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

    contenttype_re = "({0}/{0})(?:;\s*charset=({0}))?".format(token_class)

    def __init__(self):
        self.charset = None
        self.contenttype = None
        HTMLParser.HTMLParser.__init__(self)

    def _process_meta_tag(self, tag, attrs):
        def parse_http_equiv(attrs):
            for _, value in attrs:
                m = re.match(self.contenttype_re, value)
                if m:
                    return m.groups()
            return None, None

        if tag != "meta":
            return

        for name, value in attrs:
            if name == "charset":
                self.charset = value
            elif name == "http-equiv" and value.lower() == "content-type":
                self.contenttype, self.charset = parse_http_equiv(attrs)

    def handle_starttag(self, tag, attrs):
        self._process_meta_tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._process_meta_tag(tag, attrs)

def check_meta_info(headers, body):
    contenttype = None

    if "Content-Type: " in headers:
        pattern = "^Content-Type:\s*{0};?$".format(MetaTagParser.contenttype_re)
        m = re.search(pattern, headers, re.M)

        if m.group(2): # found both: content-type and charset
            return m.groups()
        else:
            contenttype = m.group(1)

    p = MetaTagParser()
    p.contenttype = contenttype
    try:
        p.feed(body)
        p.close()
    except HTMLParser.HTMLParseError:
        pass
    finally:
        return p.contenttype, p.charset

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
    if stdout != "":
        print_title_cb.resp += stdout
    if stderr != "":
        print(stderr)

    if rc >= 0 and len(print_title_cb.resp) > 0:
        resp = print_title_cb.resp
        print_title_cb.resp = ""

        sep = resp.index("\n\n")
        headers = resp[:sep+1]
        body = resp[sep+2:].translate(None, "\r\n")

        contenttype, charset = check_meta_info(headers, body)

        try:
            body = body.decode(charset);
        except TypeError: # charset was None
            pass
        except LookupError: # couldn't find specified input encoding
            # TODO this is actually really bad
            pass # for now

        if "<title>" in body.lower():
            title = body[body.lower().find("<title>")+7:
                         body.lower().find("</title>")]
        else:
            title = "No Title"
        title = re.sub(r"\s+", " ", title.strip())
        title = unescape(title)

        buf = data[:data.find("\t")]
        url = data[data.find("\t")+1:]

        video_duration = get_youtube_video_duration(url)
        if video_duration:
            title += " ({0})".format(video_duration)

        url_cache[url]["title"] = title
        print_to_buffer(buf, title)

    return weechat.WEECHAT_RC_OK
print_title_cb.resp = ""

def print_to_buffer(buf, msg):
    if len(msg) == 0:
        return # do not print empty messages

    msg = msg.encode(weechat_encoding)
    weechat.prnt(buf, "{pre}\t{msg}".format(pre = SCRIPT_PREFIX, msg = msg))

def fetch_url(url, timeout, cb, data):
    # NOTE this function is used via reflection, change with caution;
    #      see below for details
    def fetchit(_SUB_timeout_):
        import urllib2
        import sys
        try:
            req = urllib2.Request("_SUB_url_")
            req.add_header("User-Agent", "WeeChat/_SUB_ver_")
            resp = urllib2.urlopen(req, None, _SUB_timeout_)
            print(resp.info())

            contenttype = resp.info()["Content-Type"]
            if "html" in contenttype or "xml" in contenttype:
                s = ""
                while "</title>" not in s.lower():
                    s += resp.read(1024)
                print(s)
            elif contenttype.startswith("text/plain"):
                print(resp.readline())
        except urllib2.HTTPError, e:
            print(e.info())
            print(e.read())
        except urllib2.URLError, e:
            print(e.reason, file=sys.stderr)

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
    code = re.sub("_SUB_(\w+)_", lambda m: "{%s}" % m.group(1), code)
    code = code.format(url = url,
                       ver = weechat.info_get("version", ""),
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
    for link in re.findall("https?://[^ >]+", message, re.I):
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
