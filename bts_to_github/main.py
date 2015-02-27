#!/usr/bin/env python

"""
.. module:: main
   :synopsis: Debian BTS to GitHub issues sync

"""

# Released under AGPLv3+ license, see LICENSE

from argparse import ArgumentParser
from collections import OrderedDict
from github import Github, UnknownObjectException
from time import sleep
import yaml
import debianbts
import logging

log = logging.getLogger(__name__)

ABUSE_THROTTLING_TIME = 5

class ParsingError(Exception):
    pass

def setup_logging(debug):
    level = logging.DEBUG if debug else logging.INFO
    log.setLevel(level)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)


def parse_args():
    ap = ArgumentParser()
    ap.add_argument('config_filename')
    ap.add_argument('-d', '--debug', action="store_true")
    ap.add_argument('-s', '--dry-run', action="store_true",
                    help="Simulate/dry-run: do not create/update issues")
    return ap.parse_args()


def load_conf(fn):
    """Load configuration"""
    with open(fn) as f:
        conf = yaml.load(f)

    assert 'repositories' in conf
    assert 'github_api_token' in conf
    return conf


def fetch_bug_summary(bug_num):
    bug = debianbts.get_status(bug_num)
    if not bug:
        raise RuntimeError("No BTS data for #%s" % bug_num)

    return bug[0]


def fetch_bug_numbers_by_package(pkg_name):
    """Fetch non-archived bugs"""
    return debianbts.get_bugs('package', pkg_name, 'archive', 'false')


def extract_msg_id(header):
    header = header.splitlines()
    for line in header:
        if line.startswith(('Message-ID:', 'Message-Id')):
            return line[11:].strip()

    log.error("Message-ID not found in comment:")
    for line in header:
        log.error("    %s", line)
    raise ParsingError


def extract_msg_author(header):
    for line in header.splitlines():
        if line.startswith('From:'):
            return line[5:].strip()


def fetch_bug_log(bug_num):
    """Get a bug log (the sequence of comments) from the BTS

    :returns: Message-ID -> (author, body)  dict
    """
    ordered_bug_log = OrderedDict()
    for b in debianbts.get_bug_log(bug_num):
        try:
            msg_id = extract_msg_id(b['header'])
        except ParsingError:
            continue

        author = extract_msg_author(b['header'])
        ordered_bug_log[msg_id] = (author, b['body'])

    return ordered_bug_log


class BugSyncer(object):
    """Sync Bug reports from the Debian BTS to a GitHub project
    """
    def __init__(self, conf, dryrun=False):
        self.dryrun = dryrun
        self._ghclient = Github(conf['github_api_token'])
        sync_label = conf['sync_label']

        for repo_conf in conf['repositories']:
            debian_pkg_name = repo_conf['debian_pkg']
            github_repo_name = repo_conf['github_repo']
            self.sync(debian_pkg_name, github_repo_name, sync_label)

    def fetch_github_issues_by_repo(self, github_repo, sync_label):
        """Fetch issues from GitHub"""

        g_issues = github_repo.get_issues(
            #assignee='*',
            state='all',
            #labels=[sync_label,],
        )
        g_issues = [i for i in g_issues if sync_label in i.labels]
        log.debug("  %d issues currently on GitHub", len(g_issues))

        issues = {}
        for issue in g_issues:

            try:
                t = issue.title
                assert t[0] == '['
                num = t[1:].split(']', 1)[0]
                num = int(num)
                if num in issues:
                    dup_issue_num = issues[num].number
                    log.error("Duplicate Debian bug %d %d %d", num,
                              dup_issue_num, issue.number)

                issues[num] = issue
            except Exception:
                log.error("Unable to parse %r", t, exc_info=True)
                continue

        log.debug("  %d issues currently on GitHub", len(issues))
        return issues

    def sync(self, debian_pkg_name, github_repo_name, sync_label):
        """Sync bugs from a package to GitHub issues in a repository
        """
        log.debug("Mirroring from %s to %s", debian_pkg_name, github_repo_name)

        bug_numbers = fetch_bug_numbers_by_package(debian_pkg_name)
        log.debug("  %d bugs on the BTS", len(bug_numbers))

        github_repo = self._ghclient.get_repo(github_repo_name)
        self.throttle()

        # get the special label to flag issues generated from the BTS
        try:
            sync_label = github_repo.get_label(sync_label)
            self.throttle()
        except UnknownObjectException:
            log.error("Label %r not found: create such bug label on GitHub",
                      sync_label)
            return

        issues = self.fetch_github_issues_by_repo(github_repo, sync_label)
        log.debug("  %d issues currently on GitHub", len(issues))
        self.throttle()

        for bn in bug_numbers:
            self.sync_bug(bn, debian_pkg_name, issues, github_repo, sync_label)

    def sync_bug(self, bn, debian_pkg_name, issues, github_repo, sync_label):
        """Sync a bug report
        """
        log.info("    processing %s: %d", debian_pkg_name, bn)
        summary = fetch_bug_summary(bn)
        self.throttle()

        # Create the GitHub issue if needed

        if bn in issues:
            # the issue is already on GitHub
            issue = issues[bn]

        elif self.dryrun:
            log.debug("       not creating new issue (dry run)")
            return

        else:
            log.info("       creating new issue")
            issue = github_repo.create_issue(
                "[%d] %s" % (bn, summary.subject),
                labels=[sync_label, ]
            )
            self.throttle_abuse_limit()

        bts_bug_logs = fetch_bug_log(bn)
        self.throttle()
        log.debug("      %d comments on the BTS", len(bts_bug_logs))

        # Create issue comments if needed

        for comment in issue.get_comments():
            first_line = comment.body.splitlines()[0]
            if first_line.startswith('BTS_msg_id:'):
                # This comment on GitHub was created from the BTS
                bts_msg_id = first_line[11:].strip()
                bts_bug_logs.popitem(bts_msg_id)

        log.debug("      %d comments to be created", len(bts_bug_logs))

        for msg_id, comment_data in bts_bug_logs.iteritems():
            # create new comments, hopefully in the correct order
            author, body = comment_data
            newbody = "BTS_msg_id: %s\nBTS author: %s\n\n%s" % \
                (msg_id, author, body)
            if self.dryrun:
                log.debug("    not creating comment (dryrun)")
            else:
                issue.create_comment(newbody)
                self.throttle_abuse_limit()

        # Update issue open/close state if needed

        expected_issue_state = u'closed' if summary.done else u'open'
        if issue.state != expected_issue_state:
            # update needed
            if self.dryrun:
                log.debug("    not setting state to %s (dryrun)", expected_issue_state)

            else:
                log.debug("    setting state to %s", expected_issue_state)
                issue.edit(state=expected_issue_state)
                self.throttle_abuse_limit()


    def throttle(self):
        """Throttle API usage by sleeping after every call
        """
        remaining, total = self._ghclient.rate_limiting
        if remaining < 10:
            log.info("Rate limit critical: Sleeping for 1h!")
            sleep(3600)
        else:
            # Exponential backoff
            sleep_time = total * 0.1 / remaining
            sleep(sleep_time)

    def throttle_abuse_limit(self):
        """Throttle API usage to avoid hitting anti-abuse limits
        """
        sleep(ABUSE_THROTTLING_TIME)


def main():
    args = parse_args()
    setup_logging(args.debug)
    conf = load_conf(args.config_filename)
    BugSyncer(conf, dryrun=args.dry_run)


if __name__ == '__main__':
    main()
