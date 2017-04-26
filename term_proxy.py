#!/usr/bin/env python

desc = (
'''Run a forign terminal program with the ability to automate some interaction
''')

help_patterns = (
'''Patterns files allow some automation based on the output of the forign
program. The first line of the pattern file should specify a seperator for the
subsequent lines, by using it to seperate the words 'pattern', 'action', and
'translation'. Example, using ' ===== ' as the seperator:
    
    pattern ===== action ===== translation

The file follows these headers; the first element on each line should be a
regular expression pattern, followed by an action, followed by a formatting
string. If a line outputted by the forign program matches the pattern, the
action will be applied. The following actions are supported:
    
    respond: the formatted string will be sent to the forign programs stdin
    replace: the formatted string will be printed instead of the original line
    print: the formatted string will be printed along with the original line
    filter: nothing will be printed
    function: the function named by the formatted string from the
        user_functions file will be called.

The formatting strings will be formatted with numbers in braces replaced by
the group from the expression. Example, using the above seperator:

    login: (w+) ===== replace ===== The user {1} has logged in.

Whenever the forign program prints a login message the more verbose version
will be printed to the screen.
'''
)

import argparse
import os
import re
import readline
import signal
import subprocess
import sys
from fcntl import fcntl, F_GETFL, F_SETFL
from select import select
from time import sleep

import user_functions


def set_nonblocking(fileobj):
    fd = fileobj.fileno()
    flag = fcntl(fd, F_GETFL)
    fcntl(fd, F_SETFL, flag | os.O_NONBLOCK)


COMMAND = object()
OUTPUT = object()

class Forign(subprocess.Popen):
    def __init__(self, args, include_err):
        stderr = subprocess.STDOUT if include_err else None
        super(Forign, self).__init__(args, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=stderr)
        set_nonblocking(self.stdout)

    def sendline(self, line):
        self.stdin.write(''.join((line, '\n')))

    def __iter__(self):
        trfds = [sys.stdin, self.stdout]
        outbuf = ''
        while self.returncode is None:
            try:
                rfds, _, xfds = select(trfds, [], trfds)
            except KeyboardInterrupt:
                self.send_signal(signal.SIGINT)
            if xfds:
                self.poll()
                continue # TODO: handle exceptions?
            if sys.stdin in rfds:
                try:
                    yield (COMMAND, raw_input())
                except EOFError:
                    self.stdin.flush()
                    self.stdin.close()
            if self.stdout in rfds:
                data = self.stdout.read()
                outbuf = ''.join((outbuf, data))
                lines = outbuf.split('\n')
                outbuf = lines[-1]
                if len(lines) > 1:
                    sys.stdout.write('\r')
                for line in lines[:-1]:
                    yield (OUTPUT, line)
                sys.stdout.write(outbuf)
                sys.stdout.flush()
                #readline.redisplay()
                if data == '':
                    self.poll()


RESPOND = object()
REPLACE = object()
FILTER = object()
PRINT = object()
FUNCTION = object()

class Patterns(object):
    flpat = re.compile(r'pattern(.+)action\1translation(\s+.*)?')
    gprefix = 'tpp'
    actions = {
        'respond': RESPOND,
        'replace': REPLACE,
        'filter': FILTER,
        'print': PRINT,
        'function': FUNCTION,
    }
    
    def __init__(self, files):
        self.patterns = []
        self.codes = []
        for pf in files:
            with pf:
                first = pf.readline()
                match = self.flpat.match(first)
                if match is None:
                    pass # TODO: some kind of warning for bad files?
                else:
                    sep = match.group(1)
                    self.add_patterns(line[:-1].split(sep)
                                      for line in pf if sep in line)
        merge = []
        for i, pat in enumerate(self.codes):
            merge.append("(?P<%s%d>%s)" % (self.gprefix, i, pat))
        self.master = re.compile('|'.join(merge))

    def add_patterns(self, patterns):
        for pat, act, trans in patterns:
            try:
                cpat = re.compile(pat)
                act = self.actions[act]
            except re.error, KeyError:
                continue # TODO: warn about error?
            else:
                self.codes.append(pat)
                self.patterns.append((cpat, act, trans))

    def matches(self, string):
        mmatch = self.master.match(string)
        if mmatch:
            for key in mmatch.groupdict().iterkeys():
                if key.startswith(self.gprefix):
                    index = int(key[len(self.gprefix):])
                    pat, act, trans = self.patterns[index]
                    match = pat.match(string)
                    yield (act, trans.format(*match.groups()))


def proxy(ns):
    patterns = Patterns(ns.pattern_files)
    forign = Forign(ns.command, ns.include_err)
    for event, content in forign:
        if event is COMMAND:
            forign.sendline(content)
        elif event is OUTPUT:
            print_ = True
            for action, ncont in patterns.matches(content):
                if action is RESPOND:
                    forign.sendline(ncont)
                elif action is REPLACE:
                    print '\r', ncont
                    print_ = False
                elif action is PRINT:
                    print ncont
                elif action is FILTER:
                    print_ = False
                elif action is FUNCTION:
                    getattr(user_functions, ncont)(content, forign.sendline)
            if print_:
                print '\r', content
                #sys.stdout.write(''.join((ns.prompt, ' ')))
                #sys.stdout.flush()
                #readline.redisplay()
    return 0


def main():
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument('-H', '--pattern-file', action='append',
                        type=argparse.FileType('r'), dest='pattern_files',
                        default=[],
                        help='A file specifying regex patterns for'
                        ' call/response functionality')
    parser.add_argument('--help-patterns', action='version',
                        version=help_patterns,
                        help='Show info on patterns files')
    parser.add_argument('-e', '--include-err', action='store_true',
                        dest='include_err',
                        help='Also apply pattern actions to stderr output')
    parser.add_argument('-l', '--unlined-output', action='store_true',
                        dest='unlined',
                        help='Don\'t assume the forign program always outputs'
                             ' full lines all at once')
    parser.add_argument('-p', '--prompt', action='store',
                        dest='prompt', default='=',
                        help='Change prompt character(s)')
    parser.add_argument('-c', nargs=argparse.REMAINDER, dest='command',
                        help='The command to execute')
    proxy(parser.parse_args())
    


if __name__ == '__main__':
    sys.exit(main())
