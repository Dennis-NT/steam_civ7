#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送文明7数据监测邮件
- 正常情况：发送附件给指定收件人
- 附件缺失：发送报错提醒给发件人
"""

import os
import smtplib
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from dotenv import load_dotenv


def load_config():
    """从 .env 加载邮件配置"""
    load_dotenv()
    return {
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": int(os.getenv("SMTP_PORT", 25)),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_use_tls": os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"),
        "email_from": os.getenv("EMAIL_FROM", ""),
        "email_to": os.getenv("EMAIL_TO", ""),
    }


def send_email(config, subject, body, to_addrs, attachments=None):
    """
    发送邮件
    :param config: 邮件配置字典
    :param subject: 邮件主题
    :param body: 邮件正文（HTML）
    :param to_addrs: 收件人列表
    :param attachments: 附件路径列表
    :return: 是否成功
    """
    msg = MIMEMultipart()
    msg["From"] = config["email_from"]
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "html", "utf-8"))

    if attachments:
        for file_path in attachments:
            if not os.path.isfile(file_path):
                continue
            part = MIMEBase("application", "octet-stream")
            with open(file_path, "rb") as f:
                part.set_payload(f.read())
            encoders.encode_base64(part)
            filename = os.path.basename(file_path)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            msg.attach(part)

    # 判断连接方式：465/994 端口通常走 SSL；587/25 端口走 TLS(starttls)
    use_ssl = config["smtp_port"] in (465, 994)

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=30)
        else:
            server = smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30)
            if config["smtp_use_tls"]:
                server.starttls()

        # 调试日志（如需详细日志，可在 .env 加 SMTP_DEBUG=1）
        if os.getenv("SMTP_DEBUG", "0") == "1":
            server.set_debuglevel(1)

        if config["smtp_user"] and config["smtp_password"]:
            server.login(config["smtp_user"], config["smtp_password"])

        server.sendmail(config["email_from"], to_addrs, msg.as_string())
        server.quit()
        print(f"邮件发送成功 -> {', '.join(to_addrs)}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"邮件发送失败: 认证错误，请检查 SMTP_USER / SMTP_PASSWORD（126邮箱需填授权码而非登录密码）")
        print(f"详细错误: {e}")
        return False
    except smtplib.SMTPServerDisconnected as e:
        print(f"邮件发送失败: 服务器断开连接。若使用 465 端口，应走 SSL；若使用 587/25 端口，应走 TLS(starttls)。")
        print(f"详细错误: {e}")
        return False
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False


def main():
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    today_cn = now.strftime("%Y年%m月%d日")

    comments_file = os.path.join("output", f"comments_{today}.csv")
    count_words_file = os.path.join("output", f"count_words_{today}.csv")

    config = load_config()

    # 检查附件是否都存在
    missing = []
    if not os.path.isfile(comments_file):
        missing.append(comments_file)
    if not os.path.isfile(count_words_file):
        missing.append(count_words_file)

    if missing:
        # 附件缺失，发送报错提醒给发件人
        error_body = f"""
        <html>
        <body>
            <h3>数据监测邮件发送异常提醒</h3>
            <p><b>日期：</b>{today_cn}</p>
            <p><b>异常说明：</b>以下附件缺失，未能发送正常数据监测邮件：</p>
            <ul>
                {''.join([f'<li>{f}</li>' for f in missing])}
            </ul>
            <p>请检查数据生成流程。</p>
        </body>
        </html>
        """
        send_email(
            config,
            subject="【异常】文明7岁月洗礼版数据监测邮件发送失败",
            body=error_body,
            to_addrs=["shendan001@126.com"],
        )
    else:
        # 附件齐全，发送正常邮件
        # 收件人：.env 中的 EMAIL_TO + 新增的两位
        recipients = []
        if config["email_to"]:
            recipients.extend([addr.strip() for addr in config["email_to"].split(",") if addr.strip()])
        recipients.extend(["kaka.xu@r2acgn.com", "zoe.zuo@r2acgn.com"])
        # 去重并保持顺序
        seen = set()
        unique_recipients = []
        for r in recipients:
            if r.lower() not in seen:
                seen.add(r.lower())
                unique_recipients.append(r)

        body = f"""
        <html>
        <body>
            <p>您好，</p>
            <p>{today_cn} 文明7岁月洗礼版数据监测报告请查收，详见附件。</p>
            <br>
            <p>祝好</p>
        </body>
        </html>
        """
        send_email(
            config,
            subject="文明7岁月洗礼版数据监测",
            body=body,
            to_addrs=unique_recipients,
            attachments=[comments_file, count_words_file],
        )


if __name__ == "__main__":
    main()
