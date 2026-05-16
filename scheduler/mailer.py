import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class Mailer:
    def __init__(self, config):
        self._config = config

    def send(self, subject: str, body_html: str) -> bool:
        cfg = self._config
        msg = MIMEMultipart('alternative')
        msg['From'] = cfg.SENDER_EMAIL
        msg['To'] = ','.join(cfg.RECEIVER_EMAILS)
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        all_recipients = cfg.RECEIVER_EMAILS + cfg.BCC_EMAILS
        try:
            with smtplib.SMTP(cfg.SMTP_SERVER, cfg.SMTP_PORT, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(cfg.SENDER_EMAIL, cfg.SENDER_PASSWORD)
                smtp.sendmail(cfg.SENDER_EMAIL, all_recipients, msg.as_string())
            print(f"邮件发送成功 -> {', '.join(all_recipients)}")
            return True
        except Exception as e:
            print(f"邮件发送失败: {e}")
            return False
