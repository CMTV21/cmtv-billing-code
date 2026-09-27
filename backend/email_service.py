import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, List
from datetime import datetime
import logging
import asyncio
import os

logger = logging.getLogger(__name__)

class EmailService:
    """Email notification service with logging and unsubscribe management"""
    
    def __init__(self, smtp_host: str, smtp_port: int, smtp_username: str, 
                 smtp_password: str, from_email: str, from_name: str = "Digital Services",
                 email_logger=None, unsubscribe_manager=None, db=None, branding=None,
                 email_provider: str = "smtp", email_provider_config: dict = None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.from_email = from_email
        # Use SMTP from_name first, then branding site_name, then default
        self.from_name = from_name or (branding.get("site_name") if branding else None) or "Digital Services"
        
        # Email provider: "smtp", "resend", "postmark", "mailgun", "mandrill"
        self.email_provider = email_provider or "smtp"
        self.email_provider_config = email_provider_config or {}
        
        # Enabled if SMTP is configured OR an API provider is configured
        if self.email_provider == "smtp":
            self.enabled = bool(smtp_host and smtp_username and smtp_password)
        else:
            self.enabled = bool(self._provider_has_credentials())
        
        if not self.enabled and from_email:
            # Check API providers even without SMTP
            if self.email_provider != "smtp" and self._provider_has_credentials():
                self.enabled = True
        
        # Integration with logging and unsubscribe
        self.email_logger = email_logger
        self.unsubscribe_manager = unsubscribe_manager
        self.db = db
        
        # Get backend public URL for unsubscribe links
        self.backend_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001"))
    
    def _provider_has_credentials(self) -> bool:
        """Check if the selected API provider has required credentials"""
        p = self.email_provider
        c = self.email_provider_config
        if p == "resend":
            return bool(c.get("resend_api_key"))
        elif p == "postmark":
            return bool(c.get("postmark_server_token"))
        elif p == "mailgun":
            return bool(c.get("mailgun_api_key") and c.get("mailgun_domain"))
        elif p == "mandrill":
            return bool(c.get("mandrill_api_key"))
        return False
    
    def _get_email_header(self, title: str) -> str:
        """Common email header - clean, professional, spam-filter friendly"""
        return f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #1a56db; padding: 24px 20px; text-align: center;">
            <tr><td align="center">
                <h1 style="color: #ffffff; margin: 0; font-size: 22px; font-weight: 600;">{title}</h1>
            </td></tr>
        </table>
        """
    
    def _get_email_footer(self, company_name: str = "Digital Services", recipient_email: str = "", email_type: str = "transactional") -> str:
        """Common email footer - spam compliant"""
        footer = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f9fafb; padding: 16px 20px; text-align: center; border-top: 1px solid #e5e7eb;">
            <tr><td align="center">
                <p style="color: #6b7280; margin: 0; font-size: 13px;">
                    {company_name}
                </p>
            </td></tr>
        </table>
        """
        
        if email_type == "marketing" and recipient_email:
            unsubscribe_url = f"{self.backend_url}/api/unsubscribe?email={recipient_email}"
            footer = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f9fafb; padding: 16px 20px; text-align: center; border-top: 1px solid #e5e7eb;">
            <tr><td align="center">
                <p style="color: #6b7280; margin: 0; font-size: 13px;">{company_name}</p>
                <p style="margin-top: 8px; font-size: 11px;">
                    <a href="{unsubscribe_url}" style="color: #6b7280; text-decoration: underline;">Unsubscribe</a>
                </p>
            </td></tr>
        </table>
            """
        
        return footer
    
    def _wrap_email(self, content: str, title: str = "", recipient_email: str = "", email_type: str = "transactional") -> str:
        """Wrap email - looks like a plain personal email to bypass spam filters"""
        footer = ""
        if email_type == "marketing" and recipient_email:
            unsub = f"{self.backend_url}/api/unsubscribe?email={recipient_email}"
            footer = f'<p><small><a href="{unsub}">Unsubscribe</a></small></p>'
        
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
{content}
{footer}
</body>
</html>"""
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text for multipart emails"""
        import re
        text = html
        # Remove style/script blocks
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        # Convert line breaks
        text = re.sub(r'<br\s*/?\s*>', '\n', text)
        # Convert paragraphs and divs to newlines
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'</div>', '\n', text)
        text = re.sub(r'</tr>', '\n', text)
        text = re.sub(r'</h[1-6]>', '\n', text)
        # Extract link text with URL
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'\2: \1', text)
        # Remove all remaining tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode entities
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&#\d+;', '', text)
        text = re.sub(r'&[a-zA-Z]+;', '', text)
        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(line for line in lines if line)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    
    async def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str, 
        text_content: Optional[str] = None,
        email_type: str = "transactional",
        template_type: Optional[str] = None,
        customer_id: Optional[str] = None,
        order_id: Optional[str] = None,
        sent_by: Optional[str] = None,
        recipient_name: str = "",
        attachments: List[str] = []
    ) -> bool:
        """Send email via configured provider (SMTP or API)"""
        
        if not self.enabled:
            logger.warning(f"Email not sent (not configured): {subject} to {to_email}")
            return False
        
        # Check if user is unsubscribed (skip for auth-critical emails like verification)
        if self.unsubscribe_manager and template_type not in ("email_verification", "password_reset"):
            if email_type == "marketing":
                can_send = await self.unsubscribe_manager.can_send_marketing(to_email)
                if not can_send:
                    logger.info(f"Email not sent to {to_email} - unsubscribed from marketing")
                    return False
            elif email_type == "transactional":
                can_send = await self.unsubscribe_manager.can_send_transactional(to_email)
                if not can_send:
                    logger.info(f"Email not sent to {to_email} - unsubscribed from all emails")
                    return False
        
        # Generate plain text if not provided
        plain_text = text_content or self._html_to_text(html_content)
        
        # Log email before sending
        log_id = None
        if self.email_logger:
            try:
                log_id = await self.email_logger.log_email(
                    recipient_email=to_email,
                    subject=subject,
                    html_content=html_content,
                    email_type=email_type,
                    template_type=template_type,
                    customer_id=customer_id,
                    order_id=order_id,
                    sent_by=sent_by,
                    recipient_name=recipient_name,
                    text_content=plain_text
                )
            except Exception as e:
                logger.error(f"Failed to log email: {str(e)}")
        
        # Route through API provider if not SMTP
        if self.email_provider != "smtp":
            try:
                from email_providers import send_via_provider
                logger.info(f"Sending via {self.email_provider} to {to_email}: {subject}")
                success = await send_via_provider(
                    provider=self.email_provider,
                    config=self.email_provider_config,
                    from_email=self.from_email,
                    from_name=self.from_name,
                    to_email=to_email,
                    subject=subject,
                    html=html_content,
                    text=plain_text
                )
                if success and self.email_logger and log_id:
                    try:
                        await self.email_logger.mark_sent(log_id)
                    except Exception:
                        pass
                elif not success and self.email_logger and log_id:
                    try:
                        await self.email_logger.mark_failed(log_id, f"{self.email_provider} send failed")
                    except Exception:
                        pass
                return success
            except Exception as e:
                logger.error(f"API provider send failed: {e}")
                if self.email_logger and log_id:
                    try:
                        await self.email_logger.mark_failed(log_id, str(e))
                    except Exception:
                        pass
                return False
        
        try:
            import email.utils
            import email.charset
            import uuid
            
            has_attachments = bool(attachments)
            
            # Set charset to use quoted-printable instead of base64
            cs = email.charset.Charset('utf-8')
            cs.body_encoding = email.charset.QP
            
            # Generate clean boundary (not Python's default =============== format)
            boundary_id = uuid.uuid4().hex
            
            if has_attachments:
                message = MIMEMultipart('mixed', boundary=f"mixed-{boundary_id}")
                msg_alternative = MIMEMultipart('alternative', boundary=f"alt-{boundary_id}")
            else:
                message = MIMEMultipart('alternative', boundary=f"alt-{boundary_id}")
                msg_alternative = message
            
            message['Subject'] = subject
            message['From'] = f"{self.from_name} <{self.from_email}>"
            message['To'] = to_email
            message['Date'] = email.utils.formatdate(localtime=True)
            domain = self.from_email.split('@')[-1] if '@' in self.from_email else 'localhost'
            message['Message-ID'] = f"<{uuid.uuid4()}@{domain}>"
            
            # Always include plain text (generate from HTML if not provided)
            plain_text = text_content or self._html_to_text(html_content)
            
            # Create parts with quoted-printable encoding and no extra MIME-Version
            text_part = MIMEText(plain_text, 'plain', _charset=cs)
            del text_part['MIME-Version']
            html_part = MIMEText(html_content, 'html', _charset=cs)
            del html_part['MIME-Version']
            
            msg_alternative.attach(text_part)
            msg_alternative.attach(html_part)
            
            if has_attachments:
                del msg_alternative['MIME-Version']
                message.attach(msg_alternative)
            
            # Add attachments if any
            if attachments:
                from email.mime.base import MIMEBase
                from email import encoders
                import os
                
                for file_path in attachments:
                    if os.path.exists(file_path):
                        try:
                            with open(file_path, 'rb') as f:
                                part = MIMEBase('application', 'octet-stream')
                                part.set_payload(f.read())
                                encoders.encode_base64(part)
                                filename = os.path.basename(file_path)
                                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                                message.attach(part)
                        except Exception as e:
                            logger.error(f"Failed to attach file {file_path}: {str(e)}")
            
            # Determine SSL/TLS settings based on port
            # Use from_email domain as EHLO hostname (avoids random container hostname)
            ehlo_domain = self.from_email.split('@')[-1] if '@' in self.from_email else 'localhost'
            logger.info(f"Attempting to send email via {self.smtp_host}:{self.smtp_port}")
            
            if self.smtp_port == 465:
                # Use SSL/TLS (implicit encryption)
                await aiosmtplib.send(
                    message,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_username,
                    password=self.smtp_password,
                    use_tls=True,
                    start_tls=False,
                    local_hostname=ehlo_domain
                )
            else:
                # Use STARTTLS for port 587 and others (Gmail, etc.)
                smtp_client = aiosmtplib.SMTP(
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    use_tls=False,
                    start_tls=False,
                    local_hostname=ehlo_domain
                )
                async with smtp_client:
                    await smtp_client.starttls()
                    await smtp_client.login(self.smtp_username, self.smtp_password)
                    await smtp_client.send_message(message)
            
            logger.info(f"Email sent successfully to {to_email}: {subject}")
            
            # Mark as sent in log
            if self.email_logger and log_id:
                try:
                    await self.email_logger.mark_sent(log_id)
                except Exception as e:
                    logger.error(f"Failed to mark email as sent: {str(e)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Email sending failed to {to_email}: {str(e)}")
            logger.error(f"SMTP config: host={self.smtp_host}, port={self.smtp_port}, user={self.smtp_username}")
            
            # Mark as failed in log
            if self.email_logger and log_id:
                try:
                    await self.email_logger.mark_failed(log_id, str(e))
                except Exception as log_error:
                    logger.error(f"Failed to mark email as failed: {str(log_error)}")
            
            return False
    
    async def send_bulk_email(
        self, 
        recipients: List[Dict[str, str]], 
        subject: str, 
        html_content: str,
        email_type: str = "marketing",
        sent_by: str = None
    ) -> Dict[str, int]:
        """Send email to multiple recipients with rate limiting and personalization"""
        sent = 0
        failed = 0
        errors = []
        
        for recipient in recipients:
            email = recipient.get("email")
            name = recipient.get("name", "")
            customer_id = recipient.get("customer_id")
            
            # Personalize content FIRST
            personalized_content = html_content.replace("{{name}}", name)
            personalized_content = personalized_content.replace("{{customer_name}}", name)
            personalized_content = personalized_content.replace("{{email}}", email)
            
            personalized_subject = subject.replace("{{name}}", name)
            personalized_subject = personalized_subject.replace("{{customer_name}}", name)
            personalized_subject = personalized_subject.replace("{{email}}", email)
            
            # THEN wrap with email template (includes unsubscribe link per recipient)
            wrapped_content = self._wrap_email(
                personalized_content,
                personalized_subject,
                recipient_email=email,
                email_type=email_type
            )
            
            success = await self.send_email(
                to_email=email,
                subject=personalized_subject,
                html_content=wrapped_content,
                email_type=email_type,
                customer_id=customer_id,
                recipient_name=name,
                sent_by=sent_by
            )
            
            if success:
                sent += 1
            else:
                failed += 1
                errors.append({"email": email, "error": "Send failed"})
            
            # Rate limiting - small delay between emails
            await asyncio.sleep(0.1)
        
        return {
            "sent": sent,
            "failed": failed,
            "errors": errors
        }

    # Template-specific email methods
    
    async def send_order_confirmation(
        self,
        customer_email: str,
        customer_name: str,
        order_id: str,
        amount: float,
        product_name: str,
        duration: int,
        customer_id: str = None
    ):
        """Send order confirmation email using template"""
        if self.db is None:
            logger.error("Database not configured for template emails")
            return False
        
        # Get template
        template = await self.db.email_templates.find_one({
            "template_type": "order_confirmation",
            "is_active": True
        })
        
        if not template:
            logger.error("Order confirmation template not found")
            return False
        
        # Replace variables
        variables = {
            "customer_name": customer_name,
            "order_id": order_id,
            "amount": f"{amount:.2f}",
            "product_name": product_name,
            "duration": str(duration)
        }
        
        subject = template["subject"]
        content = template["html_content"]
        
        for key, value in variables.items():
            subject = subject.replace(f"{{{{{key}}}}}", value)
            content = content.replace(f"{{{{{key}}}}}", value)
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="order_confirmation",
            customer_id=customer_id,
            order_id=order_id,
            recipient_name=customer_name
        )
    
    async def send_service_activated(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        username: str,
        password: str,
        streaming_url: str,
        max_connections: int,
        expiry_date: str,
        customer_id: str = None
    ):
        """Send service activated email with credentials"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "service_activated",
            "is_active": True
        })
        
        if not template:
            return False
        
        variables = {
            "customer_name": customer_name,
            "service_name": service_name,
            "username": username,
            "password": password,
            "streaming_url": streaming_url,
            "max_connections": str(max_connections),
            "expiry_date": expiry_date,
            "dashboard_link": f"{self.backend_url}/dashboard"
        }
        
        subject = template["subject"]
        content = template["html_content"]
        
        for key, value in variables.items():
            subject = subject.replace(f"{{{{{key}}}}}", value)
            content = content.replace(f"{{{{{key}}}}}", value)
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="service_activated",
            customer_id=customer_id,
            recipient_name=customer_name
        )
    

    async def send_vpn_activated(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        vpn_username: str,
        vpn_password: str,
        expiry_date: str,
        max_devices: int = 5,
        customer_id: str = None
    ):
        """Send VPN service activated email with credentials and download links"""
        subject = f"Your VPN Service is Active — {service_name}"
        
        content = f"""
<p style="font-size:15px;color:#374151;line-height:1.6;">Hi {customer_name},</p>
<p style="font-size:15px;color:#374151;line-height:1.6;">Your VPN service <strong>{service_name}</strong> is now active! Here are your credentials and setup instructions.</p>

<div style="background:#f0fdfa;border:1px solid #99f6e4;border-radius:8px;padding:20px;margin:20px 0;">
<h3 style="margin:0 0 12px 0;color:#0d9488;font-size:16px;">Your VPN Credentials</h3>
<table style="width:100%;border-collapse:collapse;">
<tr><td style="padding:6px 0;color:#6b7280;font-size:14px;width:120px;">Username:</td><td style="padding:6px 0;font-weight:bold;color:#111827;font-size:14px;font-family:monospace;">{vpn_username}</td></tr>
<tr><td style="padding:6px 0;color:#6b7280;font-size:14px;">Password:</td><td style="padding:6px 0;font-weight:bold;color:#111827;font-size:14px;font-family:monospace;">{vpn_password}</td></tr>
<tr><td style="padding:6px 0;color:#6b7280;font-size:14px;">Max Devices:</td><td style="padding:6px 0;font-weight:bold;color:#111827;font-size:14px;">{max_devices}</td></tr>
<tr><td style="padding:6px 0;color:#6b7280;font-size:14px;">Expires:</td><td style="padding:6px 0;font-weight:bold;color:#111827;font-size:14px;">{expiry_date}</td></tr>
</table>
</div>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:20px;margin:20px 0;">
<h3 style="margin:0 0 12px 0;color:#2563eb;font-size:16px;">Download VPN Client</h3>
<table style="width:100%;border-collapse:collapse;">
<tr><td style="padding:8px 0;font-size:14px;"><strong>Windows:</strong></td><td style="padding:8px 0;"><a href="https://vpnclient.app/current/vpnclient/vpnclient.exe" style="color:#2563eb;text-decoration:none;">Download .exe</a></td></tr>
<tr><td style="padding:8px 0;font-size:14px;"><strong>Mac:</strong></td><td style="padding:8px 0;"><a href="https://vpnclient.app/current/vpnclient/vpnclient.dmg" style="color:#2563eb;text-decoration:none;">Download .dmg</a></td></tr>
<tr><td style="padding:8px 0;font-size:14px;"><strong>Ubuntu:</strong></td><td style="padding:8px 0;"><a href="https://vpnclient.app/current/vpnclient/vpnclient.run" style="color:#2563eb;text-decoration:none;">Download .run</a></td></tr>
<tr><td style="padding:8px 0;font-size:14px;"><strong>iOS:</strong></td><td style="padding:8px 0;"><a href="https://apps.apple.com/app/id1506797696" style="color:#2563eb;text-decoration:none;">App Store</a></td></tr>
<tr><td style="padding:8px 0;font-size:14px;"><strong>Android:</strong></td><td style="padding:8px 0;"><a href="https://play.google.com/store/apps/details?id=com.vpn.client" style="color:#2563eb;text-decoration:none;">Google Play</a> &nbsp;|&nbsp; <a href="https://vpnclient.app/apk/VPNClient.apk" style="color:#2563eb;text-decoration:none;">Direct APK</a></td></tr>
</table>
</div>

<div style="background:#fefce8;border:1px solid #fde68a;border-radius:8px;padding:16px;margin:20px 0;">
<h3 style="margin:0 0 8px 0;color:#92400e;font-size:14px;">Quick Setup</h3>
<ol style="margin:0;padding-left:20px;color:#374151;font-size:14px;line-height:1.8;">
<li>Download and install the VPN client for your device</li>
<li>Open the app and enter your username and password above</li>
<li>Select a server and connect — you're protected!</li>
</ol>
</div>

<p style="font-size:14px;color:#6b7280;line-height:1.6;">If you have any questions, please contact our support team.</p>
"""
        
        wrapped = self._wrap_email(content, f"VPN Service Active — {service_name}", customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped,
            email_type="transactional",
            template_type="vpn_activated",
            customer_id=customer_id,
            recipient_name=customer_name
        )

    async def send_payment_received(
        self,
        user_email: str,
        user_name: str,
        order_id: str,
        total: float,
        payment_method: str = "Manual"  # CMTV local change 2026-09-25: the real method (was always "Manual")
    ):
        """Send payment received email using template"""
        if self.db is None:
            # Fallback to simple email if no DB
            content = f"""
            <h2>Payment Received</h2>
            <p>Hi {user_name},</p>
            <p>We have received your payment of <strong>${total:.2f}</strong> for order #{order_id}.</p>
            <p>Thank you for your payment!</p>
            """
            
            return await self.send_email(
                to_email=user_email,
                subject=f"Payment Received - ${total:.2f}",
                html_content=self._wrap_email(content, "Payment Received", user_email, "transactional"),
                email_type="transactional",
                recipient_name=user_name
            )
        
        # Get template from database
        template = await self.db.email_templates.find_one({
            "template_type": "payment_received",
            "is_active": True
        })
        
        if not template:
            logger.warning("Payment received template not found, using fallback")
            # Fallback to simple email
            content = f"""
            <h2>Payment Received</h2>
            <p>Hi {user_name},</p>
            <p>We have received your payment of <strong>${total:.2f}</strong> for order #{order_id}.</p>
            <p>Thank you for your payment!</p>
            """
            
            return await self.send_email(
                to_email=user_email,
                subject=f"Payment Received - ${total:.2f}",
                html_content=self._wrap_email(content, "Payment Received", user_email, "transactional"),
                email_type="transactional",
                recipient_name=user_name
            )
        
        # Use template with variable replacement
        subject = template["subject"].replace("{{amount}}", f"{total:.2f}").replace("{{order_id}}", order_id)
        content = template["html_content"]
        content = content.replace("{{customer_name}}", user_name)
        content = content.replace("{{amount}}", f"{total:.2f}")
        content = content.replace("{{order_id}}", order_id)
        content = content.replace("{{payment_method}}", payment_method or "Manual")
        content = content.replace("{{payment_date}}", datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        
        wrapped_content = self._wrap_email(content, template["name"], user_email, "transactional")
        
        return await self.send_email(
            to_email=user_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="payment_received",
            customer_id=None,
            order_id=order_id,
            recipient_name=user_name
        )
    
    async def send_reseller_activated(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        username: str,
        password: str,
        panel_url: str,
        credits: int,
        expiry_date: str,
        customer_id: str = None
    ):
        """Send reseller panel activated email"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "reseller_activated",
            "is_active": True
        })
        
        if not template:
            # Fallback email
            content = f"""
            <h2>Your Reseller Panel is Ready!</h2>
            <p>Hi {customer_name},</p>
            <p>Your reseller panel has been activated with <strong>{credits} credits</strong>.</p>
            <p><strong>Panel URL:</strong> {panel_url}</p>
            <p><strong>Username:</strong> {username}</p>
            <p><strong>Password:</strong> {password}</p>
            <p><strong>Credits:</strong> {credits}</p>
            <p>Login to your panel and start creating subscriber accounts!</p>
            """
            
            return await self.send_email(
                to_email=customer_email,
                subject=f"Reseller Panel Activated - {credits} Credits",
                html_content=self._wrap_email(content, "Reseller Activated", customer_email, "transactional"),
                email_type="transactional",
                customer_id=customer_id,
                recipient_name=customer_name
            )
        
        # Use template
        variables = {
            "customer_name": customer_name,
            "panel_url": panel_url,
            "username": username,
            "password": password,
            "credits": str(credits),
            "expiry_date": expiry_date
        }
        
        # Replace variables in template
        subject = template["subject"]
        content = template["html_content"]
        
        for key, value in variables.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))
            subject = subject.replace(f"{{{{{key}}}}}", str(value))
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="reseller_activated",
            customer_id=customer_id,
            recipient_name=customer_name
        )

    async def send_email_verification(
        self,
        customer_email: str,
        customer_name: str,
        verification_link: str,
        customer_id: str = None
    ):
        """Send email verification - uses hardcoded clean template to avoid spam filters"""
        logger.info(f"send_email_verification: START for {customer_email}")
        logger.info(f"send_email_verification: enabled={self.enabled}, smtp_host={self.smtp_host}, from={self.from_email}")
        
        if not self.enabled:
            logger.error(f"send_email_verification: SMTP not enabled, aborting")
            return False
        
        content = f"""<p>Hi {customer_name},</p>
<p>Please confirm your email address by clicking the link below:</p>
<p><a href="{verification_link}">Confirm my email</a></p>
<p>Or copy this link into your browser:<br>{verification_link}</p>
<p>This link expires in 24 hours.</p>"""
        plain = f"Hi {customer_name},\n\nPlease confirm your email:\n\n{verification_link}\n\nThis link expires in 24 hours."
        
        logger.info(f"send_email_verification: calling send_email to {customer_email}")
        try:
            result = await self.send_email(
                to_email=customer_email,
                subject=f"Confirm your email",
                html_content=self._wrap_email(content, "", customer_email, "transactional"),
                text_content=plain,
                email_type="transactional",
                template_type="email_verification",
                customer_id=customer_id,
                recipient_name=customer_name
            )
            logger.info(f"send_email_verification: send_email returned {result}")
            return result
        except Exception as e:
            logger.error(f"send_email_verification: EXCEPTION in send_email: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def send_password_reset(
        self,
        customer_email: str,
        customer_name: str,
        reset_link: str,
        customer_id: str = None,
        account_label: str = ""
    ):
        """Send password reset link (CMTV local change 2026-09-24) - hardcoded clean template like email verification"""
        if not self.enabled:
            logger.error(f"send_password_reset: email not enabled, aborting")
            return False

        from html import escape
        name, account = escape(customer_name or ""), escape(account_label or customer_email)
        greeting = f"Hi {name}," if name else "Hi,"
        content = f"""<p>{greeting}</p>
<p>We received a request to reset the password for your account <strong>{account}</strong> on our billing website. Click the link below to choose a new password:</p>
<p><a href="{reset_link}">Reset my password</a></p>
<p>Or copy this link into your browser:<br>{reset_link}</p>
<p>This link expires in 1 hour and can only be used once. It changes the password you use to sign in to our website only; your TV line / app login does not change.</p>
<p>If you didn't ask to reset your password, you can ignore this email; your password won't change.</p>"""
        plain = (f"{'Hi ' + customer_name + ',' if customer_name else 'Hi,'}\n\n"
                 f"To reset the password for your account {account_label or customer_email} on our billing website, visit:\n\n{reset_link}\n\n"
                 "This link expires in 1 hour and can only be used once. Your TV line / app login does not change.\n"
                 "If you didn't ask for this, ignore this email.")

        try:
            return await self.send_email(
                to_email=customer_email,
                subject="Reset your password",
                html_content=self._wrap_email(content, "", customer_email, "transactional"),
                text_content=plain,
                email_type="transactional",
                template_type="password_reset",
                customer_id=customer_id,
                recipient_name=customer_name
            )
        except Exception as e:
            logger.error(f"send_password_reset: EXCEPTION in send_email: {e}")
            return False

    async def send_cockpit_account(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        username: str,
        password: str,
        expiry_date: str,
        setup_instructions: str = "",
        customer_id: str = None,
        is_trial: bool = False,
        paid_product_name: str = ""
    ):
        """Login details for a new Cockpit account (Stremio / CMTVpn) (CMTV local change 2026-09-24).
        2026-09-25: uses the "cockpit_account" email template (house style, editable in Admin > Email Templates) when
        it exists; the plain version below is the fallback."""
        if not self.enabled:
            return False

        from html import escape
        if self.db is not None:
            template = await self.db.email_templates.find_one({"template_type": "cockpit_account", "is_active": True})
            if template:
                try:
                    return await self._send_cockpit_account_template(
                        template, customer_email, customer_name, service_name, username, password, expiry_date,
                        setup_instructions, customer_id, is_trial, paid_product_name)
                except Exception as e:
                    logger.error(f"send_cockpit_account: template failed ({e}); sending the plain version")
        greeting = f"Hi {escape(customer_name)}," if customer_name else "Hi,"
        steps = escape(setup_instructions or "").replace("\n", "<br>")
        content = f"""<p>{greeting}</p>
<p>Your <strong>{escape(service_name)}</strong> account is ready. Here are your login details:</p>
<p>Username: <strong>{escape(username)}</strong><br>Password: <strong>{escape(password)}</strong><br>Valid until: {escape(expiry_date)}</p>
{f'<p><strong>How to set it up:</strong><br>{steps}</p>' if steps else ''}
<p>You can find these details any time under <strong>My Services</strong> on our website.</p>"""
        plain = (f"{'Hi ' + customer_name + ',' if customer_name else 'Hi,'}\n\n"
                 f"Your {service_name} account is ready.\n\nUsername: {username}\nPassword: {password}\nValid until: {expiry_date}\n"
                 + (f"\nHow to set it up:\n{setup_instructions}\n" if setup_instructions else "")
                 + "\nYou can find these details any time under My Services on our website.")
        try:
            return await self.send_email(
                to_email=customer_email,
                subject=f"Your {service_name} login details",
                html_content=self._wrap_email(content, "", customer_email, "transactional"),
                text_content=plain,
                email_type="transactional",
                template_type="service_activated",
                customer_id=customer_id,
                recipient_name=customer_name
            )
        except Exception as e:
            logger.error(f"send_cockpit_account: EXCEPTION in send_email: {e}")
            return False

    async def _send_cockpit_account_template(self, template, customer_email, customer_name, service_name, username,
                                             password, expiry_date, setup_instructions, customer_id, is_trial,
                                             paid_product_name):
        """Fill the "cockpit_account" template (CMTV local change 2026-09-25). Setup instructions become numbered
        steps (lines starting "1." etc.; other lines are shown as notes under them)."""
        import re
        from html import escape
        try:
            nice_date = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d").strftime("%B %-d, %Y")
        except ValueError:
            nice_date = str(expiry_date)
        steps, notes = [], []
        for line in str(setup_instructions or "").splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^(\d+)[.)]\s*(.*)$", line)
            (steps if m else notes).append(escape(m.group(2) if m else line.lstrip("*").strip()))
        badge = ('<span style="display:inline-block; width:22px; height:22px; line-height:22px; text-align:center; '
                 'background-color:#0a0e1a; border-radius:6px; color:#00e5ff; font-size:12px; font-weight:bold; '
                 'font-family:Arial, Helvetica, sans-serif;">{n}</span>')
        rows = "".join(
            f'<tr><td width="28" valign="top" style="padding-top:1px;">{badge.format(n=i + 1)}</td>'
            f'<td style="padding-bottom:14px; font-size:14px; line-height:1.6; color:#374151;">{s}</td></tr>'
            for i, s in enumerate(steps))
        setup_html = ""
        if rows or notes:
            setup_html = (
                '<table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:18px;"><tr>'
                '<td width="4" style="background-color:#5533ff; border-radius:2px; font-size:1px; line-height:1px;">&nbsp;</td>'
                '<td style="padding-left:12px; font-size:16px; font-weight:bold; color:#0a0e1a; line-height:1;">Getting started</td>'
                '</tr></table>'
                + (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;">{rows}</table>' if rows else "")
                + "".join(f'<p style="margin:0 0 10px; font-size:13px; line-height:1.6; color:#6b7280;">{n}</p>' for n in notes)
                + '<div style="height:20px; line-height:20px; font-size:1px;">&nbsp;</div>')
        name, svc, user_e = escape(customer_name or "there"), escape(service_name), escape(username)
        if is_trial:
            keep = escape(paid_product_name or "the full version")
            heading = f"Your {svc} is ready"
            intro = (f"Your free trial is set up. Enjoy it until <strong style=\"color:#0a0e1a;\">{escape(nice_date)}</strong>.")
            callout = (f"<li>Your trial ends on {escape(nice_date)}</li>"
                       f"<li>To keep it, buy <strong>{keep}</strong> from the Add-ons tab and choose "
                       f"<strong>Extend: {user_e}</strong> at checkout. Your login stays the same.</li>"
                       "<li>Please keep your login details private</li>")
        else:
            heading = f"Your {svc} account is ready"
            intro = "Thanks for choosing CMTV. Your account is set up and ready to use."
            callout = (f"<li>Your subscription is active until {escape(nice_date)}</li>"
                       "<li>You can find these details any time under My Services on our website</li>"
                       "<li>Please keep your login details private</li>")
        values = {
            "customer_name": name, "service_name": svc, "username": user_e, "password": escape(password),
            "expiry_date": escape(nice_date), "dashboard_link": f"{self.backend_url}/services",
            "heading": heading, "intro": intro, "setup_steps": setup_html, "notes": callout,
        }
        subject, content = template.get("subject") or "Your {{service_name}} login details", template["html_content"]
        for k, v in values.items():
            content = content.replace("{{" + k + "}}", v)
            subject = subject.replace("{{" + k + "}}", re.sub(r"<[^>]+>", "", v))
        plain = (f"Hi {customer_name or 'there'},\n\n{re.sub(r'<[^>]+>', '', intro)}\n\n"
                 f"Service: {service_name}\nUsername: {username}\nPassword: {password}\nValid until: {nice_date}\n"
                 + (f"\nGetting started:\n{setup_instructions}\n" if setup_instructions else "")
                 + (f"\nTo keep it, buy {paid_product_name or 'the full version'} from the Add-ons tab and choose "
                    f"Extend: {username} at checkout.\n" if is_trial else "")
                 + "\nYou can find these details any time under My Services on our website.")
        return await self.send_email(
            to_email=customer_email, subject=subject,
            html_content=self._wrap_email(content, template.get("name", ""), customer_email, "transactional"),
            text_content=plain, email_type="transactional", template_type="cockpit_account",
            customer_id=customer_id, recipient_name=customer_name)

    async def send_password_changed(
        self,
        customer_email: str,
        customer_name: str,
        customer_id: str = None,
        account_label: str = ""
    ):
        """Confirm a completed password reset (CMTV local change 2026-09-24), so an unexpected reset gets noticed"""
        if not self.enabled:
            return False

        from html import escape
        name, account = escape(customer_name or ""), escape(account_label or customer_email)
        greeting = f"Hi {name}," if name else "Hi,"
        content = f"""<p>{greeting}</p>
<p>The password for your account <strong>{account}</strong> on our billing website was just changed using a password reset link.</p>
<p>If this was you, there's nothing else to do.</p>
<p>If you did <strong>not</strong> do this, please contact support straight away.</p>"""
        plain = (f"{'Hi ' + customer_name + ',' if customer_name else 'Hi,'}\n\n"
                 f"The password for your account {account_label or customer_email} on our billing website was just changed "
                 "using a password reset link.\n\nIf this was you, there's nothing else to do. "
                 "If you did NOT do this, please contact support straight away.")

        try:
            return await self.send_email(
                to_email=customer_email,
                subject="Your password was changed",
                html_content=self._wrap_email(content, "", customer_email, "transactional"),
                text_content=plain,
                email_type="transactional",
                template_type="password_reset",
                customer_id=customer_id,
                recipient_name=customer_name
            )
        except Exception as e:
            logger.error(f"send_password_changed: EXCEPTION in send_email: {e}")
            return False

    async def send_ticket_closed(
        self,
        customer_email: str,
        customer_name: str,
        ticket_id: str,
        ticket_subject: str = "",
        customer_id: str = None
    ):
        """Tell the customer their support ticket was closed (CMTV local change 2026-09-26: server.py called this
        method but it never existed, so the email always failed). Template "ticket_closed" (house style, editable in
        Admin > Email Templates) with a plain fallback."""
        if not self.enabled:
            return False
        from html import escape
        ref = str(ticket_id)[-8:].upper()
        name = (customer_name or "").split(" ")[0] or "there"
        site = self.backend_url
        values = {"customer_name": escape(name), "ticket_id": escape(ref), "ticket_subject": escape(ticket_subject or "your request"),
                  "ticket_link": f"{site}/tickets"}
        plain = (f"Hi {name},\n\nYour support ticket #{ref} (\"{ticket_subject}\") has been closed.\n\n"
                 f"Still need help? Open a new ticket at {site}/tickets or message @Cmtv_support_bot on Telegram.\n\n"
                 "The CMTV Support Team")
        template = None
        if self.db is not None:
            template = await self.db.email_templates.find_one({"template_type": "ticket_closed", "is_active": True})
        if template:
            subject, content = template.get("subject") or "Your support ticket #{{ticket_id}} is closed", template["html_content"]
            for k, v in values.items():
                content = content.replace("{{" + k + "}}", v)
                subject = subject.replace("{{" + k + "}}", v)
            html = self._wrap_email(content, template.get("name", ""), customer_email, "transactional")
        else:
            subject = f"Your support ticket #{ref} is closed"
            html = self._wrap_email(
                f"<p>Hi {values['customer_name']},</p><p>Your support ticket <strong>#{values['ticket_id']}</strong> "
                f"(\"{values['ticket_subject']}\") has been closed.</p><p>Still need help? "
                f"<a href=\"{values['ticket_link']}\">Open a new ticket</a> or message @Cmtv_support_bot on Telegram.</p>",
                "", customer_email, "transactional")
        try:
            return await self.send_email(
                to_email=customer_email, subject=subject, html_content=html, text_content=plain,
                email_type="transactional", template_type="ticket_closed",
                customer_id=customer_id, recipient_name=customer_name)
        except Exception as e:
            logger.error(f"send_ticket_closed: EXCEPTION in send_email: {e}")
            return False

    async def send_order_cancelled(
        self,
        customer_email: str,
        customer_name: str,
        order_id: str,
        reason: str = "",
        customer_id: str = None,
        items: list = None,
        total: float = 0.0,
        credits_returned: float = 0.0
    ):
        """Tell the customer an unpaid order was cancelled (CMTV local change 2026-09-26: server.py called this
        method but it never existed, so the email always failed). Uses the "order_cancelled" template (house style,
        editable in Admin > Email Templates) with a plain fallback."""
        if not self.enabled:
            return False
        from html import escape
        ref = f"#{str(order_id)[:8]}"
        names = [str(i.get("product_name") or "").strip() for i in (items or []) if i.get("product_name")]
        item_text = ", ".join(names) or "your order"
        name = (customer_name or "").split(" ")[0] or "there"
        credit_line = (f"<li>The ${credits_returned:.2f} of account credit you used has been returned to your account</li>"
                       if credits_returned > 0 else "")
        values = {
            "customer_name": escape(name), "order_id": escape(ref), "items": escape(item_text),
            "total": f"{float(total or 0):.2f}", "reason": escape(reason or ""), "credits_note": credit_line,
            "shop_link": f"{self.backend_url}/",
        }
        plain = (f"Hi {name},\n\nYour order {ref} ({item_text}, ${float(total or 0):.2f}) has been cancelled. "
                 "You haven't been charged for it.\n"
                 + (f"The ${credits_returned:.2f} of account credit you used has been returned.\n" if credits_returned > 0 else "")
                 + f"\nIf you still want it, you can place a new order any time: {self.backend_url}/\n"
                 "Questions? Just reply to this email.\n\nThe CMTV Support Team")
        template = None
        if self.db is not None:
            template = await self.db.email_templates.find_one({"template_type": "order_cancelled", "is_active": True})
        if template:
            subject, content = template.get("subject") or "Your order {{order_id}} was cancelled", template["html_content"]
            for k, v in values.items():
                content = content.replace("{{" + k + "}}", v)
                subject = subject.replace("{{" + k + "}}", v)
            html = self._wrap_email(content, template.get("name", ""), customer_email, "transactional")
        else:
            subject = f"Your order {ref} was cancelled"
            html = self._wrap_email(
                f"<p>Hi {values['customer_name']},</p><p>Your order <strong>{values['order_id']}</strong> "
                f"({values['items']}, ${values['total']}) has been cancelled. You haven't been charged for it.</p>"
                + (f"<ul>{credit_line}</ul>" if credit_line else "")
                + f"<p>If you still want it, you can <a href=\"{values['shop_link']}\">place a new order</a> any time.</p>",
                "", customer_email, "transactional")
        try:
            return await self.send_email(
                to_email=customer_email, subject=subject, html_content=html, text_content=plain,
                email_type="transactional", template_type="order_cancelled",
                customer_id=customer_id, order_id=str(order_id), recipient_name=customer_name)
        except Exception as e:
            logger.error(f"send_order_cancelled: EXCEPTION in send_email: {e}")
            return False

    async def send_welcome_email(
        self,
        customer_email: str,
        customer_name: str,
        customer_id: str = None
    ):
        """Send welcome email using template"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "welcome",
            "is_active": True
        })
        
        if not template:
            logger.warning("Welcome email template not found")
            return False
        
        # Use template with variable replacement
        subject = template["subject"]
        content = template["html_content"]
        
        # Replace all variables
        content = content.replace("{{customer_name}}", customer_name)
        content = content.replace("{{company_name}}", self.from_name)
        content = content.replace("{{dashboard_link}}", f"{self.backend_url}/dashboard")
        subject = subject.replace("{{company_name}}", self.from_name)
        subject = subject.replace("{{customer_name}}", customer_name)
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="welcome",
            customer_id=customer_id,
            recipient_name=customer_name
        )
    
    async def send_service_renewed(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        username: str,
        new_expiry_date: str,
        customer_id: str = None
    ):
        """Send service renewed email using template"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "service_renewed",
            "is_active": True
        })
        
        if not template:
            logger.warning("Service renewed template not found")
            return False
        
        # Use template
        subject = template["subject"]
        subject = subject.replace("{{service_name}}", service_name)
        subject = subject.replace("{{customer_name}}", customer_name)
        content = template["html_content"]
        content = content.replace("{{customer_name}}", customer_name)
        content = content.replace("{{service_name}}", service_name)
        content = content.replace("{{username}}", username)
        content = content.replace("{{new_expiry_date}}", new_expiry_date)
        
        text_content = template.get("text_content", "")
        if text_content:
            text_content = text_content.replace("{{customer_name}}", customer_name)
            text_content = text_content.replace("{{service_name}}", service_name)
            text_content = text_content.replace("{{username}}", username)
            text_content = text_content.replace("{{new_expiry_date}}", new_expiry_date)
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            text_content=text_content,
            email_type="transactional",
            template_type="service_renewed",
            customer_id=customer_id,
            recipient_name=customer_name
        )
    
    async def send_expiry_warning(
        self,
        customer_email: str,
        customer_name: str,
        service_name: str,
        expiry_date: str,
        days_remaining: int,
        renewal_link: str = "",
        customer_id: str = None
    ):
        """Send service expiry warning email"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "service_expiry_warning",
            "is_active": True
        })
        
        variables = {
            "customer_name": customer_name,
            "service_name": service_name,
            "expiry_date": expiry_date,
            "days_remaining": str(days_remaining),
            "renewal_link": renewal_link or f"{self.backend_url}/dashboard",
        }
        
        if template:
            subject = template["subject"]
            content = template["html_content"]
            for key, value in variables.items():
                subject = subject.replace(f"{{{{{key}}}}}", value)
                content = content.replace(f"{{{{{key}}}}}", value)
            wrapped = self._wrap_email(content, template["name"], customer_email, "transactional")
        else:
            subject = f"Your service expires in {days_remaining} day{'s' if days_remaining != 1 else ''}!"
            content = f"""
            <h2>Service Expiry Reminder</h2>
            <p>Hi {customer_name},</p>
            <p>Your service <strong>{service_name}</strong> will expire in <strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong> on {expiry_date}.</p>
            <p style="margin: 2rem 0;">
                <a href="{variables['renewal_link']}" style="background: #3b82f6; color: white; padding: 12px 30px; text-decoration: none; border-radius: 8px; display: inline-block;">Renew Now</a>
            </p>
            <p>Don't lose access — renew today to keep your service active!</p>
            """
            wrapped = self._wrap_email(content, "Expiry Warning", customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped,
            email_type="transactional",
            template_type="service_expiry_warning",
            customer_id=customer_id,
            recipient_name=customer_name
        )

    async def send_credits_added(
        self,
        customer_email: str,
        customer_name: str,
        username: str,
        credits: int,
        customer_id: str = None
    ):
        """Send credits added email using template"""
        if self.db is None:
            return False
        
        template = await self.db.email_templates.find_one({
            "template_type": "credits_added",
            "is_active": True
        })
        
        if not template:
            logger.warning("Credits added template not found")
            return False
        
        # Use template
        subject = template["subject"]
        subject = subject.replace("{{credits}}", str(credits))
        
        content = template["html_content"]
        content = content.replace("{{customer_name}}", customer_name)
        content = content.replace("{{username}}", username)
        content = content.replace("{{credits}}", str(credits))
        
        wrapped_content = self._wrap_email(content, template["name"], customer_email, "transactional")
        
        return await self.send_email(
            to_email=customer_email,
            subject=subject,
            html_content=wrapped_content,
            email_type="transactional",
            template_type="credits_added",
            customer_id=customer_id,
            recipient_name=customer_name
        )

# Global email service instance
_email_service = None


def get_email_service(smtp_settings: dict, email_logger=None, unsubscribe_manager=None, db=None, branding=None,
                      email_provider: str = "smtp", email_provider_config: dict = None):
    """Get or create email service instance"""
    global _email_service
    
    # For API providers, we don't need SMTP host
    if email_provider == "smtp" and not smtp_settings.get("host"):
        # Check if an API provider is configured
        if not email_provider_config:
            return None
    
    _email_service = EmailService(
        smtp_host=smtp_settings.get("host", ""),
        smtp_port=smtp_settings.get("port", 587),
        smtp_username=smtp_settings.get("username", ""),
        smtp_password=smtp_settings.get("password", ""),
        from_email=smtp_settings.get("from_email", "") or email_provider_config.get("from_email", "") if email_provider_config else smtp_settings.get("from_email", ""),
        from_name=smtp_settings.get("from_name", "Digital Services"),
        email_logger=email_logger,
        unsubscribe_manager=unsubscribe_manager,
        db=db,
        branding=branding,
        email_provider=email_provider,
        email_provider_config=email_provider_config or {}
    )
    
    return _email_service
