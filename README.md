# About #
linktitle.py is a script for [WeeChat](http://weechat.org/) that
automatically fetches titles for links that are posted in chats.

# Installation #
To install linktitle.py you just need to copy it to your
~/.weechat/python directory and load it via `/python load
python/linktitle.py` inside WeeChat.

Full example:

    $ git clone git://github.com/dirkd/weechat-linktitle.git
    $ cp weechat-linktitle/linktitle.py ~/.weechat/python/

    # now change to your running WeeChat and do:
    /python load python/linktitle.py

To automatically load the script when starting WeeChat create a
symbolic link to the file in the WeeChat's autoload directory
(~/.weechat/python/autoload).

Example:

    $ ln -s ../linktitle.py ~/.weechat/python/autoload/

# Contributing #
To contribute to the project [fork it on GitHub](
http://github.com/dirkd/weechat-linktitle "linktitle.py on GitHub")
and send pull requests.

# Known Bugs #
No known bugs, but probably quite some unknown

