# amavis-quarantine-report

## Credits

This work was inspired by https://github.com/le1ca/spam-report, which unfortunately did not have the ability for users to release quarantined emails.

## About

This script generates automated HTML email reports for quarantined items in `/var/lib/amavis/virusmails/` on a per-mailbox basis and allows users to release items from quarantine by replying to the report.

Releasing quarantined items works via a mail alias (e.g. `spammgr@yourdomain.com`) by piping incoming messages to the script with the `--release` flag. The generated reports include a release link of the form `mailto:spammgr@yourdomain.com?subject=x-amavis-release:<id>`. No open ports or HTTP server required — releasing is done entirely via email.

Both plain and gzip-compressed quarantine files (`.gz`) are supported.

Tested with amavisd-new 2.10.x and Postfix 3.x.

## Requirements

- Python 3.6+
- [`python-dateutil`](https://pypi.org/project/python-dateutil/)

Install dependencies:

```bash
pip3 install -r requirements.txt
```

## Configuration

Copy or edit `config.ini` and adjust all values for your environment:

| Key | Description |
|---|---|
| `spam_glob` | Glob path to quarantine files (plain or `.gz`) |
| `from_name` | Display name used in report sender header |
| `from_address` | Email address used as the report sender |
| `release_email` | Alias address that receives release commands |
| `amavisd_release_bin` | Full path to the `amavisd-release` binary |
| `smtp_server` | SMTP server hostname for sending reports |
| `smtp_port` | SMTP server port (typically `25` or `587`) |

To avoid the outbound report email being rejected as spam by your own MTA, whitelist the `from_address` in amavis or route the script through a trusted submission path (port 587 / policy bank with `bypass_spam_checks => 1`).

## Install

1. Clone the repo and configure `config.ini`:

    ```bash
    git clone https://github.com/yourorg/amavis-quarantine-report /opt/amavis-quarantine-report
    cd /opt/amavis-quarantine-report
    cp config.ini.example config.ini   # edit as needed
    pip3 install -r requirements.txt
    ```

2. Place `logo.png` (150×50 px) in the install directory. The report renders without it if the file is absent.

3. Create a Postfix virtual alias map for the release address:

    ```bash
    echo "spammgr@yourdomain.com spammgr" > /etc/postfix/amavis_qmgr_transport
    postmap /etc/postfix/amavis_qmgr_transport
    ```

4. Add the map to `virtual_alias_maps` in `/etc/postfix/main.cf`:

    ```
    virtual_alias_maps = hash:${config_directory}/amavis_qmgr_transport
    ```

5. Add a system alias in `/etc/aliases` to pipe release commands to the script:

    ```
    # amavis-quarantine-report
    spammgr: "|/usr/bin/python3 /opt/amavis-quarantine-report/amavis-quarantine-report.py --release"
    ```

6. Apply the alias change:

    ```bash
    newaliases
    ```

7. Add a cron job to send daily reports (example: 00:05 every night):

    ```
    5 0 * * * /usr/bin/python3 /opt/amavis-quarantine-report/amavis-quarantine-report.py --send-reports >> /opt/amavis-quarantine-report/report.log 2>&1
    ```

## Usage

```
amavis-quarantine-report.py --send-reports | --release | --help
```

| Flag | Description |
|---|---|
| `--send-reports` | Scan quarantine and email a report to each affected mailbox |
| `--release` | Read a release command from stdin and call `amavisd-release` |
| `--help` | Show usage |

## Todo

- Add a better/safer authentication mechanism for releasing items
- Add multi-language email templates
- Support configurable report time window (currently fixed at 24 h)
