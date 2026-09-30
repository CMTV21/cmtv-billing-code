from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class ServiceLifecycleManager:
    """Manage automated service lifecycle"""
    
    def __init__(self, db, xtream_service=None, email_service=None):
        self.db = db
        self.services = db.services
        self.users = db.users
        self.lifecycle_logs = db.lifecycle_logs
        self.xtream_service = xtream_service
        self.email_service = email_service
    
    async def log_action(self, service_id: str, user_id: str, action: str, reason: str, old_status: str = None, new_status: str = None, triggered_by: str = "system"):
        """Log lifecycle action"""
        await self.lifecycle_logs.insert_one({
            "service_id": service_id,
            "user_id": user_id,
            "action": action,
            "reason": reason,
            "triggered_by": triggered_by,
            "old_status": old_status,
            "new_status": new_status,
            "created_at": datetime.utcnow()
        })
    
    async def auto_provision_service(self, order_id: str, service_id: str):
        """Automatically provision service after payment"""
        service = await self.services.find_one({"_id": service_id})
        if not service:
            return False
        
        # Service should be in pending status
        if service.get("status") != "pending":
            logger.warning(f"Service {service_id} not in pending status")
            return False
        
        try:
            # Create account on XtreamUI panel (if xtream_service available)
            if self.xtream_service:
                # This would call xtream_service to create account
                logger.info(f"Provisioning service {service_id} on XtreamUI panel")
            
            # Update service status to active
            await self.services.update_one(
                {"_id": service_id},
                {"$set": {
                    "status": "active",
                    "activated_at": datetime.utcnow()
                }}
            )
            
            # Log action
            await self.log_action(
                service_id=service_id,
                user_id=service["user_id"],
                action="provision",
                reason="Payment confirmed",
                old_status="pending",
                new_status="active"
            )
            
            # Send service activated email
            if self.email_service:
                user = await self.users.find_one({"_id": service["user_id"]})
                # Would call email_service.send_service_activated(...)
            
            logger.info(f"Service {service_id} auto-provisioned successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to auto-provision service {service_id}: {str(e)}")
            return False
    
    async def auto_suspend_expired_services(self):
        """Suspend all expired services"""
        now = datetime.utcnow()
        
        # Find active services that have expired and belong to billing customers
        suspended_count = 0
        async for service in self.services.find({
            "status": "active",
            "expiry_date": {"$lt": now},
            "user_id": {"$exists": True, "$nin": ["", None]}
        }):
            try:
                # Get user info for notification
                from bson import ObjectId
                uid = service.get("user_id", "")
                user = None
                if uid:
                    try:
                        user = await self.users.find_one({"_id": ObjectId(uid)})
                    except Exception:
                        user = await self.users.find_one({"_id": uid})
                
                # Fallback: use xtream_username as customer name if user not found
                customer_name = "Unknown"
                customer_email = "N/A"
                if user:
                    customer_name = user.get("name", user.get("panel_username", "Unknown"))
                    email = user.get("email", "")
                    customer_email = email if email and not email.endswith("@panel.local") else user.get("panel_username", "N/A")
                elif service.get("xtream_username"):
                    customer_name = service["xtream_username"]
                
                # Suspend service
                await self.services.update_one(
                    {"_id": service["_id"]},
                    {"$set": {
                        "status": "suspended",
                        "suspended_at": now
                    }}
                )
                
                # Log action
                await self.log_action(
                    service_id=str(service["_id"]),
                    user_id=service["user_id"],
                    action="suspend",
                    reason="Service expired",
                    old_status="active",
                    new_status="suspended"
                )
                
                # Send Telegram notification
                try:
                    from server import send_telegram_notification, send_email_notification, send_sms_notification
                    await send_telegram_notification(
                        "service_expired",
                        f"⏰ *Service Expired*\n\nCustomer: {customer_name}\nEmail: {customer_email}\nService: {service.get('product_name', 'Unknown')}\nExpired: {service.get('expiry_date').strftime('%Y-%m-%d %H:%M') if service.get('expiry_date') else 'N/A'}\n\nService has been automatically suspended."
                    )
                    await send_email_notification(
                        "service_expired",
                        "Service Expired",
                        f"Customer: {customer_name}\nEmail: {customer_email}\nService: {service.get('product_name', 'Unknown')}\nExpired: {service.get('expiry_date').strftime('%Y-%m-%d %H:%M') if service.get('expiry_date') else 'N/A'}\n\nService has been automatically suspended."
                    )
                    await send_sms_notification("service_expired", f"Service expired: {customer_name} - {service.get('product_name', 'Unknown')}")
                except Exception as notif_error:
                    logger.error(f"Failed to send notification for expired service: {str(notif_error)}")
                
                suspended_count += 1
                logger.info(f"Auto-suspended service {service['_id']} (expired)")
                
            except Exception as e:
                logger.error(f"Failed to suspend service {service['_id']}: {str(e)}")
        
        return suspended_count
    
    async def auto_cancel_long_suspended(self, days: int = 30):
        """Cancel services suspended for more than N days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        cancelled_count = 0
        async for service in self.services.find({
            "status": "suspended",
            "suspended_at": {"$lt": cutoff_date}
        }):
            try:
                await self.services.update_one(
                    {"_id": service["_id"]},
                    {"$set": {
                        "status": "cancelled",
                        "cancelled_at": datetime.utcnow()
                    }}
                )
                
                await self.log_action(
                    service_id=str(service["_id"]),
                    user_id=service["user_id"],
                    action="cancel",
                    reason=f"Suspended for {days}+ days",
                    old_status="suspended",
                    new_status="cancelled"
                )
                
                cancelled_count += 1
                
            except Exception as e:
                logger.error(f"Failed to cancel service {service['_id']}: {str(e)}")
        
        return cancelled_count
    
    async def send_expiry_warnings(self, days_before: int = 7):
        """Send warnings for services expiring soon — email + Telegram"""
        target_date = datetime.utcnow() + timedelta(days=days_before)
        start_of_target_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_target_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        warned_count = 0
        
        # Only warn for services that belong to billing system customers (have valid user_id)
        # Skip services from panel syncs that aren't linked to billing customers
        async for service in self.services.find({
            "status": "active",
            "expiry_date": {
                "$gte": start_of_target_day,
                "$lte": end_of_target_day
            },
            "user_id": {"$exists": True, "$nin": ["", None]},
            # CMTV local change 2026-09-25: no "expiring" warning when PayPal auto-renew will renew it
            "auto_renew.status": {"$ne": "ACTIVE"}
        }):
            # Check if already warned for this period
            recent_warning = await self.lifecycle_logs.find_one({
                "service_id": str(service["_id"]),
                "action": f"expiry_warning_{days_before}d",
                "created_at": {"$gte": datetime.utcnow() - timedelta(hours=20)}
            })
            
            if recent_warning:
                continue
            
            try:
                from bson import ObjectId
                uid = service.get("user_id", "")
                user = None
                if uid:
                    try:
                        user = await self.users.find_one({"_id": ObjectId(uid)})
                    except Exception:
                        user = await self.users.find_one({"_id": uid})
                
                customer_name = "Customer"
                customer_email = ""
                if user:
                    customer_name = user.get("name", user.get("panel_username", "Customer"))
                    email = user.get("email", "")
                    customer_email = email if email and not email.endswith("@panel.local") else ""
                else:
                    # No billing customer found — skip (not our user)
                    continue

                expiry_str = service.get("expiry_date").strftime("%Y-%m-%d") if service.get("expiry_date") else "N/A"
                service_name = service.get("product_name", "Unknown Service")

                # Send email if user has a real email
                if self.email_service and customer_email:
                    try:
                        await self.email_service.send_expiry_warning(
                            customer_email=customer_email,
                            customer_name=customer_name,
                            service_name=service_name,
                            expiry_date=expiry_str,
                            days_remaining=days_before,
                            customer_id=uid,
                        )
                    except Exception as e:
                        logger.warning(f"Expiry warning email failed for {customer_email}: {e}")

                # Send Telegram notification
                try:
                    from server import send_telegram_notification, send_email_notification, send_sms_notification
                    await send_telegram_notification(
                        "service_expiry_warning",
                        f"⚠️ *Service Expiring in {days_before} Day{'s' if days_before != 1 else ''}*\n\nCustomer: {customer_name}\nEmail: {customer_email or 'N/A'}\nService: {service_name}\nExpires: {expiry_str}"
                    )
                    await send_email_notification(
                        "service_expiry_warning",
                        f"Service Expiring in {days_before} Day{'s' if days_before != 1 else ''}",
                        f"Customer: {customer_name}\nEmail: {customer_email or 'N/A'}\nService: {service_name}\nExpires: {expiry_str}"
                    )
                    await send_sms_notification("service_expiry_warning", f"Service expiring in {days_before} days: {customer_name} - {service_name}")
                except Exception:
                    pass

                # Log warning
                await self.log_action(
                    service_id=str(service["_id"]),
                    user_id=uid,
                    action=f"expiry_warning_{days_before}d",
                    reason=f"Service expires in {days_before} days"
                )
                
                warned_count += 1
                
            except Exception as e:
                logger.error(f"Failed to send expiry warning for service {service['_id']}: {str(e)}")
        
        return warned_count

    async def check_panel_credits(self, low_threshold: int = 10):
        """Check panel credit balances and send Telegram alerts if low"""
        try:
            settings_col = self.db.settings
            settings = await settings_col.find_one()
            if not settings:
                return

            alerts = []

            # Check XtreamUI panels (they use credits for user creation)
            for i, panel in enumerate(settings.get("xtream", {}).get("panels", [])):
                name = panel.get("name", f"XtreamUI Panel {i+1}")
                # XtreamUI doesn't expose credits via API easily, skip
                pass

            # Check 1-Stream panels
            for i, panel in enumerate(settings.get("onestream", {}).get("panels", [])):
                name = panel.get("name", f"1-Stream Panel {i+1}")
                try:
                    from onestream_service import get_onestream_service
                    svc = get_onestream_service(panel)
                    if svc:
                        info = svc.get_account_info()
                        if info.get("success"):
                            credits = info.get("credits", 0)
                            if isinstance(credits, (int, float)) and credits < low_threshold:
                                alerts.append(f"*{name}*: {credits} credits remaining")
                except Exception as e:
                    logger.warning(f"Credit check failed for {name}: {e}")

            # Check NXT Dash panels
            for i, panel in enumerate(settings.get("nxtdash", {}).get("panels", [])):
                name = panel.get("name", f"NXT Dash Panel {i+1}")
                try:
                    from nxtdash_service import get_nxtdash_service
                    svc = get_nxtdash_service(panel)
                    if svc:
                        info = await svc.test_connection()
                        if info.get("success"):
                            data = info.get("data", {})
                            credits = data.get("credits", 0)
                            if isinstance(credits, (int, float)) and credits < low_threshold:
                                alerts.append(f"*{name}*: {credits} credits remaining")
                except Exception as e:
                    logger.warning(f"Credit check failed for {name}: {e}")

            # Check Aether panels
            for i, panel in enumerate(settings.get("aether", {}).get("panels", [])):
                name = panel.get("name", f"Aether Panel {i+1}")
                try:
                    from aether_service import get_aether_service
                    svc = get_aether_service(panel)
                    if svc:
                        balance = await svc.get_balance()
                        if balance is not None and balance < low_threshold:
                            alerts.append(f"*{name}*: {balance:g} credits remaining")
                except Exception as e:
                    logger.warning(f"Credit check failed for {name}: {e}")

            # Check Gold panels
            for i, panel in enumerate(settings.get("gold", {}).get("panels", [])):
                name = panel.get("name", f"Gold Panel {i+1}")
                try:
                    from gold_service import get_gold_service
                    svc = get_gold_service(panel)
                    if svc:
                        balance = await svc.get_balance()
                        if balance is not None and balance < low_threshold:
                            alerts.append(f"*{name}*: {balance:g} credits remaining")
                except Exception as e:
                    logger.warning(f"Credit check failed for {name}: {e}")

            if alerts:
                # Check if already alerted recently (once per 6 hours)
                recent = await self.lifecycle_logs.find_one({
                    "action": "credit_low_alert",
                    "created_at": {"$gte": datetime.utcnow() - timedelta(hours=6)}
                })
                if not recent:
                    msg = f"🔴 *Low Panel Credits Alert*\n\n" + "\n".join(alerts) + f"\n\nThreshold: {low_threshold} credits"
                    try:
                        from server import send_telegram_notification, send_email_notification, send_sms_notification
                        await send_telegram_notification("credit_low_alert", msg)
                        await send_email_notification(
                            "credit_low_alert",
                            "Low Panel Credits Alert",
                            "\n".join(alerts) + f"\n\nThreshold: {low_threshold} credits"
                        )
                        await send_sms_notification("credit_low_alert", "\n".join(alerts) + f"\nThreshold: {low_threshold} credits")
                    except Exception:
                        pass
                    await self.log_action(
                        service_id="system", user_id="system",
                        action="credit_low_alert",
                        reason=f"Low credits detected: {'; '.join(alerts)}"
                    )
                    logger.warning(f"Low panel credits: {alerts}")

        except Exception as e:
            logger.error(f"Credit check failed: {e}")

