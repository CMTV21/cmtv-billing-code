from datetime import datetime, timedelta
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

class BackgroundJobScheduler:
    """Manage all background jobs and cron tasks"""
    
    def __init__(self, db, lifecycle_manager=None, email_service=None):
        self.db = db
        self.lifecycle_manager = lifecycle_manager
        self.email_service = email_service
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Start all background jobs"""
        logger.info("Starting background job scheduler...")
        
        # Job 1: Check and suspend expired services (every hour)
        self.scheduler.add_job(
            self.job_suspend_expired_services,
            trigger=IntervalTrigger(hours=1),
            id="suspend_expired_services",
            name="Suspend Expired Services",
            replace_existing=True
        )
        
        # Job 2: Send expiry warnings - 7 days (daily at 9 AM)
        self.scheduler.add_job(
            self.job_send_expiry_warnings_7d,
            trigger=CronTrigger(hour=9, minute=0),
            id="send_expiry_warnings_7d",
            name="Send Expiry Warnings (7 days)",
            replace_existing=True
        )
        
        # Job 2b: Send expiry warnings - 3 days (daily at 9 AM)
        self.scheduler.add_job(
            self.job_send_expiry_warnings_3d,
            trigger=CronTrigger(hour=9, minute=15),
            id="send_expiry_warnings_3d",
            name="Send Expiry Warnings (3 days)",
            replace_existing=True
        )
        
        # Job 2c: Send expiry warnings - 1 day (daily at 9 AM)
        self.scheduler.add_job(
            self.job_send_expiry_warnings_1d,
            trigger=CronTrigger(hour=9, minute=30),
            id="send_expiry_warnings_1d",
            name="Send Expiry Warnings (1 day)",
            replace_existing=True
        )
        
        # Job 3: Cancel long-suspended services (daily at 2 AM)
        self.scheduler.add_job(
            self.job_cancel_suspended_services,
            trigger=CronTrigger(hour=2, minute=0),
            id="cancel_suspended_services",
            name="Cancel Long-Suspended Services",
            replace_existing=True
        )
        
        # Job 4: Process scheduled emails (every 5 minutes)
        self.scheduler.add_job(
            self.job_process_scheduled_emails,
            trigger=IntervalTrigger(minutes=5),
            id="process_scheduled_emails",
            name="Process Scheduled Emails",
            replace_existing=True
        )
        
        # Job 5: Clean up old logs (weekly on Sunday at 3 AM)
        self.scheduler.add_job(
            self.job_cleanup_old_logs,
            trigger=CronTrigger(day_of_week='sun', hour=3, minute=0),
            id="cleanup_old_logs",
            name="Cleanup Old Logs",
            replace_existing=True
        )
        
        # Job 6: Payment retry (every 6 hours)
        self.scheduler.add_job(
            self.job_retry_failed_payments,
            trigger=IntervalTrigger(hours=6),
            id="retry_failed_payments",
            name="Retry Failed Payments",
            replace_existing=True
        )
        
        # Job 7: Check panel credits (every 4 hours)
        self.scheduler.add_job(
            self.job_check_panel_credits,
            trigger=IntervalTrigger(hours=4),
            id="check_panel_credits",
            name="Check Panel Credits",
            replace_existing=True
        )
        
        # Job 8: Sync imported users from all panels (every hour, run immediately on start)
        self.scheduler.add_job(
            self.job_sync_imported_users,
            trigger=IntervalTrigger(hours=1),
            id="sync_imported_users",
            name="Sync Imported Users",
            replace_existing=True,
            next_run_time=datetime.utcnow() + timedelta(minutes=2)
        )
        
        # Job 9: Create customer accounts for unlinked imported users (every 30 min, run immediately)
        self.scheduler.add_job(
            self.job_create_customer_accounts,
            trigger=IntervalTrigger(minutes=30),
            id="create_customer_accounts",
            name="Create Customer Accounts for Imported Users",
            replace_existing=True,
            next_run_time=datetime.utcnow() + timedelta(minutes=1)
        )
        
        self.scheduler.start()
        logger.info("Background jobs started successfully")
    
    async def job_suspend_expired_services(self):
        """Suspend services that have expired"""
        try:
            if self.lifecycle_manager:
                count = await self.lifecycle_manager.auto_suspend_expired_services()
                logger.info(f"Auto-suspended {count} expired services")
        except Exception as e:
            logger.error(f"Error in suspend_expired_services job: {str(e)}")
    
    async def job_send_expiry_warnings_7d(self):
        """Send 7-day expiry warnings"""
        try:
            if self.lifecycle_manager:
                count = await self.lifecycle_manager.send_expiry_warnings(7)
                if count > 0:
                    logger.info(f"Sent {count} expiry warnings (7 days)")
        except Exception as e:
            logger.error(f"Error in 7-day expiry warnings: {str(e)}")

    async def job_send_expiry_warnings_3d(self):
        """Send 3-day expiry warnings"""
        try:
            if self.lifecycle_manager:
                count = await self.lifecycle_manager.send_expiry_warnings(3)
                if count > 0:
                    logger.info(f"Sent {count} expiry warnings (3 days)")
        except Exception as e:
            logger.error(f"Error in 3-day expiry warnings: {str(e)}")

    async def job_send_expiry_warnings_1d(self):
        """Send 1-day expiry warnings"""
        try:
            if self.lifecycle_manager:
                count = await self.lifecycle_manager.send_expiry_warnings(1)
                if count > 0:
                    logger.info(f"Sent {count} expiry warnings (1 day)")
        except Exception as e:
            logger.error(f"Error in 1-day expiry warnings: {str(e)}")

    async def job_check_panel_credits(self):
        """Check panel credit balances and alert if low"""
        try:
            if self.lifecycle_manager:
                settings = await self.db.settings.find_one()
                threshold = settings.get("credit_alert_threshold", 10) if settings else 10
                await self.lifecycle_manager.check_panel_credits(low_threshold=threshold)
        except Exception as e:
            logger.error(f"Error in credit check job: {str(e)}")
    
    async def job_cancel_suspended_services(self):
        """Cancel services suspended for 30+ days"""
        try:
            if self.lifecycle_manager:
                count = await self.lifecycle_manager.auto_cancel_long_suspended(days=30)
                logger.info(f"Auto-cancelled {count} long-suspended services")
        except Exception as e:
            logger.error(f"Error in cancel_suspended_services job: {str(e)}")
    
    async def job_process_scheduled_emails(self):
        """Process and send scheduled emails"""
        try:
            now = datetime.utcnow()
            
            # Find emails scheduled for now or earlier
            async for email in self.db.scheduled_emails.find({
                "sent": False,
                "cancelled": False,
                "scheduled_for": {"$lte": now}
            }):
                try:
                    # Send the email (would integrate with email service)
                    logger.info(f"Processing scheduled email: {email['subject']}")
                    
                    # Mark as sent
                    await self.db.scheduled_emails.update_one(
                        {"_id": email["_id"]},
                        {"$set": {"sent": True, "sent_at": now}}
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to send scheduled email {email['_id']}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error in process_scheduled_emails job: {str(e)}")
    
    async def job_cleanup_old_logs(self):
        """Clean up logs older than 90 days"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=90)
            
            # Clean email logs
            email_result = await self.db.email_logs.delete_many({
                "created_at": {"$lt": cutoff_date},
                "status": {"$in": ["sent", "failed"]}  # Keep pending/bounced
            })
            
            # Clean lifecycle logs
            lifecycle_result = await self.db.lifecycle_logs.delete_many({
                "created_at": {"$lt": cutoff_date}
            })
            
            logger.info(f"Cleaned up {email_result.deleted_count} email logs, {lifecycle_result.deleted_count} lifecycle logs")
            
        except Exception as e:
            logger.error(f"Error in cleanup_old_logs job: {str(e)}")
    
    async def job_retry_failed_payments(self):
        """Retry failed payment attempts"""
        try:
            now = datetime.utcnow()
            
            # Find payment retries ready for next attempt
            async for retry in self.db.payment_retries.find({
                "status": "pending",
                "next_retry_at": {"$lte": now},
                "attempt_number": {"$lt": 3}  # Max 3 attempts
            }):
                try:
                    logger.info(f"Retrying payment for order {retry['order_id']} (attempt {retry['attempt_number'] + 1})")
                    
                    # Would attempt payment here
                    # If successful, mark order as paid
                    # If failed, schedule next retry with exponential backoff
                    
                    # Increment attempt
                    await self.db.payment_retries.update_one(
                        {"_id": retry["_id"]},
                        {"$inc": {"attempt_number": 1}}
                    )
                    
                except Exception as e:
                    logger.error(f"Payment retry failed for {retry['order_id']}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error in retry_failed_payments job: {str(e)}")
    
    async def job_sync_imported_users(self):
        """Sync users from all configured panels automatically"""
        try:
            settings = await self.db.settings.find_one()
            if not settings:
                return
            
            from server import (
                get_xtream_service, get_settings, imported_users_collection,
                create_customer_for_imported_user
            )
            from xtreamui_service import XtreamUIService
            
            total_synced = 0
            total_updated = 0
            
            # Sync XtreamUI panels
            xtream_panels = settings.get("xtream", {}).get("panels", [])
            for i, panel in enumerate(xtream_panels):
                if not panel.get("active", True):
                    continue
                try:
                    svc = XtreamUIService(
                        panel_url=panel.get("panel_url", ""),
                        admin_username=panel.get("admin_username", ""),
                        admin_password=panel.get("admin_password", ""),
                        ssl_verify=panel.get("ssl_verify", False),
                        http_basic_user=panel.get("http_basic_user", ""),
                        http_basic_pass=panel.get("http_basic_pass", ""),
                        proxy_url=panel.get("proxy_url", "")
                    )
                    panel_name = panel.get("name", f"Panel {i+1}")
                    
                    # Sync subscribers
                    result = svc.get_reseller_users()
                    if result.get("success"):
                        for user_data in result.get("users", []):
                            username = user_data.get("username", "")
                            if not username:
                                continue
                            from datetime import datetime
                            expiry_date = None
                            exp_str = user_data.get("expiry", "")
                            if exp_str and exp_str not in ["Unlimited", "NEVER", ""]:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                    try:
                                        expiry_date = datetime.strptime(str(exp_str).strip(), fmt)
                                        break
                                    except (ValueError, TypeError):
                                        continue
                            import re
                            max_conn_raw = user_data.get("max_connections", 1)
                            max_conn_str = re.sub(r'<[^>]+>', '', str(max_conn_raw)).strip()
                            m = re.search(r'(\d+)', max_conn_str)
                            max_connections = int(m.group(1)) if m else 1
                            
                            doc = {
                                "username": username,
                                "password": user_data.get("password", ""),
                                "panel_type": "xtream",
                                "panel_index": i,
                                "panel_name": panel_name,
                                "account_type": "subscriber",
                                "max_connections": max_connections,
                                "expiry_date": expiry_date,
                                "status": user_data.get("status", "active"),
                                "last_synced": datetime.utcnow()
                            }
                            r = await imported_users_collection.update_one(
                                {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                                {"$set": doc},
                                upsert=True
                            )
                            if r.upserted_id:
                                total_synced += 1
                            elif r.modified_count:
                                total_updated += 1
                    
                except Exception as e:
                    logger.warning(f"Auto-sync failed for xtream panel {panel.get('name', i)}: {e}")
            
            if total_synced > 0 or total_updated > 0:
                logger.info(f"Auto-sync: {total_synced} new, {total_updated} updated across all panels")
            
            # Sync XuiOne panels
            xuione_panels = settings.get("xuione", {}).get("panels", [])
            for i, panel in enumerate(xuione_panels):
                if not panel.get("active", True):
                    continue
                try:
                    from xuione_service import get_xuione_service
                    xui_svc = get_xuione_service(panel)
                    if not xui_svc:
                        continue
                    panel_name = panel.get("name", f"XuiOne {i+1}")
                    result = xui_svc.get_users()
                    if result.get("success"):
                        for user_data in result.get("users", []):
                            uname = user_data.get("username", "")
                            if not uname:
                                continue
                            exp = None
                            exp_str = user_data.get("expiry", "")
                            if exp_str and exp_str not in ["Unlimited", "NEVER", ""]:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                    try:
                                        exp = datetime.strptime(str(exp_str).strip(), fmt)
                                        break
                                    except Exception:
                                        continue
                            doc = {"username": uname, "password": user_data.get("password", ""), "panel_type": "xuione", "panel_index": i,
                                   "panel_name": panel_name, "account_type": "subscriber", "max_connections": user_data.get("max_connections", 1),
                                   "expiry_date": exp, "status": user_data.get("status", "active"), "last_synced": datetime.utcnow()}
                            r = await imported_users_collection.update_one({"username": uname, "panel_name": panel_name}, {"$set": doc}, upsert=True)
                            if r.upserted_id: total_synced += 1
                            elif r.modified_count: total_updated += 1
                except Exception as e:
                    logger.warning(f"Auto-sync failed for xuione panel {panel.get('name', i)}: {e}")
            
            # Sync 1-Stream panels
            onestream_panels = settings.get("onestream", {}).get("panels", [])
            for i, panel in enumerate(onestream_panels):
                if not panel.get("active", True):
                    continue
                try:
                    from onestream_service import get_onestream_service
                    os_svc = get_onestream_service(panel)
                    if not os_svc:
                        continue
                    panel_name = panel.get("name", f"1-Stream {i+1}")
                    reseller_username = panel.get("admin_username", "").strip()
                    result = os_svc.get_lines()
                    if result.get("success"):
                        for user_data in result.get("users", []):
                            uname = user_data.get("username", "")
                            if not uname:
                                continue
                            # Filter: only direct users
                            line_owner = user_data.get("owner", "").strip()
                            if reseller_username and line_owner and line_owner != reseller_username:
                                continue
                            exp = None
                            exp_str = user_data.get("expiry", "")
                            if exp_str and exp_str not in ["Unlimited", "NEVER", ""]:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                    try:
                                        exp = datetime.strptime(str(exp_str).strip(), fmt)
                                        break
                                    except Exception:
                                        continue
                            doc = {"username": uname, "password": user_data.get("password", ""), "panel_type": "onestream", "panel_index": i,
                                   "panel_name": panel_name, "account_type": "subscriber", "max_connections": user_data.get("max_connections", 1),
                                   "expiry_date": exp, "status": user_data.get("status", "active"), "last_synced": datetime.utcnow()}
                            r = await imported_users_collection.update_one({"username": uname, "panel_name": panel_name}, {"$set": doc}, upsert=True)
                            if r.upserted_id: total_synced += 1
                            elif r.modified_count: total_updated += 1
                except Exception as e:
                    logger.warning(f"Auto-sync failed for onestream panel {panel.get('name', i)}: {e}")
            
            # Sync NXT Dash panels
            nxtdash_panels = settings.get("nxtdash", {}).get("panels", [])
            for i, panel in enumerate(nxtdash_panels):
                if not panel.get("active", True):
                    continue
                try:
                    from nxtdash_service import get_nxtdash_service
                    nd_svc = get_nxtdash_service(panel)
                    if not nd_svc:
                        continue
                    panel_name = panel.get("name", f"NXT Dash {i+1}")
                    page = 1
                    while True:
                        result = await nd_svc.get_lines(page=page)
                        if not result.get("success"):
                            break
                        lines = result.get("lines", [])
                        if not lines:
                            break
                        for line in lines:
                            uname = line.get("username", "")
                            if not uname:
                                continue
                            exp = None
                            exp_ts = line.get("expire_date")
                            if exp_ts and str(exp_ts).isdigit() and int(exp_ts) > 0:
                                from datetime import timezone
                                exp = datetime.fromtimestamp(int(exp_ts), tz=timezone.utc).replace(tzinfo=None)
                            doc = {"username": uname, "password": line.get("password", ""), "panel_type": "nxtdash", "panel_index": i,
                                   "panel_name": panel_name, "account_type": "subscriber", "max_connections": line.get("max_connections", 1),
                                   "expiry_date": exp, "status": "active" if line.get("enabled") else "suspended", "last_synced": datetime.utcnow()}
                            r = await imported_users_collection.update_one({"username": uname, "panel_name": panel_name}, {"$set": doc}, upsert=True)
                            if r.upserted_id: total_synced += 1
                            elif r.modified_count: total_updated += 1
                        if page >= result.get("last_page", 1):
                            break
                        page += 1
                except Exception as e:
                    logger.warning(f"Auto-sync failed for nxtdash panel {panel.get('name', i)}: {e}")
            
            if total_synced > 0 or total_updated > 0:
                logger.info(f"Auto-sync complete: {total_synced} new, {total_updated} updated total")
            
            # Create accounts for any unlinked users
            await self._create_accounts_for_unlinked()
            
        except Exception as e:
            logger.error(f"Error in sync_imported_users job: {e}")
    
    async def job_create_customer_accounts(self):
        """Create customer accounts for all imported users that don't have one"""
        try:
            await self._create_accounts_for_unlinked()
        except Exception as e:
            logger.error(f"Error in create_customer_accounts job: {e}")
    
    async def _create_accounts_for_unlinked(self):
        """Find all imported users and ensure each has a valid customer account"""
        try:
            from server import create_customer_for_imported_user
            
            all_imported = await self.db.imported_users.find({}).to_list(length=10000)
            
            if not all_imported:
                return
            
            created = 0
            for iu in all_imported:
                try:
                    old_uid = iu.get("user_id")
                    uid = await create_customer_for_imported_user(iu)
                    if uid and not old_uid:
                        created += 1
                except Exception:
                    pass
            
            if created > 0:
                logger.info(f"Auto-created {created} customer accounts for imported users ({len(all_imported)} checked)")
        except Exception as e:
            logger.error(f"Error creating accounts for unlinked users: {e}")
    
    def stop(self):
        """Stop scheduler"""
        self.scheduler.shutdown()
        logger.info("Background job scheduler stopped")
