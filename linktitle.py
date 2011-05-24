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

# History:
# 2011-05-24, spezi|Fanta
#   version 0.3: display play time of youtube urls
# 2011-05-24, Bluthund
#   version 0.2: implemented background fetching of urls
# 2011-05-24, Bluthund
#   version 0.1: initial version

from __future__ import print_function

try:
    import weechat
except:
    print("This script is supposed to be run in WeeChat.\n"
          "You can get WeeChat at http://weechat.org.\n\n"
          "Error: Failed to import weechat module.")
    weechat = None

import urllib2
import re
import sys

SCRIPT_NAME    = "linktitle"
SCRIPT_AUTHOR  = "Bluthund <bluthund23@gmail.com>"
SCRIPT_VERSION = "0.3"
SCRIPT_LICENSE = "GPL3"
SCRIPT_DESC    = "Show the title of incoming links."

SCRIPT_PREFIX = "[linktitle]"

TIMEOUT = 3 # seconds

# only fetch link titles for http|https schemas
# no need for the full RFC regex (RFC 1034 & 1738); urllib2 takes care of that
linkRegex = re.compile(r"https?://[^ ]+", re.I)

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

def print_title_cb(buf, cmd, rc, stdout, stderr):
    if stdout != "":
        print_title_cb.resp += stdout

    if rc >= 0:
        body = print_title_cb.resp.translate(None, "\r\n")
        print_title_cb.resp = ""

        if body.lower().find("<title>"):
            title = body[body.lower().find("<title>")+7:body.lower().find("</title>")]
        else:
            title = "No Title"
        title = re.sub(r"\s+", " ", title.strip())
        title = unescape(title)

        # youtube
        play_time = re.search(r'<span class="video-time">(\d+:\d\d)</span>', body);
        if play_time is not None:
            play_time = ' - ' + str(play_time.group(1))
        else:
            play_time = ''

        weechat.prnt(buf, "{pre}\t{0}".format(title.encode("utf-8") + play_time, pre = SCRIPT_PREFIX))

    return weechat.WEECHAT_RC_OK
print_title_cb.resp = ""

def print_link_title(buf, link):
    cmd = "{exe} -c 'try: "\
          "import urllib2; req = urllib2.Request(\"{link}\"); "\
          "req.add_header(\"User-Agent\", \"WeeChat/{ver}\"); "\
          "print urllib2.urlopen(req, None, {timeout}).read(8192)\n"\
          "except: pass'"
    cmd = cmd.format(exe = sys.executable,
                     link = link,
                     ver = weechat.info_get("version", ""),
                     timeout = TIMEOUT)

    weechat.hook_process(cmd, 0, "print_title_cb", buf)

    return weechat.WEECHAT_RC_OK

def link_cb(data, buf, date, tags, displayed, hilight, prefix, message):
    if prefix == SCRIPT_PREFIX:
        return weechat.WEECHAT_RC_OK

    for link in linkRegex.findall(message):
        print_link_title(buf, link)

    return weechat.WEECHAT_RC_OK

if __name__ == "__main__":
    if weechat:
        weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION,
                         SCRIPT_LICENSE, SCRIPT_DESC, "", "")
        weechat.hook_print("", "", "://", 1, "link_cb", "")
