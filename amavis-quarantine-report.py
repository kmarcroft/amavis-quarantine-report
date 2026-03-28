#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import getopt
import configparser
import time
import glob
import stat
import os
import re
import gzip
import base64
import locale
import pathlib
import datetime
import email
import email.utils
import email.parser
import email.mime.text
import smtplib
import subprocess
from dateutil import parser
from datetime import date, datetime, timedelta
from email.policy import EmailPolicy
from email.header import decode_header

# set locale to system locale
locale.setlocale(locale.LC_ALL, "en_US.utf8")

class ns_dict (dict):
    def __getattr__(self, key):
        return self[key]

class get_config (object):

    _section = "spam_report"
    _types = {
        'spam_glob': '',
        'from_address': '',
        'from_name': '',
	'release_email': '',
        'amavisd_release_bin': '',
        'smtp_server': '',
        'smtp_port': 'int'
    }

    def __init__(self, config_file):
        self._conf = configparser.ConfigParser()
        self._conf.read(config_file)

    def __getattr__(self, key):
        get = getattr(self._conf, "get" + self._types[key])
        return get(self._section, key)


############################################
# get spam from amavis spam folder
############################################
def get_spam(spam_glob):
    def generator():
        time_thresh = (datetime.now() - timedelta(days=1)).timestamp()
        emlparser = email.parser.BytesHeaderParser()
        # loop through all objects in the quarantine
        for match in glob.iglob(spam_glob):
            timestamp = os.stat(match)[stat.ST_CTIME]
            # compare the timestamp against time treshold 
            if timestamp > time_thresh:
                try:
                    # check if file is gzipped
                    if '.gz' in pathlib.Path(match).suffixes:
                        with gzip.open(match, 'rb') as gh:
                            res = emlparser.parse(gh)
                    else:
                        with open(match, 'rb') as fh:
                            res = emlparser.parse(fh)
                except Exception as e:
                    logtime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                    sys.stderr.write("[%s] Skipping %s: %s\n" % (logtime, match, str(e)))
                    continue
                xto = res['X-Envelope-To']
                if xto is None:
                    continue
                yield ns_dict({
                    'date'  : parser.parse(res['Date']) if res['Date'] else datetime.fromtimestamp(timestamp),
                    'to'    : str(res['To']),
                    'frm'   : str(res['From']),
                    'subj'  : str(res['Subject']),
                    'id'    : match.split("virusmails/", 1)[1] if "virusmails/" in match else os.path.basename(match),
                    'score' : res['X-Spam-Score'],
                    'xto'   : xto,
                    'time'  : timestamp
                })
    return list(generator())


############################################
# make report header
############################################
def make_report_header(logo, datestr, total):
    header = \
"""
<html>
<head>
<meta charset="utf-8"/>
<style>
h2 { margin-bottom:0px; }
table { width:100%s; }
th { background-color:#aaa; height:30px; }
td { background-color:#ddd; min-height:10px; }
.logo { position:absolute; top:10px; right:60px; }
</style>
</head>
<body>
<img class="logo" width="150" height"50" src="data:image/png;base64,%s">
<h2>Quarantine Report for %s</h2>
<p>Messages in Quarantine last 24h:  %d</p>
<table>
<tr>
<th>Date</th>
<th>Sender</th>
<th>Recipient</th>
<th>Subject</th>
<th>Action</th>
</tr>
"""
    header = header % ('%', logo, datestr, total)
    return header.strip()


############################################
# make report entries (spams)
############################################
def make_report_entry(spam, release_email):
    entry = \
"""
<tr>
<td>%s</td>
<td>%s</td>
<td>%s</td>
<td>%s</td>
<td align="center">
<a href="mailto:%s?subject=x-amavis-release:%s" style="font-weight:bold; text-decoration:none; color:green;">&#8667; Release</a>
</td>
"""
    entry = entry % (spam.date.strftime("%a., %d.%m. %H:%M:%S"), spam.frm, spam.to, spam.subj[:40], release_email, spam.id)
    return entry.strip()


############################################
# make report body
############################################
def make_report_body(spam_list, release_email):
    return "\n\n".join(make_report_entry(s, release_email) for s in spam_list)


