"""
E-Mail sender for forgotten passwords and invitations.
"""
import logging
import smtplib
import ssl
from collections import namedtuple

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

from app.lib import config


def get_smtp_config():
    smtp_config_keys = ['host', 'username', 'password', 'sender', 'port', 'starttls']

    cfg_data = {}

    for key in smtp_config_keys:
        value = config.get(f"smtp_{key}", default_value=None, raise_missing=False)
        cfg_data[key] = value
    if cfg_data['sender'] is None or cfg_data['sender'] == "":
        cfg_data['sender'] = cfg_data['username']

    if cfg_data['starttls'] is not None and \
            cfg_data['starttls'].lower() in ['true', 'y', 'yes', '1']:
        cfg_data['starttls'] = True
    else:
        cfg_data['starttls'] = False

    if cfg_data['port'] is None or cfg_data['port'] == "":
        cfg_data['port'] = "465"

    EmailConfiguration = namedtuple("EmailConfiguration",
                                    smtp_config_keys)

    cfg = EmailConfiguration(*[cfg_data.get(key, None) for key in smtp_config_keys])

    return cfg


def is_available():
    smtp_host = get_smtp_config().host
    return smtp_host is not None and smtp_host != ""


def send(recipient, subject, body):
    mail_server = None
    try:
        mail_cfg = get_smtp_config()
        if mail_cfg.host is None:
            raise Exception("smtp_host not configured. email sending unavailable.")
        logging.debug("email::send %s", recipient)

        ssl_context = ssl.create_default_context()
        if mail_cfg.starttls:
            mail_server = smtplib.SMTP(mail_cfg.host,
                                       mail_cfg.port)
            mail_server.starttls(context=ssl_context)
        else:
            mail_server = smtplib.SMTP_SSL(mail_cfg.host,
                                           mail_cfg.port,
                                           context=ssl_context)
        logging.debug("email::connected")

        mail_server.login(mail_cfg.username,
                          mail_cfg.password)
        logging.debug("email::login_success")

        msg = MIMEMultipart("alternative")
        msg.set_charset("utf-8")
        msg['Subject'] = Header(subject.encode("utf-8"), "utf-8")
        msg['From'] = mail_cfg.sender
        msg['To'] = recipient
        part = MIMEText(body.encode("utf-8"), _charset="UTF-8")
        msg.attach(part)

        resp = mail_server.sendmail(mail_cfg.sender,
                                    recipient,
                                    msg.as_string())
        logging.debug(f"email::sent {mail_cfg.sender} -> {recipient}")
        if resp is not None and len(resp) > 0:
            logging.debug(f"email::response {mail_cfg.sender} -> {recipient}: {str(resp)}")

        mail_server.quit()
    except Exception as e:
        logging.exception(e)
        raise Exception(f"Failed to send email to recipient {recipient}, reason: {str(e)}")
    finally:
        if mail_server is not None:
            mail_server.close()
            logging.debug("email::close")