############################################
# make report footer
############################################
def make_report_footer():
    return """
	   </table>
	   <br/>
	   </body>
	   </html>
	   """


############################################
# make report out of subs
############################################
def make_report(spam_list, conf, mbox):
    datestr = datetime.now().strftime("%A, %d. %B %Y")
    spam_list = sorted(spam_list, key=lambda s: float(s.score) if s.score else 0.0)
    total_size = len(spam_list)
    pwd = os.path.dirname(os.path.realpath(__file__))
    try:
        logo = base64.b64encode(open(pwd + "/logo.png", "rb").read()).decode("utf-8")
    except FileNotFoundError:
        logo = ""
    msg = email.mime.text.MIMEText(make_report_header(logo, datestr, total_size)
                                   + make_report_body(spam_list, conf.release_email)
                                   + make_report_footer(), 'html', "utf-8")

    msg['From'] = "%s <%s>" % (conf.from_name, conf.from_address)
    msg['To'] = "%s <%s>" % (mbox, mbox)
    msg['Subject'] = "Quarantine Report for %s" % str(mbox)
    msg['Date'] = email.utils.formatdate(localtime=1)
    msg.policy = EmailPolicy()
    return msg


############################################
# send report via smtp
############################################
def send_report(report, conf, mbox):
    #mbox = [mbox] + ['test@yourcorp.com']
    try:
        with smtplib.SMTP(conf.smtp_server, conf.smtp_port) as conn:
            conn.sendmail(conf.from_address, mbox, report.as_string())
            conn.quit()
    except smtplib.SMTPDataError as e:
        logtime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        sys.stderr.write("[%s] Failed to send report to %s: SMTP error %d %s\n" % (logtime, mbox, e.smtp_code, e.smtp_error))
    except smtplib.SMTPException as e:
        logtime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        sys.stderr.write("[%s] Failed to send report to %s: %s\n" % (logtime, mbox, str(e)))


############################################
# generate spam reports
############################################
def do_spam_reports(conf):
    # first we have to build a list of all mailboxes
    # that have received atleast one spam
    spams = get_spam(conf.spam_glob)
    mboxes = []
    for spam in spams:
        if spam['xto'] not in mboxes:
            mboxes.append(spam['xto'])

    # afterwards we can generate the reports and send
    # them to each user which has some spam quartined
    for mbox in mboxes:
        # filter spam list by current mailbox
        # filter by x-envelope-to (xto) instead of To: header (=more reliable)
        spam_user = [s for s in spams if str(mbox) in str(s['xto'])]
        # only send report if spam exists for mailbox
        if len(spam_user) > 0:
            logtime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            print ("[%s] Sending report to %s with %d object(s) in Quarantine" % (logtime, mbox, len(spam_user)))
            rept = make_report(spam_user, conf, mbox)
            send_report(rept, conf, mbox)


############################################
# release mail from amavis quarantine
############################################
def do_spam_release(conf):
    msg = email.message_from_file(sys.stdin)
    subj = msg['Subject']
    if subj and "x-amavis-release" in subj:
        qmid = str(subj.split(":")[1]).rstrip()
        logtime = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        print ("[%s] Released spam %s from quarantine by user" % (logtime, qmid))
        subprocess.Popen(['sudo', conf.amavisd_release_bin, qmid])
        sys.exit(0)


############################################
############################################
############################################
def main():

    # check for config file
    pwd = os.path.dirname(os.path.realpath(__file__))
    config_file = pwd + "/config.ini"
    if os.path.isfile(config_file):
        conf = get_config(config_file)
    else:
        sys.stderr.write("Missing config file config.ini!\n")
        sys.exit(1)

    # help menu
    def show_help():
       print("Usage: " + sys.argv[0] + ' --send-reports | --release | --help')
       sys.exit(2)

    # check opts and args 
    try:
       opts, args = getopt.getopt(sys.argv[1:], "srh", ['send-reports', 'release', 'help'])
    except getopt.GetoptError as err:
       show_help()

    # no opt given
    if len(sys.argv)==1:
        show_help()

    # execute
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            show_help()
        elif opt in ("--send-reports"):
            do_spam_reports(conf)
        elif opt in ("--release"):
            do_spam_release(conf)
        else:
            assert False, "unhandled option"

if __name__ == "__main__":
    main()
