from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import List, Optional
import os
import logging
import uuid
import aiofiles
import random
import string
import secrets
import hashlib
import contextvars
from html import escape as html_escape
import asyncio
import re
import shutil
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bson import ObjectId
from dotenv import load_dotenv

# Load environment variables from .env file (override existing ones)
load_dotenv(override=True)

from models import (
    User, UserCreate, UserLogin, UserRole,
    Product, ProductCreate,
    Order, OrderCreate, OrderStatus,
    Invoice, Service, ServiceStatus, AccountType,
    Settings, XtreamSettings, SMTPSettings, PayPalSettings, StripeSettings,
    Ticket, TicketCreate, TicketStatus, TicketPriority, TicketMessage,
    EmailTemplate, EmailTemplateType, EmailTemplateUpdate,
    EmailLog, EmailStatus, EmailType,
    EmailUnsubscribe, UnsubscribeReason,
    ScheduledEmail,
    TemplateVersion,
    Referral, ReferralStatus, ReferralSettings,
    Coupon, CouponType, CouponUsage,
    CreditTransaction, CreditSettings,
    Refund, RefundStatus,
    AutoRenewal, RenewalStatus,
    PaymentRetry,
    LifecycleLog, LifecycleAction,
    Download, DownloadCategory, DownloadLog,
    License, LicenseStatus, LicenseValidation,
    ImportedUser
)
from auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user, get_current_admin_user, get_current_staff_user
)
from xtreamui_service import get_xtream_service, XtreamUIService, xtream_api_call
from xtreamui_session_client import XtreamUISessionClient
from onestream_service import OneStreamService, get_onestream_service
from nxtdash_service import NxtDashService, get_nxtdash_service
from aether_service import AetherService, get_aether_service
from email_service import get_email_service
import cockpit_service  # CMTV local change 2026-09-24: Stremio / CMTVpn accounts in the Cockpit panel
from email_logger import EmailLogger
from unsubscribe_manager import UnsubscribeManager
from invoice_service import get_invoice_generator

# Import 2FA and reCAPTCHA services
from two_factor_service import TwoFactorService
from recaptcha_service import RecaptchaService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="IPTV Billing System", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Launcher API router
from launcher_api import router as launcher_router, init_launcher_api
app.include_router(launcher_router)


# MongoDB connection
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/iptv_billing")
DB_NAME = os.getenv("DB_NAME", "test_database")
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Collections
users_collection = db.users
products_collection = db.products
orders_collection = db.orders
invoices_collection = db.invoices
services_collection = db.services
settings_collection = db.settings
tickets_collection = db.tickets
email_templates_collection = db.email_templates
email_logs_collection = db.email_logs
email_unsubscribes_collection = db.email_unsubscribes
scheduled_emails_collection = db.scheduled_emails
template_versions_collection = db.template_versions
referrals_collection = db.referrals
coupons_collection = db.coupons
coupon_usage_collection = db.coupon_usage
credit_transactions_collection = db.credit_transactions
refunds_collection = db.refunds
auto_renewals_collection = db.auto_renewals
payment_retries_collection = db.payment_retries
lifecycle_logs_collection = db.lifecycle_logs
downloads_collection = db.downloads
download_logs_collection = db.download_logs
licenses_collection = db.licenses
license_validations_collection = db.license_validations
imported_users_collection = db.imported_users

# Deduplicate imported users and create unique index on startup
async def ensure_indexes():
    # Step 1: Remove duplicates by username + panel_name + account_type
    pipeline = [
        {"$sort": {"last_synced": -1}},
        {"$group": {
            "_id": {"username": "$username", "panel_name": "$panel_name", "account_type": "$account_type"},
            "docs": {"$push": "$_id"},
            "count": {"$sum": 1},
            "keep": {"$first": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicates = await db.imported_users.aggregate(pipeline).to_list(10000)
    removed = 0
    for dup in duplicates:
        ids_to_remove = [d for d in dup["docs"] if d != dup["keep"]]
        if ids_to_remove:
            result = await db.imported_users.delete_many({"_id": {"$in": ids_to_remove}})
            removed += result.deleted_count
    
    # Also catch by just username + panel_name
    pipeline2 = [
        {"$sort": {"last_synced": -1}},
        {"$group": {
            "_id": {"username": "$username", "panel_name": "$panel_name"},
            "docs": {"$push": "$_id"},
            "count": {"$sum": 1},
            "keep": {"$first": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicates2 = await db.imported_users.aggregate(pipeline2).to_list(10000)
    for dup in duplicates2:
        ids_to_remove = [d for d in dup["docs"] if d != dup["keep"]]
        if ids_to_remove:
            result = await db.imported_users.delete_many({"_id": {"$in": ids_to_remove}})
            removed += result.deleted_count
    
    if removed:
        logger.info(f"Startup: Removed {removed} duplicate imported users")
    
    # Normalize panel_index to int
    await db.imported_users.update_many(
        {"panel_index": {"$type": "string"}},
        [{"$set": {"panel_index": {"$toInt": "$panel_index"}}}]
    )
    
    # Backfill null panel_type to "xtream" and null panel_index to 0
    fixed_products = await db.products.update_many(
        {"panel_type": {"$eq": None}},
        {"$set": {"panel_type": "xtream"}}
    )
    if fixed_products.modified_count:
        logger.info(f"Startup: Backfilled panel_type='xtream' on {fixed_products.modified_count} products")
    
    fixed_pi = await db.products.update_many(
        {"panel_index": {"$eq": None}},
        {"$set": {"panel_index": 0}}
    )
    if fixed_pi.modified_count:
        logger.info(f"Startup: Backfilled panel_index=0 on {fixed_pi.modified_count} products")
    
    # Also fix services
    fixed_svc_pt = await db.services.update_many(
        {"panel_type": {"$eq": None}},
        {"$set": {"panel_type": "xtream"}}
    )
    if fixed_svc_pt.modified_count:
        logger.info(f"Startup: Backfilled panel_type='xtream' on {fixed_svc_pt.modified_count} services")
    
    fixed_svc_pi = await db.services.update_many(
        {"panel_index": {"$eq": None}},
        {"$set": {"panel_index": 0}}
    )
    if fixed_svc_pi.modified_count:
        logger.info(f"Startup: Backfilled panel_index=0 on {fixed_svc_pi.modified_count} services")
    
    # Normalize string panel_index to int on products
    await db.products.update_many(
        {"panel_index": {"$type": "string"}},
        [{"$set": {"panel_index": {"$toInt": "$panel_index"}}}]
    )

    # Fix products with duration=None by inferring from product name
    async for prod in db.products.find({"$or": [{"duration": None}, {"duration": {"$exists": False}}]}):
        pname = (prod.get("name") or "").upper()
        dur = None
        dur_unit = "months"
        if "ANNUAL" in pname or "YEARLY" in pname or "12 MONTH" in pname or "1 YEAR" in pname:
            dur = 12
        elif "6 MONTH" in pname:
            dur = 6
        elif "3 MONTH" in pname:
            dur = 3
        elif "2 MONTH" in pname:
            dur = 2
        elif "24 HOUR" in pname:
            dur = 1
            dur_unit = "days"
        elif "48 HOUR" in pname:
            dur = 2
            dur_unit = "days"
        elif "1 MONTH" in pname or "MONTH" in pname:
            dur = 1
        
        if dur:
            # Also fix the prices key to match
            old_prices = prod.get("prices", {})
            if old_prices:
                dur_months = dur if dur_unit == "months" else max(1, dur // 30)
                if dur_unit == "days":
                    dur_months = 1
                first_price = list(old_prices.values())[0]
                new_prices = {str(dur_months): first_price}
                await db.products.update_one(
                    {"_id": prod["_id"]},
                    {"$set": {"duration": dur, "duration_unit": dur_unit, "prices": new_prices}}
                )
                logger.info(f"Startup: Fixed product '{prod.get('name')}' -> duration={dur} {dur_unit}, prices={new_prices}")
    
    # Also fix services with wrong expiry (annual products with ~30 day expiry)
    async for prod in db.products.find({"duration": {"$gte": 2}, "duration_unit": "months"}):
        prod_dur_days = int(prod["duration"]) * 30
        async for svc in db.services.find({
            "product_id": str(prod["_id"]),
            "status": {"$in": ["active", "expired"]},
            "start_date": {"$exists": True}
        }):
            start = svc.get("start_date")
            expiry = svc.get("expiry_date")
            if start and expiry:
                if isinstance(start, str):
                    try: start = datetime.fromisoformat(start.replace("Z", ""))
                    except ValueError: continue
                if isinstance(expiry, str):
                    try: expiry = datetime.fromisoformat(expiry.replace("Z", ""))
                    except ValueError: continue
                actual_days = (expiry - start).days
                if actual_days < prod_dur_days - 5:  # Service was given less time than it should
                    correct_expiry = start + timedelta(days=prod_dur_days)
                    await db.services.update_one(
                        {"_id": svc["_id"]},
                        {"$set": {"expiry_date": correct_expiry, "term_months": int(prod["duration"])}}
                    )
                    logger.info(f"Startup: Fixed service '{svc.get('xtream_username')}' expiry {expiry.date()} -> {correct_expiry.date()} ({prod.get('name')})")


    
    # Step 2: Drop old index if exists
    try:
        await db.imported_users.drop_index("unique_imported_user")
    except Exception:
        pass
    
    # Step 3: Create unique index
    try:
        await db.imported_users.create_index(
            [("username", 1), ("panel_name", 1), ("account_type", 1)],
            unique=True, name="unique_imported_user", background=True
        )
    except Exception as e:
        logger.warning(f"Unique index creation failed (duplicates may still exist): {e}")
try:
    asyncio.get_event_loop().run_until_complete(ensure_indexes())
except Exception as e:
    logger.warning(f"Index creation: {e}")

# Initialize email logger and unsubscribe manager
email_logger = EmailLogger(db)
unsubscribe_manager = UnsubscribeManager(db)

# Initialize business services (imports only)
from referral_service import ReferralService
from coupon_service import CouponService
from credit_service import CreditService
from refund_service import RefundService
from lifecycle_service import ServiceLifecycleManager
from license_manager import LicenseManager

# Global service instances (will be initialized after get_settings is defined)
referral_service = None
coupon_service = None
credit_service = None
refund_service = None
license_manager = None
lifecycle_manager = None
background_scheduler = None

# Helper functions

async def get_configured_email_service():
    """Get email service with logger and unsubscribe manager"""
    settings = await get_settings()
    smtp_settings = settings.get("smtp", {})
    branding = settings.get("branding", {})
    email_provider = settings.get("email_provider", "smtp")
    email_provider_config = settings.get("email_provider_config", {})
    # Use from_email from provider config if not in SMTP
    if email_provider != "smtp" and not smtp_settings.get("from_email") and email_provider_config.get("from_email"):
        smtp_settings = {**smtp_settings, "from_email": email_provider_config["from_email"]}
    if email_provider != "smtp" and not smtp_settings.get("from_name") and email_provider_config.get("from_name"):
        smtp_settings = {**smtp_settings, "from_name": email_provider_config["from_name"]}
    return get_email_service(smtp_settings, email_logger, unsubscribe_manager, db, branding, email_provider, email_provider_config)


def safe_int(value, default=1):
    """Safely parse an int from a value that may contain HTML or other junk"""
    if value is None:
        return default
    s = str(value).strip()
    # Strip HTML tags
    s = re.sub(r'<[^>]+>', '', s).strip()
    # Extract first number (e.g. "1 / 1" -> "1")
    m = re.search(r'(\d+)', s)
    if m:
        return int(m.group(1))
    return default


def safe_panel_index(value):
    """Safely get panel_index as int, defaulting to 0"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

def safe_panel_type(value):
    """Safely get panel_type, defaulting to 'xtream'"""
    if not value or not isinstance(value, str):
        return "xtream"
    return value


async def safe_upsert_imported_user(query: dict, doc: dict):
    """Upsert an imported user, handling duplicate key errors gracefully"""
    try:
        result = await imported_users_collection.update_one(query, {"$set": doc}, upsert=True)
        return result
    except Exception as e:
        if "E11000" in str(e) or "duplicate key" in str(e).lower():
            result = await imported_users_collection.update_one(query, {"$set": doc})
            return result
        raise


async def get_verification_base_url():
    """Get the base URL for verification links - uses VERIFICATION_URL env var, then BACKEND_PUBLIC_URL"""
    url = os.getenv('VERIFICATION_URL', '') or os.getenv('BACKEND_PUBLIC_URL', '') or os.getenv('PUBLIC_URL', 'http://localhost:8001')
    return url.rstrip('/')

def str_to_objectid(id_str: str) -> ObjectId:
    """Convert string ID to ObjectId"""
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")

def generate_username(length: int = 9) -> str:
    """Generate random username (alphanumeric, no confusing chars)"""
    # Exclude confusing characters: o, O, 0, i, I, l, L, 1
    characters = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(characters, k=length))

def generate_password(length: int = 9) -> str:
    """Generate random password (alphanumeric, no confusing chars, no special chars)"""
    # Exclude confusing characters: o, O, 0, i, I, l, L, 1
    # No special characters
    characters = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(characters, k=length))


# CMTV local change 2026-09-24: emails are stored as typed, so "John@x.com" and "john@x.com" were treated as
# different people (login failed with the "wrong" capitals, and sign-up could create a second account).
def _email_ci(email: str) -> dict:
    """Mongo condition matching this email in any capitalisation"""
    return {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}

async def find_user_by_email(email: str):
    """The account with this email: exact match first, otherwise any capitalisation, but only if that points to
    a single account. Returns None when it's ambiguous, so we never guess which of two accounts was meant."""
    email = email.strip()
    user = await users_collection.find_one({"email": email})
    if user:
        return user
    matches = await users_collection.find({"email": _email_ci(email)}).to_list(length=2)
    if len(matches) > 1:
        logger.warning(f"Email lookup for '{email}' is ambiguous: matches {len(matches)} accounts with different capitalisation")
        return None
    return matches[0] if matches else None

async def email_in_use(email: str, exclude_user_id=None):
    """Any account already using this email, in any capitalisation (for sign-up / email change checks)"""
    query = {"email": _email_ci(email)}
    if exclude_user_id is not None:
        query["_id"] = {"$ne": str_to_objectid(exclude_user_id)}
    return await users_collection.find_one(query)

async def create_customer_for_imported_user(imported_user: dict) -> Optional[str]:
    """Create or link a billing customer account for an imported panel user.
    Returns the user_id of the created/existing customer account."""
    username = imported_user.get("username", "")
    password = imported_user.get("password", "")
    if not username:
        return None

    # If already linked, verify the customer still exists
    existing_uid = imported_user.get("user_id")
    if existing_uid:
        try:
            customer = await users_collection.find_one({"_id": str_to_objectid(existing_uid)})
            if customer:
                return existing_uid  # Already linked and customer exists
            # Customer was deleted — clear the stale link and re-create
            logger.info(f"Imported user {username} linked to deleted customer {existing_uid}, re-linking...")
        except Exception:
            pass

    # Check if customer already exists with this panel_username
    existing = await users_collection.find_one({"panel_username": username})
    if existing:
        user_id = str(existing["_id"])
        await imported_users_collection.update_one(
            {"_id": imported_user["_id"]},
            {"$set": {"user_id": user_id}}
        )
        return user_id

    # Check by placeholder email
    placeholder_email = f"{username}@panel.local"
    email_exists = await users_collection.find_one({"email": placeholder_email})
    if email_exists:
        user_id = str(email_exists["_id"])
        if not email_exists.get("panel_username"):
            await users_collection.update_one({"_id": email_exists["_id"]}, {"$set": {"panel_username": username}})
        await imported_users_collection.update_one(
            {"_id": imported_user["_id"]},
            {"$set": {"user_id": user_id}}
        )
        return user_id

    # Create new customer account
    import secrets
    try:
        customer_doc = {
            "email": placeholder_email,
            "password": get_password_hash(password or secrets.token_hex(8)),
            "name": username,
            "role": "user",
            "panel_username": username,
            "email_verified": False,
            "credit_balance": 0.0,
            "referral_code": secrets.token_hex(4),
            "created_at": datetime.utcnow(),
            "created_via": "panel_sync",
        }
        result = await users_collection.insert_one(customer_doc)
        user_id = str(result.inserted_id)
    except Exception as dup_err:
        existing_by_email = await users_collection.find_one({"email": placeholder_email})
        if existing_by_email:
            user_id = str(existing_by_email["_id"])
        else:
            logger.error(f"Failed to create customer for {username}: {dup_err}")
            return None

    # Link the imported user
    await imported_users_collection.update_one(
        {"_id": imported_user["_id"]},
        {"$set": {"user_id": user_id}}
    )

    # Auto-create a service record so "My Services" works
    panel_type = imported_user.get("panel_type", "")
    panel_name = imported_user.get("panel_name", "")
    streaming_url = ""
    settings = await get_settings()
    panels_key = panel_type if panel_type != "xtream" else "xtream"
    panels_list = settings.get(panels_key, {}).get("panels", [])
    panel_index = imported_user.get("panel_index", 0)
    if panel_index < len(panels_list):
        p = panels_list[panel_index]
        streaming_url = p.get("streaming_url") or p.get("resolved_streaming_url") or p.get("portal_url") or ""
        if not streaming_url and panel_type != "aether":
            streaming_url = p.get("panel_url", "")

    service_exists = await services_collection.find_one({
        "user_id": user_id,
        "xtream_username": username,
    })
    if service_exists:
        # Update panel info if missing or changed
        update_fields = {}
        if not service_exists.get("panel_type"):
            update_fields["panel_type"] = panel_type
        if not service_exists.get("panel_name"):
            update_fields["panel_name"] = panel_name
        if service_exists.get("panel_index") is None:
            update_fields["panel_index"] = panel_index
        if streaming_url and not service_exists.get("streaming_url"):
            update_fields["streaming_url"] = streaming_url
        # Always update expiry and status from panel
        if imported_user.get("expiry_date"):
            update_fields["expiry_date"] = imported_user["expiry_date"]
        if imported_user.get("status"):
            update_fields["status"] = imported_user["status"]
        if update_fields:
            await services_collection.update_one({"_id": service_exists["_id"]}, {"$set": update_fields})
    else:
        service_doc = {
            "user_id": user_id,
            "product_id": "",
            "product_name": f"{panel_name} - {imported_user.get('account_type', 'subscriber').title()}",
            "xtream_username": username,
            "xtream_password": password,
            "username": username,
            "password": password,
            "panel_type": panel_type,
            "panel_name": panel_name,
            "panel_index": panel_index,
            "account_type": imported_user.get("account_type", "subscriber"),
            "max_connections": imported_user.get("max_connections", 1),
            "streaming_url": streaming_url,
            "expiry_date": imported_user.get("expiry_date"),
            "status": imported_user.get("status", "active"),
            "created_at": datetime.utcnow(),
            "created_via": "panel_sync",
        }
        # Add panel-specific IDs
        if imported_user.get("nxtdash_line_id"):
            service_doc["nxtdash_line_id"] = imported_user["nxtdash_line_id"]
        if imported_user.get("onestream_line_id"):
            service_doc["onestream_line_id"] = imported_user["onestream_line_id"]
        if imported_user.get("xtream_user_id"):
            service_doc["dedicatedip"] = imported_user["xtream_user_id"]
        if imported_user.get("aether_line_id"):
            service_doc["aether_line_id"] = imported_user["aether_line_id"]
            service_doc["aether_package_id"] = imported_user.get("aether_package_id")

        await services_collection.insert_one(service_doc)

    return user_id


def render_provision_notes(template: str, **kwargs) -> str:
    """Render provisioning notes template with variables"""
    if not template:
        template = "{{customer_name}} | {{email}} | Order: {{order_id}}"
    for key, val in kwargs.items():
        template = template.replace("{{" + key + "}}", str(val or ""))
    return template.strip()


async def get_settings() -> dict:
    """Get system settings"""
    settings = await settings_collection.find_one()
    if not settings:
        # Create default settings
        default_settings = Settings().dict()
        await settings_collection.insert_one(default_settings)
        return default_settings
    return settings

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize application"""
    logger.info("Starting IPTV Billing System...")
    
    # Create indexes
    await users_collection.create_index("email", unique=True)
    await users_collection.create_index("panel_username", sparse=True)
    await products_collection.create_index("name")
    await orders_collection.create_index("user_id")
    await services_collection.create_index("user_id")
    
    # Create default admin user if not exists
    admin_exists = await users_collection.find_one({"role": "admin"})
    if not admin_exists:
        admin_user = {
            "email": "admin@example.com",
            "name": "Admin",
            "password": get_password_hash("admin123"),
            "role": "admin",
            "created_at": datetime.utcnow()
        }
        await users_collection.insert_one(admin_user)
        logger.info("Default admin created: admin@example.com / admin123")
    
    # Initialize business services (now that get_settings is available)
    global referral_service, coupon_service, credit_service, refund_service, license_manager
    referral_service = ReferralService(db, get_settings)
    coupon_service = CouponService(db)
    credit_service = CreditService(db, get_settings)
    refund_service = RefundService(db, credit_service)
    license_manager = LicenseManager(db)
    logger.info("Business services initialized")
    
    # Initialize Launcher API
    init_launcher_api(db, get_settings, provision_order_services)
    logger.info("Launcher API initialized")
    
    # Validate license on startup (check env var first, then settings)
    current_domain = license_manager.get_current_domain()
    logger.info(f"Current domain detected: {current_domain}")
    logger.info(f"BACKEND_PUBLIC_URL: {os.getenv('BACKEND_PUBLIC_URL', 'not set')}")
    
    license_key = os.getenv("LICENSE_KEY")
    
    # If not in env, check settings
    if not license_key:
        existing_settings = await get_settings()
        license_key = existing_settings.get("license_key", "")
    
    if license_key:
        logger.info(f"Validating license key: {license_key[:8]}...")
        validation = await license_manager.validate_license(license_key, current_domain)
        if validation["valid"]:
            logger.info(f"✓ License validated for domain: {current_domain}")
            logger.info(f"✓ Licensed to: {validation.get('customer_name', 'N/A')}")
        else:
            logger.warning(f"✗ License validation failed: {validation['reason']}")
            logger.warning(f"✗ Domain sent: {current_domain}")
            logger.warning("Application will run in DEMO mode with limitations")
    else:
        logger.warning("No LICENSE_KEY found in environment or settings. Running in DEMO mode.")
    
    # Create default products if none exist
    product_count = await products_collection.count_documents({})
    if product_count == 0:
        default_products = [
            {
                "name": "IPTV Subscriber - 1 Month",
                "description": "Monthly IPTV subscription with full channel access",
                "account_type": "subscriber",
                "bouquets": [1, 2, 3],
                "max_connections": 2,
                "reseller_credits": 0,
                "reseller_max_lines": 0,
                "trial_days": 0,
                "prices": {"1": 15.00},
                "active": True,
                "created_at": datetime.utcnow()
            },
            {
                "name": "IPTV Subscriber - 3 Months",
                "description": "3-month IPTV subscription with full channel access",
                "account_type": "subscriber",
                "bouquets": [1, 2, 3],
                "max_connections": 2,
                "reseller_credits": 0,
                "reseller_max_lines": 0,
                "trial_days": 0,
                "prices": {"3": 40.00},
                "active": True,
                "created_at": datetime.utcnow()
            },
            {
                "name": "IPTV Subscriber - 6 Months",
                "description": "6-month IPTV subscription with full channel access",
                "account_type": "subscriber",
                "bouquets": [1, 2, 3],
                "max_connections": 2,
                "reseller_credits": 0,
                "reseller_max_lines": 0,
                "trial_days": 0,
                "prices": {"6": 75.00},
                "active": True,
                "created_at": datetime.utcnow()
            },
            {
                "name": "IPTV Subscriber - 12 Months",
                "description": "Annual IPTV subscription with full channel access",
                "account_type": "subscriber",
                "bouquets": [1, 2, 3],
                "max_connections": 2,
                "reseller_credits": 0,
                "reseller_max_lines": 0,
                "trial_days": 0,
                "prices": {"12": 140.00},
                "active": True,
                "created_at": datetime.utcnow()
            },
            {
                "name": "IPTV Reseller Package",
                "description": "Reseller package with credit management",
                "account_type": "reseller",
                "bouquets": [],
                "max_connections": 0,
                "reseller_credits": 500.00,
                "reseller_max_lines": 50,
                "trial_days": 0,
                "prices": {"1": 200.00},
                "active": True,
                "created_at": datetime.utcnow()
            }
        ]
        await products_collection.insert_many(default_products)
        logger.info("Default products created")
    
    # Create default email templates if none exist
    template_count = await email_templates_collection.count_documents({})
    if template_count == 0:
        default_templates = [
            {
                "template_type": "order_confirmation",
                "name": "Order Confirmation",
                "subject": "Order Confirmed - {{order_id}}",
                "html_content": """
<h2>Thank you for your order!</h2>
<p>Hi {{customer_name}},</p>
<p>Your order <strong>#{{order_id}}</strong> has been confirmed and payment has been received.</p>

<div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
    <h3 style="margin-top: 0;">Order Details:</h3>
    <p><strong>Order ID:</strong> #{{order_id}}</p>
    <p><strong>Amount Paid:</strong> ${{amount}}</p>
    <p><strong>Service:</strong> {{product_name}}</p>
    <p><strong>Duration:</strong> {{duration}} month(s)</p>
</div>

<p>Your service credentials will be sent to you shortly.</p>
<p>If you have any questions, please don't hesitate to contact our support team.</p>
""",
                "text_content": "Thank you for your order! Order #{{order_id}} has been confirmed. Amount: ${{amount}}",
                "available_variables": ["customer_name", "order_id", "amount", "product_name", "duration"],
                "description": "Sent when an order payment is confirmed",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "service_expiry_warning",
                "name": "Service Expiry Warning",
                "subject": "Your Service Expires Soon - {{days_remaining}} Days Left",
                "html_content": """
<h2>Service Expiry Notice</h2>
<p>Hi {{customer_name}},</p>
<p>This is a friendly reminder that your service will expire in <strong>{{days_remaining}} days</strong>.</p>

<div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
    <h3 style="margin-top: 0;">Service Details:</h3>
    <p><strong>Service:</strong> {{service_name}}</p>
    <p><strong>Expiry Date:</strong> {{expiry_date}}</p>
    <p><strong>Days Remaining:</strong> {{days_remaining}} days</p>
</div>

<p>To continue enjoying uninterrupted service, please renew before the expiry date.</p>
<p><a href="{{renewal_link}}" style="background-color: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px;">Renew Now</a></p>
""",
                "text_content": "Hi {{customer_name}}, your service expires in {{days_remaining}} days. Please renew to continue service.",
                "available_variables": ["customer_name", "service_name", "expiry_date", "days_remaining", "renewal_link"],
                "description": "Sent when a service is about to expire (7, 3, or 1 day before)",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "service_expired",
                "name": "Service Expired",
                "subject": "Your Service Has Expired",
                "html_content": """
<h2>Service Expired</h2>
<p>Hi {{customer_name}},</p>
<p>Your service <strong>{{service_name}}</strong> has expired as of {{expiry_date}}.</p>

<div style="background-color: #f8d7da; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #dc3545;">
    <p><strong>Service:</strong> {{service_name}}</p>
    <p><strong>Expired On:</strong> {{expiry_date}}</p>
</div>

<p>To reactivate your service, please visit our website and place a new order.</p>
<p><a href="{{renewal_link}}" style="background-color: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px;">Reactivate Service</a></p>
""",
                "text_content": "Hi {{customer_name}}, your service has expired. Please renew to continue.",
                "available_variables": ["customer_name", "service_name", "expiry_date", "renewal_link"],
                "description": "Sent when a service has expired",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "ticket_reply",
                "name": "Support Ticket Reply",
                "subject": "New Reply on Your Support Ticket #{{ticket_id}}",
                "html_content": """
<h2>Support Ticket Update</h2>
<p>Hi {{customer_name}},</p>
<p>You have received a new reply on your support ticket <strong>#{{ticket_id}}</strong>.</p>

<div style="background-color: #d1ecf1; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #17a2b8;">
    <h3 style="margin-top: 0;">Ticket: {{ticket_subject}}</h3>
    <p><strong>Reply from:</strong> Support Team</p>
    <div style="background-color: white; padding: 15px; border-radius: 5px; margin-top: 10px;">
        {{reply_message}}
    </div>
</div>

<p><a href="{{ticket_link}}" style="background-color: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px;">View Ticket</a></p>
""",
                "text_content": "Hi {{customer_name}}, you have a new reply on ticket #{{ticket_id}}.",
                "available_variables": ["customer_name", "ticket_id", "ticket_subject", "reply_message", "ticket_link"],
                "description": "Sent when support team replies to a customer ticket",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "welcome",
                "name": "Welcome Email",
                "subject": "Welcome to {{company_name}}!",
                "html_content": """
<h2>Welcome Aboard!</h2>
<p>Hi {{customer_name}},</p>
<p>Thank you for registering with <strong>{{company_name}}</strong>! We're excited to have you as part of our community.</p>

<div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
    <h3 style="margin-top: 0;">Getting Started:</h3>
    <ul style="margin-bottom: 0;">
        <li>Browse our available services and products</li>
        <li>Create your first order</li>
        <li>Access your customer dashboard</li>
        <li>Contact support if you need any assistance</li>
    </ul>
</div>

<p><a href="{{dashboard_link}}" style="background-color: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px;">Go to Dashboard</a></p>
""",
                "text_content": "Welcome to {{company_name}}! We're excited to have you.",
                "available_variables": ["customer_name", "company_name", "dashboard_link"],
                "description": "Sent when a new user registers",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "service_activated",
                "name": "Service Activated - Connection Details",
                "subject": "Your Streaming Service is Ready",
                "html_content": """
<h2>Welcome to Your Premium Streaming Service</h2>

<p>Hi {{customer_name}},</p>

<p>Thank you for choosing us! We are delighted to confirm that your streaming service account has been successfully set up and is ready for you to enjoy.</p>

<p>Your subscription includes access to thousands of channels and on-demand content. You can start watching immediately on up to {{max_connections}} devices at the same time.</p>

<div style="background-color: #f8f9fa; padding: 25px; border-radius: 8px; margin: 25px 0;">
    <h3 style="margin-top: 0; color: #212529;">Your Account Information</h3>
    
    <p style="margin-bottom: 15px;">Below are your personal login credentials. Please keep them safe and do not share with others.</p>
    
    <table style="width: 100%; margin-top: 15px;">
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Service Plan:</td>
            <td style="padding: 10px 0; color: #212529;">{{service_name}}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Account Username:</td>
            <td style="padding: 10px 0; color: #212529; font-family: monospace;">{{username}}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Account Passcode:</td>
            <td style="padding: 10px 0; color: #212529; font-family: monospace;">{{password}}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Server Address:</td>
            <td style="padding: 10px 0; color: #212529; font-size: 13px; word-break: break-all;">{{streaming_url}}</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Concurrent Streams:</td>
            <td style="padding: 10px 0; color: #212529;">{{max_connections}} device(s)</td>
        </tr>
        <tr>
            <td style="padding: 10px 0; color: #495057; font-weight: 600;">Valid Until:</td>
            <td style="padding: 10px 0; color: #212529;">{{expiry_date}}</td>
        </tr>
    </table>
</div>

<h3 style="color: #212529;">Getting Started is Easy</h3>

<p>Follow these simple steps to begin watching:</p>

<ol style="line-height: 1.8; color: #495057;">
    <li>Download a compatible player application on your device (we recommend IPTV Smarters Pro, TiviMate, or VLC Media Player)</li>
    <li>Open the application and select the option to add a new connection or login</li>
    <li>Enter your account information from above (username, passcode, and server address)</li>
    <li>Save your settings and you are all set to start streaming</li>
</ol>

<div style="background-color: #e7f3ff; padding: 20px; border-radius: 8px; margin: 25px 0;">
    <h4 style="margin-top: 0; color: #004085;">Important Information</h4>
    <ul style="margin: 0; line-height: 1.8; color: #004085;">
        <li>Your subscription is active until {{expiry_date}}</li>
        <li>You may connect up to {{max_connections}} devices simultaneously</li>
        <li>For security purposes, please keep your login credentials private</li>
        <li>You can manage your account and view all services anytime from your dashboard</li>
    </ul>
</div>

<p>If you need any assistance with setup or have questions about your service, our support team is here to help. Simply reply to this email or contact us through your account dashboard.</p>

<p style="margin-top: 25px;"><a href="{{dashboard_link}}" style="background-color: #007bff; color: white; padding: 14px 32px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: 600;">Access My Dashboard</a></p>

<p style="margin-top: 30px; color: #6c757d;">We appreciate your business and look forward to providing you with an excellent streaming experience.</p>

<p style="color: #6c757d;">Best regards,<br>The Support Team</p>
""",
                "text_content": "Your service is active! Username: {{username}}, Password: {{password}}, Streaming URL: {{streaming_url}}. Expires: {{expiry_date}}",
                "available_variables": ["customer_name", "service_name", "username", "password", "streaming_url", "max_connections", "expiry_date", "dashboard_link"],
                "description": "Sent when a service is activated with connection credentials",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "payment_received",
                "name": "Payment Received",
                "subject": "Payment Received - ${{amount}}",
                "html_content": """
<h2>Payment Confirmation</h2>
<p>Hi {{customer_name}},</p>
<p>We have successfully received your payment of <strong>${{amount}}</strong>.</p>

<div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
    <h3 style="margin-top: 0;">Payment Details:</h3>
    <p><strong>Amount:</strong> ${{amount}}</p>
    <p><strong>Order ID:</strong> #{{order_id}}</p>
    <p><strong>Payment Method:</strong> {{payment_method}}</p>
    <p><strong>Date:</strong> {{payment_date}}</p>
</div>

<p>Thank you for your payment!</p>
""",
                "text_content": "Payment of ${{amount}} received for order #{{order_id}}. Thank you!",
                "available_variables": ["customer_name", "amount", "order_id", "payment_method", "payment_date"],
                "description": "Sent when a payment is successfully processed",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
,
            {
                "template_type": "reseller_activated",
                "name": "Reseller Panel Activated",
                "subject": "Your Reseller Panel is Ready - {{credits}} Credits",
                "html_content": """
<h2>🎉 Your Reseller Panel is Active!</h2>
<p>Hi {{customer_name}},</p>
<p>Your reseller panel has been successfully activated and is ready to use!</p>

<div style="background-color: #dbeafe; padding: 25px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #3b82f6;">
    <h3 style="margin-top: 0; color: #1e40af;">Reseller Panel Details</h3>
    <table style="width: 100%; border-collapse: collapse;">
        <tr>
            <td style="padding: 8px 0; font-weight: bold; color: #1e40af;">Panel URL:</td>
            <td style="padding: 8px 0; font-family: monospace; background-color: #f3f4f6; padding: 5px 10px; border-radius: 4px; word-break: break-all;">{{panel_url}}</td>
        </tr>
        <tr>
            <td style="padding: 8px 0; font-weight: bold; color: #1e40af;">Username:</td>
            <td style="padding: 8px 0; font-family: monospace; background-color: #f3f4f6; padding: 5px 10px; border-radius: 4px;">{{username}}</td>
        </tr>
        <tr>
            <td style="padding: 8px 0; font-weight: bold; color: #1e40af;">Password:</td>
            <td style="padding: 8px 0; font-family: monospace; background-color: #f3f4f6; padding: 5px 10px; border-radius: 4px;">{{password}}</td>
        </tr>
        <tr>
            <td style="padding: 8px 0; font-weight: bold; color: #1e40af;">Credits:</td>
            <td style="padding: 8px 0; font-weight: bold; font-size: 1.2em; color: #059669;">{{credits}} credits</td>
        </tr>
        <tr>
            <td style="padding: 8px 0; font-weight: bold; color: #1e40af;">Expiry Date:</td>
            <td style="padding: 8px 0;">{{expiry_date}}</td>
        </tr>
    </table>
</div>

<div style="background-color: #fef3c7; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #f59e0b;">
    <h3 style="margin-top: 0; color: #92400e;">🚀 Getting Started</h3>
    <ol style="margin: 0; padding-left: 20px; color: #92400e;">
        <li style="margin-bottom: 10px;">Login to your reseller panel using the URL above</li>
        <li style="margin-bottom: 10px;">Enter your username and password</li>
        <li style="margin-bottom: 10px;">Start creating subscriber accounts for your customers</li>
        <li style="margin-bottom: 10px;">Each subscriber you create will deduct credits from your balance</li>
        <li>Manage your lines, monitor usage, and grow your business!</li>
    </ol>
</div>

<div style="background-color: #d1fae5; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #10b981;">
    <h3 style="margin-top: 0; color: #065f46;">💡 Important Notes</h3>
    <ul style="margin: 0; padding-left: 20px; color: #065f46;">
        <li style="margin-bottom: 8px;">Your {{credits}} credits allow you to create subscriber accounts</li>
        <li style="margin-bottom: 8px;">Credits are deducted based on the package/duration you assign</li>
        <li style="margin-bottom: 8px;">Monitor your credit balance in the reseller panel</li>
        <li style="margin-bottom: 8px;">Purchase additional credit packages anytime to top up</li>
        <li>Need help? Contact our support team!</li>
    </ul>
</div>

<p><a href="{{dashboard_link}}" style="background-color: #3b82f6; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 10px;">Go to Dashboard</a></p>
<p style="margin-top: 20px;">Start managing your IPTV business today! 🎬</p>
""",
                "text_content": "Your reseller panel is active! Panel: {{panel_url}}, Username: {{username}}, Password: {{password}}, Credits: {{credits}}",
                "available_variables": ["customer_name", "panel_url", "username", "password", "credits", "expiry_date", "dashboard_link"],
                "description": "Sent when a reseller panel is activated with credentials and credits",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "email_verification",
                "name": "Email Verification",
                "subject": "Confirm your email",
                "html_content": """<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>
<p style="font-size: 15px; color: #374151; line-height: 1.6;">Please confirm your email address to complete your account setup.</p>
<p style="margin: 24px 0; text-align: center;">
    <a href="{{verification_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">Confirm Email</a>
</p>
<p style="font-size: 13px; color: #6b7280; line-height: 1.5;">If the button does not work, copy this link into your browser:</p>
<p style="font-size: 13px; color: #6b7280; word-break: break-all; background: #f9fafb; padding: 10px; border-radius: 4px;">{{verification_link}}</p>""",
                "text_content": "Hi {{customer_name}},\n\nPlease confirm your email by visiting:\n{{verification_link}}\n\nThis link expires in 24 hours.",
                "available_variables": ["customer_name", "verification_link"],
                "description": "Sent when a new user registers to verify their email",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "service_renewed",
                "name": "Service Renewed",
                "subject": "Service Renewed Successfully",
                "html_content": """
<h2>Service Renewed!</h2>
<p>Hi {{customer_name}},</p>
<p>Your service has been successfully renewed.</p>

<div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #28a745;">
    <h3 style="margin-top: 0;">Renewal Details:</h3>
    <p><strong>Service:</strong> {{service_name}}</p>
    <p><strong>Username:</strong> {{username}}</p>
    <p><strong>New Expiry Date:</strong> {{new_expiry_date}}</p>
</div>

<p>Your existing credentials remain the same.</p>
<p>Thank you for renewing your service!</p>
""",
                "text_content": "Service {{service_name}} renewed. New expiry: {{new_expiry_date}}",
                "available_variables": ["customer_name", "service_name", "username", "new_expiry_date"],
                "description": "Sent when a service is renewed/extended",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "template_type": "credits_added",
                "name": "Credits Added to Reseller Panel",
                "subject": "{{credits}} Credits Added to Your Panel",
                "html_content": """
<h2>Credits Added!</h2>
<p>Hi {{customer_name}},</p>
<p>We have added <strong>{{credits}} credits</strong> to your reseller panel.</p>

<div style="background-color: #dbeafe; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #3b82f6;">
    <h3 style="margin-top: 0;">Panel Details:</h3>
    <p><strong>Panel Username:</strong> {{username}}</p>
    <p><strong>Credits Added:</strong> {{credits}}</p>
</div>

<p>Login to your panel to see the updated credits and start creating subscriber accounts!</p>
<p>Thank you for your purchase!</p>
""",
                "text_content": "{{credits}} credits added to your reseller panel ({{username}})",
                "available_variables": ["customer_name", "username", "credits"],
                "description": "Sent when credits are added to an existing reseller panel",
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }

        ]
        await email_templates_collection.insert_many(default_templates)
        logger.info("Default email templates created")
    
    # Initialize lifecycle manager and background jobs
    global lifecycle_manager, background_scheduler
    
    # Get email service for lifecycle manager
    smtp_settings = (await get_settings()).get("smtp", {})
    branding = (await get_settings()).get("branding", {})
    email_svc = get_email_service(smtp_settings, email_logger, unsubscribe_manager, db, branding)
    xtream_svc = get_xtream_service({})  # Will be configured via settings
    
    lifecycle_manager = ServiceLifecycleManager(db, xtream_svc, email_svc)
    
    # Start background job scheduler
    try:
        from scheduler_init import init_scheduler
        background_scheduler = init_scheduler(db, lifecycle_manager, email_svc)
        logger.info("Background job scheduler started")
    except Exception as e:
        logger.error(f"Failed to start background jobs: {str(e)}")
    
    # One-time: create customer accounts for any existing unlinked imported users
    try:
        all_imported = await imported_users_collection.find({}).to_list(length=10000)
        if all_imported:
            created = 0
            for iu in all_imported:
                try:
                    uid = await create_customer_for_imported_user(iu)
                    if uid and not iu.get("user_id"):
                        created += 1
                except Exception:
                    pass
            if created > 0:
                logger.info(f"Startup: created/linked {created} customer accounts for imported users")
    except Exception as e:
        logger.warning(f"Startup account creation failed: {e}")
    
    logger.info("IPTV Billing System started successfully!")

# Health check
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ===== AUTH ROUTES =====

@app.post("/api/auth/register")
async def register(user_data: UserCreate):
    """Register new user with email verification"""
    # Verify reCAPTCHA if enabled
    settings = await get_settings()
    recaptcha_settings = settings.get("recaptcha", {})
    
    if recaptcha_settings.get("enabled"):
        if not user_data.recaptcha_token:
            raise HTTPException(status_code=403, detail="Security verification required. Please refresh and try again.")
        
        secret_key = recaptcha_settings.get("secret_key")
        if secret_key:
            score_threshold = recaptcha_settings.get("customer_score_threshold", 0.5)
            success, score, _ = await RecaptchaService.verify_token(
                user_data.recaptcha_token, secret_key, action="register", min_score=score_threshold
            )
            if not success and score > 0.0:
                raise HTTPException(status_code=403, detail=f"Security verification failed (score: {score}). Please try again.")
    
    # Check if email already exists
    existing_user = await email_in_use(user_data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Generate verification token
    verification_token = secrets.token_urlsafe(32)
    
    # Create user with email verification
    user_dict = {
        "email": user_data.email,
        "name": user_data.name,
        "password": get_password_hash(user_data.password),
        "role": "user",
        "email_verified": False,
        "verification_token": verification_token,
        "credit_balance": 0.0,
        "referral_code": None,
        "referred_by": user_data.referral_code.upper() if user_data.referral_code else None,
        "created_at": datetime.utcnow()
    }
    
    result = await users_collection.insert_one(user_dict)
    user_id = str(result.inserted_id)
    
    # Generate referral code
    new_user_code = await referral_service.create_referral_code_for_user(user_id)
    
    # Track referral
    if user_data.referral_code:
        await referral_service.track_referral(user_data.referral_code, user_data.email)
    
    # Send verification email
    verification_link = f"{os.getenv('SITE_URL', os.getenv('BACKEND_PUBLIC_URL', 'http://localhost:8001'))}/api/verify-email?redirect=true&token={verification_token}"
    
    try:
        email_service = await get_configured_email_service()
        logger.info(f"Email service status: configured={email_service is not None}, enabled={email_service.enabled if email_service else 'N/A'}")
        if email_service and email_service.enabled:
            logger.info(f"Sending verification email to {user_data.email}")
            result = await email_service.send_email_verification(
                customer_email=user_data.email,
                customer_name=user_data.name,
                verification_link=verification_link,
                customer_id=user_id
            )
            if result:
                logger.info(f"Verification email sent successfully to {user_data.email}")
            else:
                logger.error(f"Verification email failed to send to {user_data.email} (returned False)")
        else:
            logger.warning(f"SMTP not configured - verification email NOT sent to {user_data.email}")
    except Exception as e:
        logger.error(f"Error sending verification email to {user_data.email}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    # Send Telegram notification
    await send_telegram_notification(
        "new_user_registration",
        f"🆕 *New User Registration*\n\nName: {user_data.name}\nEmail: {user_data.email}"
    )
    await send_email_notification(
        "new_user_registration",
        "New User Registration",
        f"Name: {user_data.name}\nEmail: {user_data.email}"
    )
    await send_sms_notification("new_user_registration", f"Name: {user_data.name}\nEmail: {user_data.email}")
    
    return {
        "message": "Registration successful! Please check your email to verify your account.",
        "email": user_data.email,
        "verification_required": True
    }

@app.get("/api/verify-email")
async def verify_email_api(token: str, redirect: bool = False):
    """API endpoint for email verification"""
    user = await users_collection.find_one({"verification_token": token})
    
    if not user:
        if redirect:
            return RedirectResponse(url="/?error=invalid_token")
        raise HTTPException(status_code=404, detail="Invalid or expired verification token")
    
    # Check if already verified
    if user.get("email_verified"):
        return {"message": "Email already verified", "verified": True}
    
    # Verify email
    await users_collection.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "email_verified": True,
                "verification_token": None
            }
        }
    )
    
    # Send welcome email
    email_service = await get_configured_email_service()
    if email_service and email_service.enabled:
        await email_service.send_welcome_email(
            customer_email=user["email"],
            customer_name=user["name"],
            customer_id=str(user["_id"])
        )
    
    # Award signup bonus if referred
    if user.get("referred_by") and credit_service:
        settings = await get_settings()
        referred_reward = settings.get("referral", {}).get("referred_reward", 5.0)
        
        if referred_reward > 0:
            try:
                await credit_service.add_credits(
                    user_id=str(user["_id"]),
                    amount=referred_reward,
                    transaction_type="referral_signup",
                    description="Welcome bonus for using referral code"
                )
            except Exception as e:
                logger.error(f"Failed to award signup bonus: {e}")
    
    if redirect:
        return RedirectResponse(url="/?message=email_verified")
    return {"message": "Email verified successfully", "verified": True}

@app.get("/verify-email")
async def verify_email(token: str):
    """Legacy redirect endpoint for email verification"""
    try:
        await verify_email_api(token)
        return RedirectResponse(url="/?message=email_verified")
    except Exception:
        return RedirectResponse(url="/?error=invalid_token")

class ResendVerificationRequest(BaseModel):
    email: str
    password: str
    new_email: Optional[str] = None

@app.post("/api/auth/resend-verification")
async def resend_verification(data: ResendVerificationRequest):
    """Resend verification email, optionally update email address"""
    login_id = data.email.strip()
    if "@" in login_id:
        user = await find_user_by_email(login_id)
    else:
        user = await users_collection.find_one({"panel_username": login_id})
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if not verify_password(data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    if user.get("email_verified"):
        raise HTTPException(status_code=400, detail="Email already verified")
    
    target_email = data.new_email.strip() if data.new_email and data.new_email.strip() else data.email
    
    # If changing email, check it's not taken
    if target_email != data.email:
        existing = await email_in_use(target_email, exclude_user_id=user["_id"])
        if existing:
            raise HTTPException(status_code=400, detail="That email is already registered")
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"email": target_email}}
        )
    
    # Generate new verification token
    verification_token = secrets.token_urlsafe(32)
    await users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"verification_token": verification_token}}
    )
    
    verification_link = f"{os.getenv('SITE_URL', os.getenv('BACKEND_PUBLIC_URL', 'http://localhost:8001'))}/api/verify-email?redirect=true&token={verification_token}"
    logger.info(f"Resend verification: new token generated for {target_email}, link={verification_link[:80]}...")
    
    try:
        email_service = await get_configured_email_service()
        logger.info(f"Resend: Email service configured={email_service is not None}, enabled={email_service.enabled if email_service else 'N/A'}")
        if email_service and email_service.enabled:
            result = await email_service.send_email_verification(
                customer_email=target_email,
                customer_name=user.get("name", ""),
                verification_link=verification_link,
                customer_id=str(user["_id"])
            )
            if result:
                logger.info(f"Resend verification email sent to {target_email}")
                return {"message": f"Verification email sent to {target_email}"}
            else:
                logger.error(f"Resend verification email failed for {target_email}")
                raise HTTPException(status_code=500, detail="Failed to send verification email. Please try again or contact support.")
        else:
            logger.warning(f"SMTP not configured - cannot resend verification to {target_email}")
            raise HTTPException(status_code=500, detail="Email system is not configured. Please contact support.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resend verification: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to send verification email. Please try again.")

# CMTV local change 2026-09-24: self-service "forgot password". Emails a one-time reset link that expires after
# PASSWORD_RESET_TTL. Only a SHA-256 hash of the token is stored, so the database alone can't be used to reset passwords.
PASSWORD_RESET_TTL = timedelta(hours=1)
PASSWORD_RESET_COOLDOWN = timedelta(minutes=2)  # at most one reset email per account per cooldown

class ForgotPasswordRequest(BaseModel):
    email: str  # Can be email OR username, same as login
    recaptcha_token: Optional[str] = None

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def _mask_email(email: str) -> str:
    """jo***@gmail.com - enough for the customer to recognise their account, without showing the full address"""
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"

async def _find_reset_account(login_id: str):
    """Find exactly one account for a reset request, or None if there is no match or the match is ambiguous"""
    if "@" in login_id:
        return await find_user_by_email(login_id)
    matches = await users_collection.find({"panel_username": login_id}).to_list(length=2)
    if len(matches) > 1:
        logger.warning(f"Password reset for username '{login_id}' refused: matches {len(matches)} accounts")
        return None
    return matches[0] if matches else None

@app.post("/api/auth/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    """Email a password reset link. Always gives the same answer, so it can't be used to find out who has an account."""
    generic = {"message": "If an account matches, a password reset link has been sent to its email address. The link expires in 1 hour."}

    settings = await get_settings()
    recaptcha_settings = settings.get("recaptcha", {})
    if recaptcha_settings.get("enabled"):
        if not data.recaptcha_token:
            raise HTTPException(status_code=403, detail="Security verification required. Please refresh and try again.")
        secret_key = recaptcha_settings.get("secret_key")
        if secret_key:
            success, score, _ = await RecaptchaService.verify_token(
                data.recaptcha_token, secret_key, action="forgot_password",
                min_score=recaptcha_settings.get("customer_score_threshold", 0.5)
            )
            if not success and score > 0.0:
                raise HTTPException(status_code=403, detail=f"Security verification failed (score: {score}). Please try again.")

    login_id = data.email.strip()
    if not login_id:
        return generic
    user = await _find_reset_account(login_id)

    email = (user or {}).get("email") or ""
    if not user or "@" not in email or email.lower().endswith("@panel.local"):
        logger.info(f"Password reset requested for '{login_id}': no single account with a real email address")
        return generic
    if user.get("role") != "user":
        # Admin/staff passwords are reset from the server, not by email
        logger.warning(f"Password reset requested for {user.get('role')} account {email}: refused")
        return generic

    now = datetime.utcnow()
    last_request = user.get("password_reset_requested_at")
    if last_request and now - last_request < PASSWORD_RESET_COOLDOWN:
        logger.info(f"Password reset for {email} skipped: requested again within cooldown")
        return generic

    reset_token = secrets.token_urlsafe(32)
    await users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "password_reset_token_hash": _hash_reset_token(reset_token),
            "password_reset_expires": now + PASSWORD_RESET_TTL,
            "password_reset_requested_at": now
        }}
    )

    reset_link = f"{os.getenv('SITE_URL', os.getenv('BACKEND_PUBLIC_URL', 'http://localhost:8001'))}/reset-password?token={reset_token}"
    try:
        email_service = await get_configured_email_service()
        if email_service and email_service.enabled:
            sent = await email_service.send_password_reset(
                customer_email=email,
                customer_name=user.get("name") or user.get("panel_username") or "",
                reset_link=reset_link,
                customer_id=str(user["_id"]),
                account_label=user.get("panel_username") or email
            )
            if sent:
                logger.info(f"Password reset email sent to {email}")
            else:
                logger.error(f"Password reset email failed to send to {email} (returned False)")
        else:
            logger.warning(f"Email not configured - password reset email NOT sent to {email}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {e}")

    return generic

async def _find_user_by_reset_token(token: str):
    return await users_collection.find_one({
        "password_reset_token_hash": _hash_reset_token(token.strip()),
        "password_reset_expires": {"$gt": datetime.utcnow()},
        "role": "user"
    })

@app.get("/api/auth/reset-password/check")
async def check_reset_token(token: str):
    """Tell the reset page which account the link is for, so the customer can confirm it's theirs"""
    user = await _find_user_by_reset_token(token)
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")
    return {"email": _mask_email(user["email"]), "username": user.get("panel_username") or None}

@app.post("/api/auth/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Set a new password using the token from a password reset email"""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = await _find_user_by_reset_token(data.token)
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")

    # The token belongs to this one account: the update matches its _id AND the token, so a link that was
    # replaced by a newer one (or already used) can't change anything
    result = await users_collection.update_one(
        {"_id": user["_id"], "password_reset_token_hash": user["password_reset_token_hash"]},
        {
            "$set": {
                "password": get_password_hash(data.new_password),
                "password_changed_at": datetime.utcnow(),
                # The link was opened from their inbox, which proves they own the address
                "email_verified": True,
                "verification_token": None
            },
            "$unset": {"password_reset_token_hash": "", "password_reset_expires": "", "password_reset_requested_at": ""}
        }
    )
    if result.modified_count != 1:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please request a new one.")
    logger.info(f"Password reset completed for {user.get('email')}")

    # Tell the customer, so a reset they didn't make doesn't go unnoticed
    try:
        email_service = await get_configured_email_service()
        if email_service and email_service.enabled:
            await email_service.send_password_changed(
                customer_email=user["email"],
                customer_name=user.get("name") or user.get("panel_username") or "",
                customer_id=str(user["_id"]),
                account_label=user.get("panel_username") or user["email"]
            )
    except Exception as e:
        logger.error(f"Error sending password changed email to {user.get('email')}: {e}")

    return {"message": "Your password has been reset. You can now sign in with your new password."}

@app.post("/api/auth/login")
async def login(credentials: UserLogin):
    """Login user - requires email verification and optional reCAPTCHA"""
    # Step 1: Verify reCAPTCHA if enabled
    settings = await get_settings()
    recaptcha_settings = settings.get("recaptcha", {})
    
    if recaptcha_settings.get("enabled") and credentials.recaptcha_token:
        score_threshold = recaptcha_settings.get("customer_score_threshold", 0.5)
        secret_key = recaptcha_settings.get("secret_key")
        
        logger.info(f"reCAPTCHA verification attempt for {credentials.email}")
        logger.info(f"Score threshold: {score_threshold}, Has secret key: {bool(secret_key)}")
        
        if secret_key:
            success, score, response_data = await RecaptchaService.verify_token(
                credentials.recaptcha_token,
                secret_key,
                action="login",
                min_score=score_threshold
            )
            
            logger.info(f"reCAPTCHA result: success={success}, score={score}")
            
            # For development/testing: Allow 0.0 scores (common in test environments)
            # In production, you may want to be stricter
            if not success and score > 0.0:
                logger.warning(f"reCAPTCHA failed for {credentials.email}: score={score}, threshold={score_threshold}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Security verification failed (score: {score}). Please try again."
                )
            elif score == 0.0:
                logger.warning(f"reCAPTCHA score 0.0 for {credentials.email} - allowing (test environment)")
        else:
            logger.warning("reCAPTCHA enabled but no secret key configured")
    elif recaptcha_settings.get("enabled") and not credentials.recaptcha_token:
        logger.warning(f"reCAPTCHA enabled but no token provided for {credentials.email}")
        raise HTTPException(
            status_code=403,
            detail="Security verification required. Please refresh and try again."
        )
    
    # Step 2: Verify credentials (support both email and username login)
    login_id = credentials.email.strip()
    if "@" in login_id:
        user = await find_user_by_email(login_id)
    else:
        # Username login — check panel_username field
        user = await users_collection.find_one({"panel_username": login_id})
    
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email/username or password")
    
    # Step 3: Check email verification (except for admin and panel-synced users)
    has_real_email = bool(user.get("email")) and "@" in user.get("email", "") and not user["email"].endswith("@panel.local")
    is_panel_user = user.get("created_via") == "panel_sync"
    needs_email_link = (not has_real_email or not user.get("email_verified", False)) and is_panel_user and user.get("role") != "admin"
    
    # Only block login for email verification if user registered normally (not panel-synced)
    if user.get("role") != "admin" and not is_panel_user and has_real_email and not user.get("email_verified", False):
        raise HTTPException(
            status_code=403, 
            detail="Email not verified. Please check your inbox for the verification link."
        )
    
    # Step 4: Check 2FA for admin users
    if user.get("role") == "admin" and user.get("totp_enabled"):
        if not credentials.totp_code:
            # Return special response indicating 2FA is required
            return {
                "requires_2fa": True,
                "message": "Two-factor authentication required",
                "temp_token": create_access_token(data={
                    "sub": str(user["_id"]),
                    "email": user["email"],
                    "temp": True
                }, expires_delta=timedelta(minutes=5))
            }
        
        # Verify TOTP code
        totp_secret = user.get("totp_secret")
        if not TwoFactorService.verify_totp(totp_secret, credentials.totp_code):
            raise HTTPException(status_code=401, detail="Invalid 2FA code")
    
    # Step 5: Create access token
    access_token = create_access_token(data={
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user.get("role", "user")
    })
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "requires_2fa": False,
        "needs_email_link": needs_email_link,
        "user": {
            "id": str(user["_id"]),
            "email": user.get("email", ""),
            "name": user.get("name", user.get("panel_username", "")),
            "role": user.get("role", "user"),
            "email_verified": user.get("email_verified", False),
            "totp_enabled": user.get("totp_enabled", False),
            "panel_username": user.get("panel_username", ""),
            "needs_email_link": needs_email_link,
            "permissions": user.get("permissions", []),
        }
    }

@app.post("/api/auth/link-email")
async def link_email_to_account(data: dict, current_user: dict = Depends(get_current_user)):
    """Link an email address to a panel-imported account and send verification"""
    email = data.get("email", "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email address required")

    # Check email not already used
    existing = await email_in_use(email, exclude_user_id=current_user["sub"])
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use by another account")

    # Generate verification token
    import secrets
    verification_token = secrets.token_urlsafe(32)

    await users_collection.update_one(
        {"_id": str_to_objectid(current_user["sub"])},
        {"$set": {"email": email, "email_verified": False, "verification_token": verification_token}}
    )

    # Send verification email
    email_service = await get_configured_email_service()
    if email_service:
        try:
            user = await users_collection.find_one({"_id": str_to_objectid(current_user["sub"])})
            customer_name = user.get("name", user.get("panel_username", "Customer"))
            verify_url = f"{os.getenv('SITE_URL', os.getenv('BACKEND_PUBLIC_URL', os.getenv('PUBLIC_URL', '')))}/api/verify-email?redirect=true&token={verification_token}"
            await email_service.send_email_verification(email, customer_name, verify_url, customer_id=current_user["sub"])
        except Exception as e:
            logger.warning(f"Failed to send verification email: {e}")

    return {"success": True, "message": "Verification email sent. Please check your inbox."}

@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info"""
    user = await users_collection.find_one({"_id": str_to_objectid(current_user["sub"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    has_email = bool(user.get("email")) and "@" in user.get("email", "") and not user["email"].endswith("@panel.local")
    
    return {
        "id": str(user["_id"]),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "role": user.get("role", "user"),
        "panel_username": user.get("panel_username", ""),
        "needs_email_link": not has_email and user.get("role") != "admin",
        "email_verified": user.get("email_verified", False),
    }

# ===== 2FA ROUTES (Admin Only) =====

@app.post("/api/auth/2fa/setup")
async def setup_2fa(current_user: dict = Depends(get_current_admin_user)):
    """Setup 2FA for admin user - generates QR code"""
    user_id = current_user["sub"]
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate new TOTP secret
    secret = TwoFactorService.generate_secret()
    
    # Generate QR code
    qr_code = TwoFactorService.generate_qr_code(
        secret,
        user["email"],
        issuer="IPTV Billing Admin"
    )
    
    # Store secret temporarily (not enabled yet)
    await users_collection.update_one(
        {"_id": str_to_objectid(user_id)},
        {"$set": {"totp_secret_pending": secret}}
    )
    
    return {
        "secret": secret,
        "qr_code": qr_code,
        "message": "Scan this QR code with Google Authenticator and verify to enable 2FA"
    }

@app.post("/api/auth/2fa/verify-setup")
async def verify_2fa_setup(
    totp_code: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Verify 2FA setup by checking TOTP code"""
    user_id = current_user["sub"]
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    pending_secret = user.get("totp_secret_pending")
    if not pending_secret:
        raise HTTPException(status_code=400, detail="No pending 2FA setup found")
    
    # Verify the TOTP code
    if not TwoFactorService.verify_totp(pending_secret, totp_code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    
    # Generate backup codes
    backup_codes = TwoFactorService.get_backup_codes(count=10)
    
    # Enable 2FA and move pending secret to active
    await users_collection.update_one(
        {"_id": str_to_objectid(user_id)},
        {
            "$set": {
                "totp_secret": pending_secret,
                "totp_enabled": True,
                "backup_codes": backup_codes
            },
            "$unset": {"totp_secret_pending": ""}
        }
    )
    
    return {
        "message": "2FA enabled successfully",
        "backup_codes": backup_codes
    }

@app.post("/api/auth/2fa/disable")
async def disable_2fa(
    password: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Disable 2FA for admin user (requires password confirmation)"""
    user_id = current_user["sub"]
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify password
    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # Disable 2FA
    await users_collection.update_one(
        {"_id": str_to_objectid(user_id)},
        {
            "$set": {"totp_enabled": False},
            "$unset": {"totp_secret": "", "backup_codes": ""}
        }
    )
    
    return {"message": "2FA disabled successfully"}

@app.get("/api/auth/2fa/status")
async def get_2fa_status(current_user: dict = Depends(get_current_admin_user)):
    """Get 2FA status for current admin user"""
    user_id = current_user["sub"]
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "enabled": user.get("totp_enabled", False),
        "has_backup_codes": bool(user.get("backup_codes"))
    }

# ===== RECAPTCHA SETTINGS ROUTES =====

@app.get("/api/recaptcha/sitekey")
async def get_recaptcha_sitekey():
    """Get reCAPTCHA site key (public endpoint)"""
    settings = await get_settings()
    recaptcha = settings.get("recaptcha", {})
    
    return {
        "site_key": recaptcha.get("site_key", ""),
        "enabled": recaptcha.get("enabled", False)
    }

@app.get("/api/terms")
async def get_terms():
    """Get terms and conditions (public endpoint)"""
    settings = await get_settings()
    terms = settings.get("terms", {})
    return {
        "enabled": terms.get("enabled", False),
        "title": terms.get("title", "Terms and Conditions"),
        "content": terms.get("content", "")
    }


# ===== PRODUCT ROUTES =====

@app.get("/api/products")
async def get_products():
    """Get all active products sorted by display_order"""
    products = []
    async for product in products_collection.find({"active": True}).sort([("display_order", 1), ("created_at", 1)]):
        product["id"] = str(product["_id"])
        del product["_id"]
        products.append(product)
    return products

@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    """Get single product"""
    product = await products_collection.find_one({"_id": str_to_objectid(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    product["id"] = str(product["_id"])
    del product["_id"]
    return product

# ===== ORDER ROUTES =====

# ===== PAYPAL ROUTES =====

@app.post("/api/orders/{order_id}/pay/paypal")
async def create_paypal_payment(order_id: str, origin: dict, current_user: dict = Depends(get_current_user)):
    """Create PayPal payment for order"""
    user_id = current_user["sub"]
    
    # Get order
    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    # Get PayPal settings
    settings = await get_settings()
    paypal_settings = settings.get("paypal", {})
    
    if not paypal_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="PayPal not enabled")
    
    from paypal_service import get_paypal_service
    paypal = get_paypal_service(paypal_settings)
    
    if not paypal:
        raise HTTPException(status_code=500, detail="PayPal service not available")
    
    # Get frontend URL from origin
    frontend_url = origin.get("origin", "http://localhost:3000")
    
    # Create payment with frontend URLs
    settings = await get_settings()
    currency = settings.get("currency", "USD")
    result = paypal.create_order(
        amount=order["total"],
        currency=currency,
        return_url=f"{frontend_url}/payment/paypal/success?order_id={order_id}",
        cancel_url=f"{frontend_url}/checkout?payment=cancelled",
        order_id=order_id
    )
    
    if result["success"]:
        return {"success": True, "order_id": result["order_id"]}  # Return EC-XXX token
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Payment creation failed"))

@app.post("/api/orders/paypal/capture")
async def capture_paypal_order(data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Capture PayPal order after approval"""
    order_id = data.get("order_id")
    paypal_order_id = data.get("paypal_order_id")
    
    # Get PayPal settings
    settings = await get_settings()
    paypal_settings = settings.get("paypal", {})
    
    from paypal_service import get_paypal_service
    paypal = get_paypal_service(paypal_settings)
    
    if not paypal:
        raise HTTPException(status_code=500, detail="PayPal service not available")

    # CMTV local change 2026-09-24: both ids come from the browser, so before capturing make sure this PayPal
    # order was created for THIS billing order, belongs to this customer, and is for the full amount.
    # (Previously a cheap PayPal payment could be used to mark an expensive order paid.)
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id)}) if order_id else None
    if not order or order.get("user_id") != current_user["sub"]:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "paid":
        return {"success": True, "message": "Order already paid"}
    pp = paypal.get_order(paypal_order_id) if paypal_order_id else {"success": False}
    try:
        pp_amount = float(pp.get("amount") or 0)
    except (TypeError, ValueError):
        pp_amount = 0.0
    expected_currency = settings.get("currency", "USD")
    if (not pp.get("success") or pp.get("reference_id") != order_id
            or pp_amount + 0.01 < float(order.get("total") or 0)
            or (pp.get("currency") or "").upper() != str(expected_currency).upper()):
        logger.error(f"PayPal capture refused for order {order_id}: PayPal order {paypal_order_id} is for "
                     f"{pp.get('reference_id')!r} {pp.get('amount')} {pp.get('currency')} (expected {order.get('total')} {expected_currency})")
        raise HTTPException(status_code=400, detail="This PayPal payment does not match the order")

    # Capture payment
    result = paypal.capture_order(paypal_order_id)
    
    if result["success"] and result["status"] == "COMPLETED":
        # Get order
        order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
        
        if order and order["status"] != "paid":
            # Mark order as paid
            await orders_collection.update_one(
                {"_id": str_to_objectid(order_id)},
                {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "paypal", "payment_id": paypal_order_id}}
            )
            
            # Update invoice
            await invoices_collection.update_one(
                {"order_id": order_id},
                {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
            )
            
            # Get user
            user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
            
            # Provision services
            background_tasks.add_task(provision_order_services, order_id, order, user)
            
            return {"success": True, "message": "Payment captured successfully"}
    
    raise HTTPException(status_code=500, detail="Payment capture failed")

@app.get("/api/orders/{order_id}/pay/paypal/success")
async def paypal_success(order_id: str, paymentId: str, PayerID: str, background_tasks: BackgroundTasks):
    """Handle PayPal payment success"""
    settings = await get_settings()
    paypal_settings = settings.get("paypal", {})
    
    from paypal_service import get_paypal_service
    paypal = get_paypal_service(paypal_settings)
    
    if not paypal:
        return {"error": "PayPal not configured"}
    
    # Execute payment
    result = paypal.execute_payment(paymentId, PayerID)
    
    if result["success"] and result["state"] == "approved":
        # Get order
        order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
        
        if order:
            # Mark order as paid
            await orders_collection.update_one(
                {"_id": str_to_objectid(order_id)},
                {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "paypal", "payment_id": paymentId}}
            )
            
            # Update invoice
            await invoices_collection.update_one(
                {"order_id": order_id},
                {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
            )
            
            # Get user
            user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
            
            # Provision services
            background_tasks.add_task(provision_order_services, order_id, order, user)
            
            # Redirect to success page
            frontend_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", "http://localhost:3000"))
            return RedirectResponse(url=f"{frontend_url}/orders?payment=success")
    
    return {"error": "Payment failed"}

@app.get("/api/orders/{order_id}/pay/paypal/cancel")
async def paypal_cancel(order_id: str):
    """Handle PayPal payment cancellation"""
    frontend_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", "http://localhost:3000"))
    return RedirectResponse(url=f"{frontend_url}/orders?payment=cancelled")

@app.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle PayPal webhooks - safety net for payment confirmation"""
    try:
        data = await request.json()
        event_type = data.get("event_type", "")
        logger.info(f"PayPal webhook received: {event_type}")
        
        # Handle payment completion events
        if event_type in ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.SALE.COMPLETED"]:
            resource = data.get("resource", {})
            
            # Try to find our order from the PayPal custom_id, reference_id, or invoice_id
            custom_id = resource.get("custom_id", "") or resource.get("invoice_id", "")
            paypal_id = resource.get("id", "")
            
            # Check purchase_units for reference_id/custom_id
            if not custom_id:
                purchase_units = resource.get("purchase_units", [])
                if purchase_units:
                    custom_id = purchase_units[0].get("custom_id", "") or purchase_units[0].get("reference_id", "")
            
            # Also check supplementary_data for order reference
            if not custom_id:
                supplementary = resource.get("supplementary_data", {})
                related = supplementary.get("related_ids", {})
                custom_id = related.get("order_id", "")
            
            # Try to find order by payment_id
            order = None
            if custom_id:
                order = await orders_collection.find_one({"_id": str_to_objectid(custom_id)})
            if not order and paypal_id:
                order = await orders_collection.find_one({"payment_id": paypal_id})
            
            # CMTV local change 2026-09-24: the webhook body is not authenticated, so confirm with PayPal itself
            # that this capture is COMPLETED, belongs to this order and covers its total before marking it paid.
            if order and order.get("status") != "paid":
                verified = False
                if event_type == "PAYMENT.CAPTURE.COMPLETED" and paypal_id:
                    from paypal_service import get_paypal_service
                    wh_settings = await get_settings()
                    pp = get_paypal_service(wh_settings.get("paypal", {}))
                    cap = pp.get_capture(paypal_id) if pp else {"success": False}
                    belongs = cap.get("custom_id") == str(order["_id"])
                    if not belongs and pp and cap.get("paypal_order_id"):
                        belongs = pp.get_order(cap["paypal_order_id"]).get("reference_id") == str(order["_id"])
                    try:
                        cap_amount = float(cap.get("amount") or 0)
                    except (TypeError, ValueError):
                        cap_amount = 0.0
                    verified = (cap.get("success") and cap.get("status") == "COMPLETED" and belongs
                                and cap_amount + 0.01 >= float(order.get("total") or 0)
                                and (cap.get("currency") or "").upper() == str(wh_settings.get("currency", "USD")).upper())
                if not verified:
                    logger.warning(f"PayPal webhook NOT trusted for order {order.get('_id')}: {event_type} {paypal_id} could not be verified with PayPal")
                    return {"status": "received"}

            if order and order.get("status") != "paid":
                order_id = str(order["_id"])
                logger.info(f"PayPal webhook: Marking order {order_id} as paid")
                
                await orders_collection.update_one(
                    {"_id": order["_id"]},
                    {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "paypal", "payment_id": paypal_id}}
                )
                await invoices_collection.update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                )
                
                user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                if user:
                    background_tasks.add_task(provision_order_services, order_id, order, user)
                    logger.info(f"PayPal webhook: Order {order_id} paid and provisioning triggered")
            elif order and order.get("status") == "paid":
                logger.info(f"PayPal webhook: Order already paid, skipping")
            else:
                logger.warning(f"PayPal webhook: Could not find order for custom_id={custom_id}, paypal_id={paypal_id}")
        
        return {"status": "received"}
    except Exception as e:
        logger.error(f"PayPal webhook error: {str(e)}")
        return {"status": "error"}

# ===== STRIPE/CRYPTO ROUTES =====

@app.post("/api/orders/{order_id}/pay/stripe")
async def create_stripe_payment(order_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Create Stripe/Crypto payment session for order"""
    user_id = current_user["sub"]
    
    # Get order
    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    # Get Stripe settings
    settings = await get_settings()
    stripe_settings = settings.get("stripe", {})
    
    if not stripe_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Stripe not enabled")
    
    # Get base URL - prefer BACKEND_PUBLIC_URL for production behind proxy
    base_url = os.getenv("BACKEND_PUBLIC_URL", str(request.base_url).rstrip('/'))
    webhook_url = f"{base_url}/api/webhooks/stripe"
    
    from stripe_service import get_stripe_service
    stripe = get_stripe_service(stripe_settings, webhook_url)
    
    if not stripe:
        raise HTTPException(status_code=500, detail="Stripe service not available. Check your Stripe API keys.")
    
    # Get frontend URL for redirects - use SITE_URL for customer-facing pages
    frontend_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", base_url))
    
    # Create payment session
    settings = await get_settings()
    currency = settings.get("currency", "USD").lower()
    # Note: {CHECKOUT_SESSION_ID} is a Stripe placeholder that gets replaced with actual session ID
    result = await stripe.create_payment_session(
        amount=order["total"],
        order_id=order_id,
        success_url=f"{frontend_url}/checkout?payment=success&session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}",
        cancel_url=f"{frontend_url}/checkout?payment=cancelled",
        crypto_enabled=stripe_settings.get("crypto_enabled", True),
        currency=currency
    )
    
    if result["success"]:
        # Store payment transaction for tracking
        await db.payment_transactions.insert_one({
            "order_id": order_id,
            "user_id": user_id,
            "gateway": "stripe",
            "session_id": result["session_id"],
            "amount": order["total"],
            "currency": currency,
            "payment_status": "pending",
            "created_at": datetime.utcnow()
        })
        return {"success": True, "session_id": result["session_id"], "checkout_url": result["checkout_url"]}
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Payment creation failed"))

@app.get("/api/payments/stripe/success")
async def stripe_payment_success(session_id: str, order_id: str, background_tasks: BackgroundTasks):
    """Handle Stripe payment success - check status and redirect"""
    settings = await get_settings()
    stripe_settings = settings.get("stripe", {})
    
    base_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001")
    webhook_url = f"{base_url}/api/webhooks/stripe"
    frontend_url = os.getenv("SITE_URL", base_url)
    
    from stripe_service import get_stripe_service
    stripe = get_stripe_service(stripe_settings, webhook_url)
    
    if stripe:
        result = await stripe.get_payment_status(session_id)
        
        if result.get("success") and (result.get("payment_status") or result.get("status")) == "paid":
            # Mark order as paid
            order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
            
            if order and order["status"] != "paid":
                await orders_collection.update_one(
                    {"_id": str_to_objectid(order_id)},
                    {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "stripe", "payment_id": session_id}}
                )
                
                await invoices_collection.update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                )
                
                user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                background_tasks.add_task(provision_order_services, order_id, order, user)
    
    # Redirect to orders page
    return RedirectResponse(url=f"{frontend_url}/orders?payment=success")

@app.get("/api/payments/stripe/status/{session_id}")
async def check_stripe_payment_status(session_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Check Stripe payment status and provision if paid"""
    settings = await get_settings()
    stripe_settings = settings.get("stripe", {})
    
    base_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001")
    webhook_url = f"{base_url}/api/webhooks/stripe"
    
    from stripe_service import get_stripe_service
    stripe = get_stripe_service(stripe_settings, webhook_url)
    
    if not stripe:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Get payment status from Stripe
    result = await stripe.get_payment_status(session_id)
    
    if result.get("success") and (result.get("payment_status") or result.get("status")) == "paid":
        # Find payment transaction
        transaction = await db.payment_transactions.find_one({"session_id": session_id})
        
        if transaction:
            order_id = transaction["order_id"]
            order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
            
            if order and order["status"] != "paid":
                logger.info(f"Stripe status check: marking order {order_id} as paid and provisioning")
                # Mark order as paid
                await orders_collection.update_one(
                    {"_id": str_to_objectid(order_id)},
                    {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "stripe", "payment_id": session_id}}
                )
                await invoices_collection.update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                )
                await db.payment_transactions.update_one(
                    {"session_id": session_id},
                    {"$set": {"payment_status": "paid", "updated_at": datetime.utcnow()}}
                )
                
                user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                if user:
                    background_tasks.add_task(provision_order_services, order_id, order, user)
            elif order and order["status"] == "paid":
                # Already paid — check if services need provisioning (webhook may have set paid but not provisioned)
                existing_services = await services_collection.count_documents({"order_id": order_id})
                if existing_services == 0:
                    logger.info(f"Stripe status check: order {order_id} paid but no services found, re-provisioning")
                    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                    if user:
                        background_tasks.add_task(provision_order_services, order_id, order, user)
    
    return result

@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Stripe webhooks - safety net for payment confirmation"""
    try:
        body = await request.body()
        signature = request.headers.get("Stripe-Signature", "")
        
        settings = await get_settings()
        stripe_settings = settings.get("stripe", {})
        webhook_secret = stripe_settings.get("webhook_secret", "")
        
        # Verify webhook signature if secret is configured
        import json
        if webhook_secret and signature:
            try:
                import stripe
                stripe.api_key = stripe_settings.get("live_secret_key") or stripe_settings.get("test_secret_key") or ""
                event = stripe.Webhook.construct_event(body, signature, webhook_secret)
                logger.info(f"Stripe webhook verified: {event['type']}")
            except stripe.error.SignatureVerificationError:
                logger.error("Stripe webhook signature verification failed")
                raise HTTPException(status_code=400, detail="Invalid signature")
        else:
            event = json.loads(body)
        
        event_type = event.get("type", "") if isinstance(event, dict) else event["type"]
        logger.info(f"Stripe webhook received: {event_type}")
        
        if event_type in ["checkout.session.completed", "payment_intent.succeeded"]:
            session = event.get("data", {}).get("object", {})
            session_id = session.get("id", "")
            payment_status = session.get("payment_status", "")
            
            # Find the order by session_id in payment_transactions
            tx = await db.payment_transactions.find_one({"session_id": session_id})
            
            if tx and payment_status == "paid":
                order_id = tx.get("order_id")
                order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
                
                if order and order.get("status") != "paid":
                    logger.info(f"Stripe webhook: Marking order {order_id} as paid")
                    
                    await orders_collection.update_one(
                        {"_id": str_to_objectid(order_id)},
                        {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "stripe", "payment_id": session_id}}
                    )
                    await invoices_collection.update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                    )
                    await db.payment_transactions.update_one(
                        {"session_id": session_id},
                        {"$set": {"payment_status": "paid"}}
                    )
                    
                    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                    if user:
                        background_tasks.add_task(provision_order_services, order_id, order, user)
                        logger.info(f"Stripe webhook: Order {order_id} paid and provisioning triggered")
                elif order and order.get("status") == "paid":
                    logger.info(f"Stripe webhook: Order {order_id} already paid, skipping")
        
        return {"status": "received"}
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        return {"status": "error"}

# ===== HELCIM ROUTES =====

@app.post("/api/orders/{order_id}/pay/helcim")
async def create_helcim_payment(order_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Initialize HelcimPay.js checkout session for an order"""
    user_id = current_user["sub"]

    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")

    settings = await get_settings()
    helcim_settings = settings.get("helcim", {})
    if not helcim_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Helcim not enabled")

    from helcim_service import get_helcim_service
    helcim = get_helcim_service(helcim_settings)
    if not helcim:
        raise HTTPException(status_code=500, detail="Helcim service not available. Check your API token.")

    currency = settings.get("currency", "USD")
    result = await helcim.initialize_checkout(
        amount=order["total"],
        currency=currency,
        order_id=order_id,
        terminal_id=helcim_settings.get("terminal_id", ""),
    )

    if result["success"]:
        await db.payment_transactions.insert_one({
            "order_id": order_id,
            "user_id": user_id,
            "gateway": "helcim",
            "checkout_token": result["checkoutToken"],
            "secret_token": result["secretToken"],
            "amount": order["total"],
            "currency": currency,
            "payment_status": "pending",
            "created_at": datetime.utcnow()
        })
        return {
            "success": True,
            "checkoutToken": result["checkoutToken"],
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Helcim payment init failed"))


@app.post("/api/orders/{order_id}/helcim/verify")
async def verify_helcim_payment(order_id: str, data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Verify a completed HelcimPay.js transaction and mark order as paid."""
    user_id = current_user["sub"]

    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "paid":
        return {"success": True, "message": "Order already paid"}

    transaction_id = data.get("transactionId", "")
    card_token = data.get("cardToken", "")

    if not transaction_id:
        raise HTTPException(status_code=400, detail="Missing transactionId from Helcim response")

    # Mark order as paid
    await orders_collection.update_one(
        {"_id": str_to_objectid(order_id)},
        {"$set": {
            "status": "paid",
            "paid_at": datetime.utcnow(),
            "payment_method": "helcim",
            "payment_id": str(transaction_id),
        }}
    )

    # Update payment transaction record
    await db.payment_transactions.update_one(
        {"order_id": order_id, "gateway": "helcim"},
        {"$set": {
            "payment_status": "completed",
            "transaction_id": str(transaction_id),
            "card_token": card_token,
            "completed_at": datetime.utcnow(),
        }}
    )

    logger.info(f"Helcim payment verified for order {order_id}, txn={transaction_id}")

    # Provision services in background
    # CMTV local change 2026-09-24: this passed (order_id, user_id), which fails before provisioning even starts
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    background_tasks.add_task(provision_order_services, order_id, order, user)

    return {"success": True, "message": "Payment verified, services being provisioned"}


# ===== SQUARE ROUTES =====

@app.post("/api/orders/{order_id}/pay/square")
async def create_square_payment(order_id: str, data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Create Square payment for order"""
    user_id = current_user["sub"]
    source_id = data.get("source_id")  # Square payment token
    
    if not source_id:
        raise HTTPException(status_code=400, detail="Payment token required")
    
    # Get order
    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    # Get user
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    # Get Square settings
    settings = await get_settings()
    square_settings = settings.get("square", {})
    
    if not square_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Square not enabled")
    
    from square_service import get_square_service
    square = get_square_service(square_settings)
    
    if not square:
        raise HTTPException(status_code=500, detail="Square service not available")
    
    # Create payment
    settings = await get_settings()
    currency = settings.get("currency", "USD")
    result = await square.create_payment(
        amount=order["total"],
        source_id=source_id,
        order_id=order_id,
        customer_email=user.get("email", ""),
        currency=currency
    )
    
    if result["success"] and result["status"] == "COMPLETED":
        # Mark order as paid
        await orders_collection.update_one(
            {"_id": str_to_objectid(order_id)},
            {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "square", "payment_id": result["payment_id"]}}
        )
        
        # Update invoice
        await invoices_collection.update_one(
            {"order_id": order_id},
            {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
        )
        
        # Provision services
        background_tasks.add_task(provision_order_services, order_id, order, user)
        
        return {"success": True, "payment_id": result["payment_id"], "receipt_url": result.get("receipt_url")}
    
    raise HTTPException(status_code=500, detail=result.get("error", "Payment failed"))


# ===== TAGADAPAY ROUTES =====

@app.post("/api/orders/{order_id}/pay/tagadapay")
async def create_tagadapay_payment(order_id: str, request: Request, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Process a TagadaPay card payment"""
    user_id = current_user["sub"]
    body = await request.json()
    
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id), "user_id": user_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    settings = await get_settings()
    from tagadapay_service import get_tagadapay_service
    tagada = get_tagadapay_service(settings)
    if not tagada:
        raise HTTPException(status_code=400, detail="TagadaPay not configured")
    
    tagada_token = body.get("tagadaToken")
    card_number = body.get("card_number") or body.get("cardNumber")
    expiry_date = body.get("expiry") or body.get("expiryDate")
    cvc = body.get("cvc")
    cardholder_name = body.get("cardholder_name") or body.get("cardholderName", "")
    sca_required = body.get("scaRequired", False)
    customer_email = body.get("email", "")
    first_name = body.get("firstName", "")
    last_name = body.get("lastName", "")
    
    if not tagada_token and not card_number:
        raise HTTPException(status_code=400, detail="Card details or tagadaToken required")
    
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    if user:
        customer_email = customer_email or user.get("email", "")
        name_parts = user.get("name", "").split(" ", 1)
        first_name = first_name or name_parts[0]
        last_name = last_name or (name_parts[1] if len(name_parts) > 1 else "")
    
    # If raw card data sent, tokenize server-side via BasisTheory then create tagadaToken
    if card_number and not tagada_token:
        import httpx, base64, json as json_mod
        BT_API_KEY = "key_prod_us_pub_PNMB2AiaECJ463K6QAPNU6"
        try:
            # Parse expiry MM/YY
            exp_parts = expiry_date.split("/")
            exp_month = int(exp_parts[0])
            exp_year = int(exp_parts[1]) + 2000
            
            async with httpx.AsyncClient() as client:
                # Step 1: Tokenize card via BasisTheory REST API
                bt_resp = await client.post(
                    "https://api.basistheory.com/tokens",
                    headers={"BT-API-KEY": BT_API_KEY, "Content-Type": "application/json"},
                    json={
                        "type": "card",
                        "data": {
                            "number": card_number.replace(" ", ""),
                            "expiration_month": exp_month,
                            "expiration_year": exp_year,
                            "cvc": cvc
                        },
                        **({"metadata": {"cardholderName": cardholder_name}} if cardholder_name else {})
                    },
                    timeout=15.0
                )
                if bt_resp.status_code not in (200, 201):
                    error_detail = bt_resp.text
                    logger.error(f"BasisTheory tokenization failed: {bt_resp.status_code} {error_detail}")
                    raise HTTPException(status_code=400, detail=f"Card tokenization failed: {error_detail}")
                
                bt_data = bt_resp.json()
                bt_token_id = bt_data.get("id")
                logger.info(f"BasisTheory token created: {bt_token_id}")
                
                # Step 2: Build tagadaToken (base64-encoded JSON matching @tagadapay/core-js format)
                tagada_token_obj = {
                    "type": "card",
                    "token": bt_token_id,
                    "provider": "basistheory",
                    "nonSensitiveMetadata": {
                        "cardType": "card",
                        "expiryMonth": exp_month,
                        "expiryYear": exp_year,
                        "createdAt": datetime.utcnow().isoformat() + "Z"
                    }
                }
                # Add card details if available
                card_data = bt_data.get("data", {})
                if card_data.get("number"):
                    tagada_token_obj["nonSensitiveMetadata"]["last4"] = str(card_data["number"])[-4:]
                enrichments = bt_data.get("enrichments", {})
                bin_details = enrichments.get("bin_details", {})
                if bin_details.get("card_brand"):
                    tagada_token_obj["nonSensitiveMetadata"]["brand"] = bin_details["card_brand"].lower()
                if bt_data.get("fingerprint"):
                    tagada_token_obj["nonSensitiveMetadata"]["fingerprint"] = bt_data["fingerprint"]
                
                tagada_token = base64.b64encode(json_mod.dumps(tagada_token_obj).encode()).decode()
                logger.info(f"TagadaToken created from BasisTheory token {bt_token_id}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Server-side card tokenization error: {e}")
            raise HTTPException(status_code=400, detail=f"Card processing error: {str(e)}")
    
    # Exchange tagadaToken for a payment instrument
    instrument_result = await tagada.create_payment_instrument(tagada_token, customer_email, first_name, last_name)
    if not instrument_result["success"]:
        raise HTTPException(status_code=400, detail=f"Payment instrument creation failed: {instrument_result['error']}")
    pi_id = instrument_result["payment_instrument_id"]
    customer_id = instrument_result["customer_id"]
    
    # Optional 3DS
    threeds_id = None
    if sca_required:
        threeds_result = await tagada.create_3ds_session(pi_id)
        if threeds_result["success"]:
            threeds_id = threeds_result["threeds_session_id"]
    
    # 3. Process payment
    currency = settings.get("currency", "USD")
    if isinstance(currency, dict):
        currency = currency.get("code", "USD")
    
    site_url = os.getenv("SITE_URL", os.getenv("BACKEND_PUBLIC_URL", ""))
    return_url = f"{site_url}/orders?payment=success&order_id={order_id}"
    
    amount_cents = int(float(order["total"]) * 100)
    
    payment_result = await tagada.process_payment(
        payment_instrument_id=pi_id,
        customer_id=customer_id,
        amount=amount_cents,
        currency=currency,
        threeds_session_id=threeds_id,
        return_url=return_url,
        metadata={"order_id": order_id}
    )
    
    # Save transaction
    await db.payment_transactions.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "gateway": "tagadapay",
        "payment_id": payment_result.get("payment_id"),
        "payment_status": payment_result.get("status", "unknown"),
        "amount": order["total"],
        "created_at": datetime.utcnow()
    })
    
    if payment_result.get("requires_redirect"):
        return {
            "success": True,
            "requires_redirect": True,
            "redirect_url": payment_result["redirect_url"],
            "payment_id": payment_result.get("payment_id")
        }
    
    if payment_result["success"]:
        # Mark order as paid and provision
        await orders_collection.update_one(
            {"_id": str_to_objectid(order_id)},
            {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "tagadapay", "payment_id": payment_result.get("payment_id")}}
        )
        await invoices_collection.update_one(
            {"order_id": order_id},
            {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
        )
        await db.payment_transactions.update_one(
            {"order_id": order_id, "gateway": "tagadapay"},
            {"$set": {"payment_status": "paid"}}
        )
        user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
        if user:
            background_tasks.add_task(provision_order_services, order_id, order, user)
        
        return {"success": True, "status": "paid", "payment_id": payment_result.get("payment_id")}
    
    raise HTTPException(status_code=400, detail=payment_result.get("error", "Payment failed"))

@app.post("/api/webhooks/tagadapay")
async def tagadapay_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle TagadaPay webhooks"""
    try:
        body = await request.json()
        event_type = body.get("type", "")
        logger.info(f"TagadaPay webhook: {event_type}")
        
        if event_type in ("payment.succeeded", "payment.captured"):
            payment_data = body.get("data", {}).get("object", {})
            payment_id = payment_data.get("id", "")
            metadata = payment_data.get("metadata", {})
            order_id = metadata.get("order_id", "")
            
            if order_id:
                order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
                if order and order["status"] != "paid":
                    await orders_collection.update_one(
                        {"_id": str_to_objectid(order_id)},
                        {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "tagadapay", "payment_id": payment_id}}
                    )
                    await invoices_collection.update_one({"order_id": order_id}, {"$set": {"status": "paid", "paid_date": datetime.utcnow()}})
                    await db.payment_transactions.update_one({"order_id": order_id, "gateway": "tagadapay"}, {"$set": {"payment_status": "paid"}})
                    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                    if user:
                        background_tasks.add_task(provision_order_services, order_id, order, user)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"TagadaPay webhook error: {e}")
        return {"status": "error"}

# ===== GHOSTPAY (CRYPTO) ROUTES =====

@app.get("/api/ghostpay/cryptos")
async def get_ghostpay_cryptos(current_user: dict = Depends(get_current_user)):
    """Get available cryptocurrencies from GhostPay"""
    settings = await get_settings()
    from ghostpay_service import get_ghostpay_service
    gp = get_ghostpay_service(settings)
    if not gp:
        raise HTTPException(status_code=400, detail="GhostPay not configured")
    result = await gp.get_cryptos()
    if result["success"]:
        return result["cryptos"]
    raise HTTPException(status_code=500, detail=result.get("error"))

@app.post("/api/orders/{order_id}/pay/ghostpay")
async def create_ghostpay_payment(order_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Create GhostPay crypto payment for order"""
    user_id = current_user["sub"]
    body = await request.json()
    crypto = body.get("crypto", "BTC")
    
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id), "user_id": user_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    settings = await get_settings()
    from ghostpay_service import get_ghostpay_service
    gp = get_ghostpay_service(settings)
    if not gp:
        raise HTTPException(status_code=400, detail="GhostPay not enabled")
    
    base_url = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8001")
    callback_url = f"{base_url}/api/webhooks/ghostpay"
    currency = settings.get("currency", "USD")
    
    result = await gp.create_payment(
        crypto=crypto,
        amount=order["total"],
        external_id=order_id,
        fiat=currency,
        callback_url=callback_url
    )
    
    if result["success"]:
        await db.payment_transactions.insert_one({
            "order_id": order_id,
            "user_id": user_id,
            "gateway": "ghostpay",
            "invoice_id": result["invoice_id"],
            "crypto": crypto,
            "amount_fiat": order["total"],
            "amount_crypto": result.get("amount_crypto"),
            "wallet": result.get("wallet"),
            "payment_status": "pending",
            "created_at": datetime.utcnow()
        })
        return {
            "success": True,
            "invoice_id": result["invoice_id"],
            "payment_url": result["payment_url"],
            "wallet": result["wallet"],
            "amount_crypto": result["amount_crypto"],
            "crypto": crypto,
            "expires_at": result.get("expires_at")
        }
    raise HTTPException(status_code=500, detail=result.get("error", "Payment creation failed"))

@app.get("/api/payments/ghostpay/status/{invoice_id}")
async def check_ghostpay_status(invoice_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Check GhostPay invoice status"""
    from ghostpay_service import GhostPayService
    gp = GhostPayService("")  # Public endpoint, no key needed
    result = await gp.check_invoice(invoice_id)
    
    if result.get("success") and result.get("status") in ("PAID", "OVERPAID"):
        tx = await db.payment_transactions.find_one({"invoice_id": invoice_id})
        if tx:
            order_id = tx["order_id"]
            order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
            if order and order["status"] != "paid":
                await orders_collection.update_one(
                    {"_id": str_to_objectid(order_id)},
                    {"$set": {"status": "paid", "paid_at": datetime.utcnow(), "payment_method": "ghostpay", "payment_id": invoice_id}}
                )
                await invoices_collection.update_one(
                    {"order_id": order_id},
                    {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                )
                await db.payment_transactions.update_one(
                    {"invoice_id": invoice_id},
                    {"$set": {"payment_status": "paid"}}
                )
                user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                if user:
                    background_tasks.add_task(provision_order_services, order_id, order, user)
            elif order and order["status"] == "paid":
                existing = await services_collection.count_documents({"order_id": order_id})
                if existing == 0:
                    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                    if user:
                        background_tasks.add_task(provision_order_services, order_id, order, user)
    
    return {"success": True, "payment_status": result.get("status", "UNKNOWN"), "amount_received": result.get("amount_received"), "transactions": result.get("transactions", [])}

@app.get("/api/ghostpay/prices")
async def get_ghostpay_prices():
    """Get live crypto prices - public, no auth"""
    from ghostpay_service import GhostPayService
    gp = GhostPayService("")
    result = await gp.get_prices()
    if result.get("success"):
        return result["prices"]
    return []

@app.post("/api/webhooks/ghostpay")
async def ghostpay_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GhostPay webhook notifications
    Events: invoice.paid, invoice.partial, invoice.expired
    Payload may contain: event, external_id/orderId, crypto, fiat, balance_fiat, balance_crypto, paid, status, transactions
    Must return 200 OK
    """
    try:
        body = await request.json()
        event = body.get("event", "")
        # GhostPay may send order ID as external_id or orderId
        external_id = body.get("external_id") or body.get("orderId") or body.get("order_id") or ""
        status = body.get("status", "")
        paid = body.get("paid", False)
        
        logger.info(f"GhostPay webhook received: event={event}, external_id={external_id}, status={status}, paid={paid}, body_keys={list(body.keys())}")
        
        # Determine if payment is confirmed
        is_paid = (event == "invoice.paid") or (status in ("PAID", "OVERPAID")) or (paid == True)
        is_partial = (event == "invoice.partial") or (status == "PARTIAL")
        is_expired = (event == "invoice.expired") or (status == "EXPIRED")
        
        if is_paid and external_id:
            try:
                order = await orders_collection.find_one({"_id": str_to_objectid(external_id)})
            except Exception:
                # Try finding by string ID or payment transaction
                order = None
                tx = await db.payment_transactions.find_one({"gateway": "ghostpay", "$or": [{"order_id": external_id}, {"invoice_id": external_id}]})
                if tx:
                    order = await orders_collection.find_one({"_id": str_to_objectid(tx["order_id"])})
                    external_id = tx["order_id"]
            
            # CMTV local change 2026-09-24: GhostPay webhooks are not signed, so never trust the body. Look up the
            # invoice billing created for this order and ask GhostPay itself whether it is PAID/OVERPAID in full.
            if order and order["status"] != "paid":
                gp_tx = await db.payment_transactions.find_one(
                    {"gateway": "ghostpay", "order_id": str(order["_id"])}, sort=[("created_at", -1)])
                from ghostpay_service import get_ghostpay_service
                gp_verify = get_ghostpay_service(await get_settings())
                inv = await gp_verify.check_invoice(gp_tx["invoice_id"]) if (gp_verify and gp_tx and gp_tx.get("invoice_id")) else {"success": False}
                try:
                    inv_fiat = float(inv.get("amount_fiat") or 0)
                except (TypeError, ValueError):
                    inv_fiat = 0.0
                if not (inv.get("success") and inv.get("status") in ("PAID", "OVERPAID")
                        and inv_fiat + 0.01 >= float(order.get("total") or 0)):
                    logger.warning(f"GhostPay webhook NOT trusted for order {order['_id']}: invoice "
                                   f"{gp_tx and gp_tx.get('invoice_id')} status={inv.get('status')} amount_fiat={inv.get('amount_fiat')}")
                    return {"status": "ok"}

            if order and order["status"] != "paid":
                logger.info(f"GhostPay webhook: marking order {external_id} as paid")
                await orders_collection.update_one(
                    {"_id": str_to_objectid(external_id)},
                    {"$set": {
                        "status": "paid",
                        "paid_at": datetime.utcnow(),
                        "payment_method": "ghostpay",
                        "payment_details": {
                            "crypto": body.get("crypto"),
                            "balance_crypto": body.get("balance_crypto"),
                            "balance_fiat": body.get("balance_fiat"),
                            "transactions": body.get("transactions", [])
                        }
                    }}
                )
                await invoices_collection.update_one(
                    {"order_id": external_id},
                    {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                )
                # Update payment transaction
                await db.payment_transactions.update_one(
                    {"order_id": external_id, "gateway": "ghostpay"},
                    {"$set": {"payment_status": "paid", "updated_at": datetime.utcnow()}}
                )
                user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                if user:
                    background_tasks.add_task(provision_order_services, external_id, order, user)
                    logger.info(f"GhostPay: order {external_id} paid and provisioning triggered")
        
        elif is_partial and external_id:
            logger.info(f"GhostPay: partial payment for order {external_id}")
            await db.payment_transactions.update_one(
                {"order_id": external_id, "gateway": "ghostpay"},
                {"$set": {"payment_status": "partial", "amount_received": body.get("balance_crypto"), "updated_at": datetime.utcnow()}}
            )
        
        elif is_expired and external_id:
            logger.info(f"GhostPay: invoice expired for order {external_id}")
            await db.payment_transactions.update_one(
                {"order_id": external_id, "gateway": "ghostpay"},
                {"$set": {"payment_status": "expired", "updated_at": datetime.utcnow()}}
            )
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"GhostPay webhook error: {e}")
        return {"status": "error"}


# ===== BLOCKONOMICS (BITCOIN) ROUTES =====

@app.post("/api/orders/{order_id}/pay/blockonomics")
async def create_blockonomics_payment(order_id: str, current_user: dict = Depends(get_current_user)):
    """Create Bitcoin payment via Blockonomics for order"""
    user_id = current_user["sub"]
    
    # Get order
    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    # Get Blockonomics settings
    settings = await get_settings()
    blockonomics_settings = settings.get("blockonomics", {})
    
    if not blockonomics_settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Bitcoin payments not enabled")
    
    # Build callback URL for webhook - use PUBLIC_URL for production
    public_url = os.getenv("PUBLIC_URL", "https://admin-analytics-46.preview.emergentagent.com")
    callback_url = f"{public_url}/api/webhooks/blockonomics"
    
    from blockonomics_service import get_blockonomics_service
    blockonomics = get_blockonomics_service(blockonomics_settings, callback_url)
    
    if not blockonomics:
        raise HTTPException(status_code=500, detail="Blockonomics service not available")
    
    # Get current BTC price
    price_result = await blockonomics.get_btc_price("USD")
    if not price_result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to fetch BTC price")
    
    btc_price = price_result["price"]
    
    # Convert USD to satoshis
    amount_satoshis = blockonomics.convert_usd_to_satoshis(order["total"], btc_price)
    amount_btc = blockonomics.convert_satoshis_to_btc(amount_satoshis)
    
    # Get new Bitcoin address
    address_result = await blockonomics.get_new_address()
    if not address_result.get("success"):
        error_msg = address_result.get("error", "Failed to generate Bitcoin address")
        # Provide helpful error message for common setup issues
        if "match_callback" in error_msg.lower() or "store" in error_msg.lower():
            error_msg = "Blockonomics setup incomplete. Please create a Store in your Blockonomics dashboard and set the HTTP Callback URL to: " + callback_url
        raise HTTPException(status_code=500, detail=error_msg)
    
    btc_address = address_result["address"]
    
    # Store payment transaction
    await db.payment_transactions.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "gateway": "blockonomics",
        "btc_address": btc_address,
        "amount_usd": order["total"],
        "amount_satoshis": amount_satoshis,
        "amount_btc": amount_btc,
        "btc_price_at_creation": btc_price,
        "payment_status": "pending",
        "confirmations": 0,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=30)
    })
    
    logger.info(f"Blockonomics payment created: {btc_address} for order {order_id}, amount: {amount_btc} BTC")
    
    return {
        "success": True,
        "btc_address": btc_address,
        "amount_satoshis": amount_satoshis,
        "amount_btc": amount_btc,
        "amount_usd": order["total"],
        "btc_price": btc_price,
        "expires_in_minutes": 30,
        "qr_data": f"bitcoin:{btc_address}?amount={amount_btc}"
    }

@app.get("/api/payments/blockonomics/status/{order_id}")
async def check_blockonomics_payment_status(order_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Check Bitcoin payment status for an order"""
    user_id = current_user["sub"]
    
    # Find payment transaction
    transaction = await db.payment_transactions.find_one({
        "order_id": order_id,
        "gateway": "blockonomics"
    })
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    # Get Blockonomics settings
    settings = await get_settings()
    blockonomics_settings = settings.get("blockonomics", {})
    confirmations_required = blockonomics_settings.get("confirmations_required", 1)
    
    # Build callback URL for webhook - use PUBLIC_URL for production
    public_url = os.getenv("PUBLIC_URL", "https://admin-analytics-46.preview.emergentagent.com")
    callback_url = f"{public_url}/api/webhooks/blockonomics"
    
    from blockonomics_service import get_blockonomics_service
    blockonomics = get_blockonomics_service(blockonomics_settings, callback_url)
    
    if not blockonomics:
        raise HTTPException(status_code=500, detail="Blockonomics service not available")
    
    btc_address = transaction["btc_address"]
    
    # Check address balance
    balance_result = await blockonomics.get_address_balance(btc_address)
    
    confirmed_satoshis = balance_result.get("confirmed", 0)
    unconfirmed_satoshis = balance_result.get("unconfirmed", 0)
    total_received = confirmed_satoshis + unconfirmed_satoshis
    
    # Get transaction history for confirmations
    history_result = await blockonomics.get_address_history(btc_address)
    transactions = history_result.get("transactions", [])
    
    # Determine payment status
    expected_satoshis = transaction["amount_satoshis"]
    payment_status = "pending"
    confirmations = 0
    txid = None
    
    if transactions:
        # Get the latest transaction
        latest_tx = transactions[0] if transactions else None
        if latest_tx:
            txid = latest_tx.get("txid")
            confirmations = 1 if latest_tx.get("status") == "confirmed" else 0
    
    # Check if we received enough (allowing 2% variance for network fees)
    if total_received >= expected_satoshis * 0.98:
        if confirmed_satoshis >= expected_satoshis * 0.98:
            payment_status = "confirmed"
            confirmations = max(confirmations, 1)
        else:
            payment_status = "unconfirmed"
    
    # Update transaction record
    await db.payment_transactions.update_one(
        {"_id": transaction["_id"]},
        {"$set": {
            "payment_status": payment_status,
            "confirmations": confirmations,
            "received_satoshis": total_received,
            "txid": txid,
            "updated_at": datetime.utcnow()
        }}
    )
    
    # If payment is confirmed with enough confirmations, mark order as paid
    if payment_status == "confirmed" and confirmations >= confirmations_required:
        order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
        
        if order and order["status"] != "paid":
            await orders_collection.update_one(
                {"_id": str_to_objectid(order_id)},
                {"$set": {
                    "status": "paid",
                    "paid_at": datetime.utcnow(),
                    "payment_method": "blockonomics",
                    "payment_id": txid
                }}
            )
            
            # Update invoice
            await invoices_collection.update_one(
                {"order_id": order_id},
                {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
            )
            
            # Provision services
            user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
            background_tasks.add_task(provision_order_services, order_id, order, user)
            
            logger.info(f"Blockonomics payment confirmed for order {order_id}, txid: {txid}")
    
    return {
        "success": True,
        "payment_status": payment_status,
        "confirmations": confirmations,
        "confirmations_required": confirmations_required,
        "amount_expected_satoshis": expected_satoshis,
        "amount_received_satoshis": total_received,
        "amount_expected_btc": transaction["amount_btc"],
        "amount_received_btc": blockonomics.convert_satoshis_to_btc(total_received) if blockonomics else 0,
        "btc_address": btc_address,
        "txid": txid
    }

@app.post("/api/webhooks/blockonomics")
async def blockonomics_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Blockonomics payment webhooks.
    Blockonomics sends: status (0=unconfirmed, 1=partially confirmed, 2=confirmed), addr, value, txid
    """
    try:
        # CMTV local change 2026-09-24: this callback is unauthenticated and trusts the amount it is sent,
        # so ignore it completely while Blockonomics is disabled (otherwise anyone could mark orders paid).
        if not (await get_settings()).get("blockonomics", {}).get("enabled"):
            logger.warning("Blockonomics webhook ignored: Blockonomics is disabled")
            return {"status": "ignored", "message": "Blockonomics is disabled"}

        # Get webhook data (can be form data or JSON)
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)

        btc_address = payload.get("addr")
        status_code = int(payload.get("status", -1))
        txid = payload.get("txid")
        value_satoshis = int(payload.get("value", 0))
        
        logger.info(f"Blockonomics webhook: address={btc_address}, status={status_code}, value={value_satoshis}, txid={txid}")
        
        if not btc_address:
            return {"status": "error", "message": "Missing address"}
        
        # Find payment transaction by address
        transaction = await db.payment_transactions.find_one({
            "btc_address": btc_address,
            "gateway": "blockonomics"
        })
        
        if not transaction:
            logger.warning(f"Blockonomics webhook: Payment not found for address {btc_address}")
            return {"status": "ok", "message": "Payment not found"}
        
        order_id = transaction["order_id"]
        
        # Determine payment status
        # Status codes: 0=unconfirmed, 1=partial confirm, 2=confirmed (2+ confirmations)
        payment_status = "pending"
        if status_code == 0:
            payment_status = "unconfirmed"
        elif status_code >= 1:
            payment_status = "confirmed"
        
        # Update transaction
        await db.payment_transactions.update_one(
            {"_id": transaction["_id"]},
            {"$set": {
                "payment_status": payment_status,
                "confirmations": status_code,
                "received_satoshis": value_satoshis,
                "txid": txid,
                "updated_at": datetime.utcnow()
            }}
        )
        
        # Get settings for confirmation threshold
        settings = await get_settings()
        blockonomics_settings = settings.get("blockonomics", {})
        confirmations_required = blockonomics_settings.get("confirmations_required", 1)
        
        # If payment confirmed, mark order as paid
        if status_code >= confirmations_required:
            order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
            
            if order and order["status"] != "paid":
                # Check amount received is sufficient
                expected_satoshis = transaction["amount_satoshis"]
                if value_satoshis >= expected_satoshis * 0.98:  # Allow 2% variance
                    await orders_collection.update_one(
                        {"_id": str_to_objectid(order_id)},
                        {"$set": {
                            "status": "paid",
                            "paid_at": datetime.utcnow(),
                            "payment_method": "blockonomics",
                            "payment_id": txid
                        }}
                    )
                    
                    await invoices_collection.update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
                    )
                    
                    # Provision services
                    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
                    background_tasks.add_task(provision_order_services, order_id, order, user)
                    
                    logger.info(f"Blockonomics webhook: Order {order_id} marked as paid, txid: {txid}")
                else:
                    logger.warning(f"Blockonomics webhook: Insufficient payment for order {order_id}. Expected: {expected_satoshis}, Received: {value_satoshis}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Blockonomics webhook error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/reseller/check-username/{username}")
async def check_reseller_username(username: str, current_user: dict = Depends(get_current_user)):
    """Check if a reseller username already exists on any panel"""
    # Check in services collection
    existing_service = await services_collection.find_one(
        {"xtream_username": username, "account_type": "reseller"},
        {"_id": 0, "xtream_username": 1, "panel_name": 1, "status": 1, "user_id": 1}
    )
    # Check in imported users
    existing_imported = await imported_users_collection.find_one(
        {"username": username, "account_type": "reseller"},
        {"_id": 0, "username": 1, "panel_name": 1, "status": 1}
    )
    
    exists = bool(existing_service or existing_imported)
    is_own = False
    if existing_service and existing_service.get("user_id") == current_user["sub"]:
        is_own = True
    
    return {
        "exists": exists,
        "is_own": is_own,
        "panel_name": (existing_service or existing_imported or {}).get("panel_name", ""),
        "status": (existing_service or existing_imported or {}).get("status", "")
    }

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Create new order with coupon and credit support"""
    user_id = current_user["sub"]
    
    # Deduplication: prevent duplicate orders within 30 seconds for same user + items
    item_ids = sorted([i.product_id for i in order_data.items])
    recent_duplicate = await orders_collection.find_one({
        "user_id": user_id,
        "created_at": {"$gte": datetime.utcnow() - timedelta(seconds=30)},
        "status": {"$in": ["pending", "paid"]},
    })
    if recent_duplicate:
        recent_item_ids = sorted([i.get("product_id", "") for i in recent_duplicate.get("items", [])])
        if recent_item_ids == item_ids:
            # Return existing order instead of creating duplicate
            existing_id = str(recent_duplicate["_id"])
            logger.info(f"Duplicate order prevented for user {user_id}, returning existing order {existing_id}")
            return {"order_id": existing_id, "id": existing_id, "message": "Order already exists", "total": recent_duplicate.get("total", 0)}
    
    # Check trial eligibility - 1 trial per customer per panel
    for item in order_data.items:
        product = await products_collection.find_one({"_id": str_to_objectid(item.product_id)})
        if product and product.get("is_trial"):
            panel_type = product.get("panel_type", "xtream")
            panel_index = product.get("panel_index", 0)
            existing_trial = await services_collection.find_one({
                "user_id": user_id,
                "panel_type": panel_type,
                "panel_index": panel_index,
                "account_type": "subscriber",
                "$or": [
                    {"is_trial": True},
                    {"product_name": {"$regex": "trial", "$options": "i"}}
                ]
            })
            if not existing_trial:
                existing_trial_order = await orders_collection.find_one({
                    "user_id": user_id,
                    "status": {"$in": ["paid", "pending"]},
                    "items": {"$elemMatch": {"product_id": item.product_id}}
                })
                if existing_trial_order:
                    existing_trial = existing_trial_order
            if existing_trial:
                raise HTTPException(
                    status_code=400,
                    detail=f"You have already used a trial for this service. Only one trial per customer is allowed."
                )
    
    # Calculate pricing — validate item prices against actual product prices
    # CMTV local change 2026-09-24: always charge the product's own price. The browser's price was trusted
    # unless it was <= 0, so a modified request could buy any plan for $0.01. Each product holds one price.
    actual_total = 0.0
    for item in order_data.items:
        product = await products_collection.find_one({"_id": str_to_objectid(item.product_id)})
        if not product:
            raise HTTPException(status_code=400, detail=f"Product not found: {item.product_name}")
        product_prices = product.get("prices", {}) or {}
        actual_price = float(list(product_prices.values())[0]) if product_prices else 0.0
        if abs(float(item.price or 0) - actual_price) > 0.009:
            logger.warning(f"Order item {item.product_name}: client price ${item.price} replaced by product price ${actual_price}")
        item.price = actual_price
        actual_total += item.price

    subtotal = actual_total
    discount_amount = 0.0
    credits_used = 0.0
    
    # Apply coupon if provided
    if order_data.coupon_code:
        product_ids = [item.product_id for item in order_data.items]
        coupon_result = await coupon_service.validate_coupon(
            order_data.coupon_code,
            subtotal,
            product_ids
        )
        
        if not coupon_result["valid"]:
            raise HTTPException(status_code=400, detail=coupon_result["error"])
        
        discount_amount = coupon_result["discount"]
    
    # Calculate total after discount
    total_after_discount = subtotal - discount_amount
    
    # Apply credits if requested
    if order_data.use_credits > 0:
        user_balance = await credit_service.get_balance(user_id)
        
        # Can't use more credits than available or more than order total
        credits_to_use = min(order_data.use_credits, user_balance, total_after_discount)
        credits_used = credits_to_use
    
    # Final total
    final_total = max(0, total_after_discount - credits_used)
    
    # Create order
    order_dict = {
        "user_id": user_id,
        "items": [item.dict() for item in order_data.items],
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "coupon_code": order_data.coupon_code.upper() if order_data.coupon_code else None,
        "credits_used": credits_used,
        "total": final_total,
        "reseller_credentials": order_data.reseller_credentials,  # Save custom credentials
        "status": "pending",
        "payment_method": "manual",
        "created_at": datetime.utcnow(),
        "paid_at": None
    }
    
    result = await orders_collection.insert_one(order_dict)
    order_id = str(result.inserted_id)
    
    # Record coupon usage
    if order_data.coupon_code and discount_amount > 0:
        await coupon_service.apply_coupon(
            order_data.coupon_code,
            user_id,
            order_id,
            discount_amount
        )
    
    # Deduct credits if used
    if credits_used > 0:
        await credit_service.deduct_credits(
            user_id=user_id,
            amount=credits_used,
            transaction_type="order_payment",
            description=f"Credits used for order #{order_id[:8]}",
            order_id=order_id
        )
    
    # Create invoice with custom numbering
    settings = await get_settings()
    inv_settings = settings.get("invoice", {})
    inv_prefix = inv_settings.get("invoice_prefix", "INV")
    inv_next = inv_settings.get("next_number", 1001)
    inv_padding = inv_settings.get("number_padding", 4)
    invoice_number = f"{inv_prefix}-{str(inv_next).zfill(inv_padding)}"
    
    # Increment the next invoice number in settings
    await settings_collection.update_one({}, {"$set": {"invoice.next_number": inv_next + 1}}, upsert=True)
    
    invoice_dict = {
        "order_id": order_id,
        "user_id": user_id,
        "invoice_number": invoice_number,
        "total": final_total,
        "status": "unpaid" if final_total > 0 else "paid",
        "due_date": datetime.utcnow() + timedelta(days=7),
        "paid_date": datetime.utcnow() if final_total == 0 else None,
        "pdf_path": None,
        "created_at": datetime.utcnow()
    }
    
    invoice_result = await invoices_collection.insert_one(invoice_dict)
    invoice_id = str(invoice_result.inserted_id)
    
    # Send "New Order" Telegram notification
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    order_items_text = "\n".join([f"- {item.product_name} (${item.price})" for item in order_data.items])
    await send_telegram_notification(
        "new_order",
        f"🛒 *New Order Created*\n\nCustomer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nTotal: ${final_total:.2f}\n\nItems:\n{order_items_text}"
    )
    await send_email_notification(
        "new_order",
        "New Order Created",
        f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nTotal: ${final_total:.2f}\n\nItems:\n{order_items_text}"
    )
    await send_sms_notification("new_order", f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nTotal: ${final_total:.2f}\n\nItems:\n{order_items_text}")
    
    # If fully paid with credits, mark order as paid and provision service
    if final_total == 0:
        await orders_collection.update_one(
            {"_id": str_to_objectid(order_id)},
            {"$set": {"status": "paid", "paid_at": datetime.utcnow()}}
        )
        
        # Re-fetch the updated order for provisioning
        paid_order = await orders_collection.find_one({"_id": str_to_objectid(order_id)}, {"_id": 0})
        if paid_order:
            paid_order["id"] = order_id
            background_tasks.add_task(provision_order_services, order_id, paid_order, user)
        logger.info(f"Order {order_id} fully paid with credits - auto-provisioning triggered")
    
    return {
        "order_id": order_id,
        "invoice_id": invoice_id,
        "status": "paid" if final_total == 0 else "pending",
        "subtotal": subtotal,
        "discount": discount_amount,
        "credits_used": credits_used,
        "total": final_total,
        "message": "Order created successfully." + (" Paid with credits!" if final_total == 0 else " Please proceed to payment.")
    }

@app.get("/api/orders")
async def get_orders(current_user: dict = Depends(get_current_user)):
    """Get user orders"""
    user_id = current_user["sub"]
    orders = []
    
    async for order in orders_collection.find({"user_id": user_id}).sort("created_at", -1):
        order["id"] = str(order["_id"])
        del order["_id"]
        orders.append(order)
    
    return orders

@app.get("/api/orders/{order_id}")
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """Get single order"""
    user_id = current_user["sub"]
    order = await orders_collection.find_one({
        "_id": str_to_objectid(order_id),
        "user_id": user_id
    })
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order["id"] = str(order["_id"])
    del order["_id"]
    return order

# ===== SERVICE ROUTES =====

@app.get("/api/services")
async def get_services(current_user: dict = Depends(get_current_user)):
    """Get user services with product setup instructions"""
    user_id = current_user["sub"]
    services = []
    settings = await get_settings()
    
    async for service in services_collection.find({"user_id": user_id}).sort("created_at", -1):
        service["id"] = str(service["_id"])
        del service["_id"]
        
        # Sync expiry from imported_users (panel-synced data is the source of truth)
        if service.get("xtream_username") and service.get("status") in ("active", "expired", "suspended"):
            imported = await imported_users_collection.find_one({"username": service["xtream_username"]})
            if imported and imported.get("expiry_date"):
                panel_expiry = imported["expiry_date"]
                service_expiry = service.get("expiry_date")
                # Convert strings to datetime if needed
                if isinstance(panel_expiry, str):
                    try: panel_expiry = datetime.fromisoformat(panel_expiry.replace("Z", "+00:00").replace("+00:00", ""))
                    except ValueError: panel_expiry = None
                if isinstance(service_expiry, str):
                    try: service_expiry = datetime.fromisoformat(service_expiry.replace("Z", "+00:00").replace("+00:00", ""))
                    except ValueError: service_expiry = None
                # Update if panel expiry differs from service expiry
                if panel_expiry and (not service_expiry or abs((panel_expiry - service_expiry).total_seconds()) > 3600):
                    service["expiry_date"] = panel_expiry
                    await services_collection.update_one(
                        {"_id": str_to_objectid(service["id"])},
                        {"$set": {"expiry_date": panel_expiry}}
                    )
        
        # Get product details to include setup instructions
        if service.get("product_id"):
            product = await products_collection.find_one({"_id": str_to_objectid(service["product_id"])})
            if product:
                service["setup_instructions"] = product.get("setup_instructions", "")
        
        # Ensure streaming_url is populated from panel settings if missing
        if not service.get("streaming_url"):
            panel_type = service.get("panel_type") or "xtream"
            panel_index = service.get("panel_index") or 0
            if isinstance(panel_index, str):
                try: panel_index = int(panel_index)
                except (ValueError, TypeError): panel_index = 0
            panels = settings.get(panel_type, {}).get("panels", [])
            if panels and panel_index < len(panels):
                p = panels[panel_index]
                service["streaming_url"] = p.get("streaming_url") or p.get("portal_url") or p.get("panel_url", "")
        
        services.append(service)
    
    return services

@app.get("/api/services/{service_id}")
async def get_service(service_id: str, current_user: dict = Depends(get_current_user)):
    """Get single service"""
    user_id = current_user["sub"]
    service = await services_collection.find_one({
        "_id": str_to_objectid(service_id),
        "user_id": user_id
    })
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    service["id"] = str(service["_id"])
    del service["_id"]
    return service

# ===== INVOICE ROUTES =====

@app.get("/api/invoices")
async def get_invoices(current_user: dict = Depends(get_current_user)):
    """Get user invoices"""
    user_id = current_user["sub"]
    invoices = []
    
    async for invoice in invoices_collection.find({"user_id": user_id}).sort("created_at", -1):
        invoice["id"] = str(invoice["_id"])
        del invoice["_id"]
        invoices.append(invoice)
    
    return invoices

@app.get("/api/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(invoice_id: str, current_user: dict = Depends(get_current_user)):
    """Download invoice PDF"""
    user_id = current_user["sub"]
    is_admin = current_user.get("role") == "admin"
    
    # Build query - admin can access any invoice, users only their own
    query = {"_id": str_to_objectid(invoice_id)}
    if not is_admin:
        query["user_id"] = user_id
    
    invoice = await invoices_collection.find_one(query)
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Generate PDF if not exists
    if not invoice.get("pdf_path") or not os.path.exists(invoice["pdf_path"]):
        # Get order and user info (use invoice's user_id, not current user)
        order = await orders_collection.find_one({"_id": str_to_objectid(invoice["order_id"])})
        user = await users_collection.find_one({"_id": str_to_objectid(invoice["user_id"])})
        settings = await get_settings()
        inv_settings = settings.get("invoice", {})
        
        invoice_data = {
            "invoice_number": invoice["invoice_number"],
            "created_at": invoice["created_at"].strftime("%Y-%m-%d"),
            "due_date": invoice["due_date"].strftime("%Y-%m-%d"),
            "order_id": invoice["order_id"],
            "status": invoice["status"],
            "customer_name": user["name"],
            "customer_email": user["email"],
            "items": order["items"],
            "total": invoice["total"],
            "subtotal": order.get("subtotal", invoice["total"]),
            "discount_amount": order.get("discount_amount", 0),
            "credits_used": order.get("credits_used", 0),
            "company_name": inv_settings.get("company_name") or settings.get("company_name", "IPTV Billing"),
            "company_email": inv_settings.get("company_email") or settings.get("company_email", "")
        }
        
        invoice_generator = get_invoice_generator()
        pdf_path = invoice_generator.generate_invoice(invoice_data, inv_settings)
        
        # Update invoice with PDF path
        await invoices_collection.update_one(
            {"_id": str_to_objectid(invoice_id)},
            {"$set": {"pdf_path": pdf_path}}
        )
    else:
        pdf_path = invoice["pdf_path"]
    
    # Return the PDF file
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"invoice_{invoice['invoice_number']}.pdf")

# ===== TICKET ROUTES =====

@app.post("/api/tickets")
async def create_ticket(ticket_data: TicketCreate, current_user: dict = Depends(get_current_user)):
    """Create a support ticket"""
    user_id = current_user["sub"]
    
    # Get service name if service_id provided
    service_name = None
    if ticket_data.service_id:
        service = await services_collection.find_one({"_id": str_to_objectid(ticket_data.service_id)})
        if service:
            service_name = service.get("product_name")
    
    ticket_dict = {
        "user_id": user_id,
        "subject": ticket_data.subject,
        "status": "open",
        "priority": ticket_data.priority,
        "service_id": ticket_data.service_id,
        "service_name": service_name,
        "messages": [{
            "message": ticket_data.message,
            "is_admin": False,
            "created_at": datetime.utcnow()
        }],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await tickets_collection.insert_one(ticket_dict)
    ticket_dict["id"] = str(result.inserted_id)
    
    # Get user info for notification
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    # Send "New Support Ticket" Telegram notification
    await send_telegram_notification(
        "new_support_ticket",
        f"🎫 *New Support Ticket*\n\nFrom: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nSubject: {ticket_data.subject}\nPriority: {ticket_data.priority}\n\nMessage:\n{ticket_data.message[:200]}..."
    )
    await send_email_notification(
        "new_support_ticket",
        "New Support Ticket",
        f"From: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nSubject: {ticket_data.subject}\nPriority: {ticket_data.priority}\n\nMessage:\n{ticket_data.message[:200]}..."
    )
    await send_sms_notification("new_support_ticket", f"From: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nSubject: {ticket_data.subject}\nPriority: {ticket_data.priority}\n\nMessage:\n{ticket_data.message[:200]}...")
    
    return {"message": "Ticket created successfully", "ticket_id": ticket_dict["id"]}

@app.get("/api/tickets")
async def get_tickets(current_user: dict = Depends(get_current_user)):
    """Get user's tickets"""
    user_id = current_user["sub"]
    tickets = []
    
    async for ticket in tickets_collection.find({"user_id": user_id}).sort("created_at", -1):
        ticket["id"] = str(ticket["_id"])
        del ticket["_id"]
        tickets.append(ticket)
    
    return tickets

@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, current_user: dict = Depends(get_current_user)):
    """Get single ticket"""
    user_id = current_user["sub"]
    ticket = await tickets_collection.find_one({
        "_id": str_to_objectid(ticket_id),
        "user_id": user_id
    })
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket["id"] = str(ticket["_id"])
    del ticket["_id"]
    return ticket

@app.post("/api/tickets/{ticket_id}/reply")
async def customer_reply_to_ticket(ticket_id: str, reply: dict, current_user: dict = Depends(get_current_user)):
    """Customer adds a reply to their own ticket"""
    user_id = current_user["sub"]
    
    ticket = await tickets_collection.find_one({
        "_id": str_to_objectid(ticket_id),
        "user_id": user_id
    })
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    message = reply.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    new_message = {
        "message": message,
        "is_admin": False,
        "created_at": datetime.utcnow()
    }
    
    await tickets_collection.update_one(
        {"_id": str_to_objectid(ticket_id)},
        {
            "$push": {"messages": new_message},
            "$set": {"status": "open", "updated_at": datetime.utcnow()}
        }
    )
    
    # Notify admin via Telegram/email
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    try:
        await send_telegram_notification(
            "ticket_reply",
            f"💬 *Customer Reply*\n\nTicket: #{ticket_id[:8]}...\nSubject: {ticket.get('subject', 'N/A')}\nFrom: {user.get('name', 'Unknown') if user else 'Unknown'}\n\nMessage:\n{message[:200]}..."
        )
    except Exception:
        pass
    
    try:
        await send_email_notification(
            "ticket_reply",
            f"Customer replied to ticket #{ticket_id[:8]}: {ticket.get('subject', 'N/A')}",
            f"From: {user.get('name', 'Unknown') if user else 'Unknown'}\n\nMessage:\n{message[:300]}"
        )
    except Exception:
        pass
    
    return {"message": "Reply added successfully"}

@app.get("/api/admin/tickets")
async def get_all_tickets(current_user: dict = Depends(get_current_admin_user)):
    """Get all support tickets"""
    tickets = []
    
    async for ticket in tickets_collection.find().sort("created_at", -1):
        user = await users_collection.find_one({"_id": str_to_objectid(ticket["user_id"])})
        
        ticket["id"] = str(ticket["_id"])
        ticket["customer_name"] = user["name"] if user else "Unknown"
        ticket["customer_email"] = user["email"] if user else "Unknown"
        del ticket["_id"]
        tickets.append(ticket)
    
    return tickets

@app.post("/api/admin/tickets/{ticket_id}/reply")
async def reply_to_ticket(ticket_id: str, reply: dict, current_user: dict = Depends(get_current_admin_user)):
    """Add admin reply to ticket"""
    ticket = await tickets_collection.find_one({"_id": str_to_objectid(ticket_id)})
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    new_message = {
        "message": reply["message"],
        "is_admin": True,
        "created_at": datetime.utcnow()
    }
    
    new_status = reply.get("status", ticket.get("status", "in_progress"))
    
    await tickets_collection.update_one(
        {"_id": str_to_objectid(ticket_id)},
        {
            "$push": {"messages": new_message},
            "$set": {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
        }
    )
    
    # Get customer info for notification
    user = await users_collection.find_one({"_id": str_to_objectid(ticket["user_id"])})
    
    # Send "Ticket Reply" Telegram notification
    await send_telegram_notification(
        "ticket_reply",
        f"💬 *Ticket Reply*\n\nTicket: #{ticket_id[:8]}...\nSubject: {ticket.get('subject', 'N/A')}\nCustomer: {user.get('name', 'Unknown') if user else 'Unknown'}\n\nAdmin replied:\n{reply['message'][:200]}..."
    )
    await send_email_notification(
        "ticket_reply",
        "Ticket Reply",
        f"Ticket: #{ticket_id[:8]}...\nSubject: {ticket.get('subject', 'N/A')}\nCustomer: {user.get('name', 'Unknown') if user else 'Unknown'}\n\nAdmin replied:\n{reply['message'][:200]}..."
    )
    await send_sms_notification("ticket_reply", f"Ticket: #{ticket_id[:8]}...\nSubject: {ticket.get('subject', 'N/A')}\nCustomer: {user.get('name', 'Unknown') if user else 'Unknown'}\n\nAdmin replied:\n{reply['message'][:200]}...")
    
    return {"message": "Ticket status updated"}

@app.post("/api/admin/customers/{customer_id}/change-password")
async def admin_change_customer_password(
    customer_id: str,
    new_password: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Admin changes a customer's password"""
    user = await users_collection.find_one({"_id": str_to_objectid(customer_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Hash the new password
    hashed_password = get_password_hash(new_password)
    
    # Update password
    await users_collection.update_one(
        {"_id": str_to_objectid(customer_id)},
        {"$set": {"password": hashed_password}}
    )
    
    logger.info(f"Admin {current_user['sub']} changed password for user {customer_id}")
    
    return {"message": "Password changed successfully"}

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@app.post("/api/admin/change-password")
async def admin_change_own_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_admin_user)
):
    """Admin changes their own password"""
    admin_id = current_user["sub"]
    
    # Get admin user
    admin = await users_collection.find_one({"_id": str_to_objectid(admin_id)})
    
    if not admin:
        raise HTTPException(status_code=404, detail="Admin user not found")
    
    # Verify current password
    if not verify_password(request.current_password, admin["password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    # Hash new password
    hashed_password = get_password_hash(request.new_password)
    
    # Update password
    await users_collection.update_one(
        {"_id": str_to_objectid(admin_id)},
        {"$set": {"password": hashed_password}}
    )
    
    logger.info(f"Admin {admin_id} changed their own password")
    
    return {"message": "Password changed successfully. Please login again."}

@app.put("/api/admin/tickets/{ticket_id}/status")
async def update_ticket_status(ticket_id: str, status_update: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update ticket status"""
    ticket = await tickets_collection.find_one({"_id": str_to_objectid(ticket_id)})
    
    await tickets_collection.update_one(
        {"_id": str_to_objectid(ticket_id)},
        {"$set": {"status": status_update["status"], "updated_at": datetime.utcnow()}}
    )
    
    # Send email if ticket is closed
    if status_update["status"] == "closed" and ticket:
        try:
            user = await users_collection.find_one({"_id": str_to_objectid(ticket["user_id"])})
            if user:
                settings = await get_settings()
                smtp_settings = settings.get("smtp", {})
                email_service = get_email_service(smtp_settings)
                if email_service and email_service.enabled:
                    await email_service.send_ticket_closed(
                        user["email"],
                        user["name"],
                        ticket_id,
                        ticket["subject"]
                    )
        except Exception as e:
            logger.error(f"Failed to send ticket closed email: {e}")
    
    return {"message": "Ticket status updated"}

# ===== ADMIN ROUTES =====

@app.get("/api/admin/stats")
async def get_admin_stats(current_user: dict = Depends(get_current_admin_user)):
    """Get admin dashboard statistics"""
    # Count stats
    total_customers = await users_collection.count_documents({"role": "user"})
    total_orders = await orders_collection.count_documents({})
    paid_orders = await orders_collection.count_documents({"status": "paid"})
    pending_orders = await orders_collection.count_documents({"status": "pending"})
    total_services = await services_collection.count_documents({})
    active_services = await services_collection.count_documents({"status": "active"})
    pending_tickets = await tickets_collection.count_documents({"status": {"$in": ["open", "in_progress"]}})
    
    # Ticket status breakdown
    awaiting_reply_tickets = await tickets_collection.count_documents({"status": "open"})
    open_tickets = await tickets_collection.count_documents({"status": "open"})
    in_progress_tickets = await tickets_collection.count_documents({"status": "in_progress"})
    closed_tickets = await tickets_collection.count_documents({"status": "closed"})
    
    # Revenue stats
    revenue_pipeline = [
        {"$match": {"status": "paid"}},
        {"$group": {"_id": None, "total_revenue": {"$sum": "$total"}}}
    ]
    revenue_result = await orders_collection.aggregate(revenue_pipeline).to_list(length=1)
    total_revenue = revenue_result[0]["total_revenue"] if revenue_result else 0
    
    # 7-day revenue data for chart
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    revenue_by_day = []
    for i in range(7):
        day_start = seven_days_ago + timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        
        day_revenue_pipeline = [
            {
                "$match": {
                    "status": "paid",
                    "paid_at": {
                        "$gte": day_start,
                        "$lt": day_end
                    }
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$total"}}}
        ]
        day_result = await orders_collection.aggregate(day_revenue_pipeline).to_list(length=1)
        day_total = day_result[0]["total"] if day_result else 0
        
        revenue_by_day.append({
            "date": day_start.strftime("%b %d"),
            "revenue": round(day_total, 2)
        })
    
    # Recent orders
    recent_orders = []
    async for order in orders_collection.find().sort("created_at", -1).limit(10):
        user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
        order["id"] = str(order["_id"])
        order["customer_name"] = user["name"] if user else "Unknown"
        order["customer_email"] = user["email"] if user else "Unknown"
        del order["_id"]
        recent_orders.append(order)
    
    return {
        "total_customers": total_customers,
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "pending_orders": pending_orders,
        "total_services": total_services,
        "active_services": active_services,
        "pending_tickets": pending_tickets,
        "total_revenue": total_revenue,
        "ticket_status": {
            "awaiting_reply": awaiting_reply_tickets,
            "open": open_tickets,
            "in_progress": in_progress_tickets,
            "closed": closed_tickets
        },
        "revenue_data": revenue_by_day,
        "recent_orders": recent_orders
    }

# Pydantic model for creating customers
class CreateCustomerRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

# ===== STAFF MANAGEMENT =====

@app.get("/api/admin/staff")
async def get_staff_members(current_user: dict = Depends(get_current_admin_user)):
    """Get all staff accounts"""
    staff = []
    async for user in users_collection.find({"role": "staff"}):
        staff.append({
            "id": str(user["_id"]),
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "permissions": user.get("permissions", []),
            "created_at": user.get("created_at"),
        })
    return staff


@app.post("/api/admin/staff")
async def create_staff_account(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Create a staff account with limited permissions"""
    email = data.get("email", "").strip().lower()
    name = data.get("name", "").strip()
    password = data.get("password", "")
    permissions = data.get("permissions", [])

    if not email or not password or not name:
        raise HTTPException(status_code=400, detail="Email, name, and password required")

    existing = await email_in_use(email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")

    valid_perms = ["tickets", "customers", "imported_users", "orders", "dashboard", "services"]
    permissions = [p for p in permissions if p in valid_perms]

    import secrets
    staff_doc = {
        "email": email,
        "name": name,
        "password": get_password_hash(password),
        "role": "staff",
        "permissions": permissions,
        "email_verified": True,
        "referral_code": secrets.token_hex(4),
        "credit_balance": 0.0,
        "created_at": datetime.utcnow(),
    }
    result = await users_collection.insert_one(staff_doc)
    return {"success": True, "id": str(result.inserted_id), "message": f"Staff account '{name}' created"}


@app.put("/api/admin/staff/{staff_id}")
async def update_staff_account(staff_id: str, data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update staff permissions or details"""
    staff = await users_collection.find_one({"_id": str_to_objectid(staff_id), "role": "staff"})
    if not staff:
        raise HTTPException(status_code=404, detail="Staff account not found")

    update = {}
    if "name" in data: update["name"] = data["name"]
    if "permissions" in data:
        valid_perms = ["tickets", "customers", "imported_users", "orders", "dashboard", "services"]
        update["permissions"] = [p for p in data["permissions"] if p in valid_perms]
    if "password" in data and data["password"]:
        update["password"] = get_password_hash(data["password"])

    if update:
        await users_collection.update_one({"_id": str_to_objectid(staff_id)}, {"$set": update})
    return {"success": True, "message": "Staff account updated"}


@app.delete("/api/admin/staff/{staff_id}")
async def delete_staff_account(staff_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete a staff account"""
    result = await users_collection.delete_one({"_id": str_to_objectid(staff_id), "role": "staff"})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Staff account not found")
    return {"success": True, "message": "Staff account deleted"}


@app.post("/api/admin/customers/create")
async def create_customer(data: CreateCustomerRequest, current_user: dict = Depends(get_current_admin_user)):
    """Create a new customer account"""
    
    # Check if email already exists
    existing_user = await email_in_use(data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Validate password
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Hash password
    hashed_password = get_password_hash(data.password)
    
    # Generate referral code
    import secrets
    referral_code = secrets.token_urlsafe(6).upper()[:8]
    
    # Create user document
    user_doc = {
        "email": data.email.lower(),
        "password": hashed_password,
        "name": data.name,
        "role": "user",
        "email_verified": True,  # Admin-created accounts are pre-verified
        "credit_balance": 0.0,
        "referral_code": referral_code,
        "created_at": datetime.utcnow()
    }
    
    result = await users_collection.insert_one(user_doc)
    
    logger.info(f"Admin {current_user.get('email')} created customer account: {data.email}")
    
    return {
        "success": True,
        "message": f"Customer '{data.name}' created successfully",
        "customer": {
            "id": str(result.inserted_id),
            "name": data.name,
            "email": data.email.lower(),
            "referral_code": referral_code
        }
    }

@app.get("/api/admin/customers")
async def get_all_customers(search: str = "", current_user: dict = Depends(get_current_admin_user)):
    """Get all customers with optional search"""
    query = {"role": "user"}
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"panel_username": {"$regex": search, "$options": "i"}}
        ]
    customers = []
    async for user in users_collection.find({"role": "user"}).sort("created_at", -1):
        # Get user's services count
        services_count = await services_collection.count_documents({"user_id": str(user["_id"])})
        orders_count = await orders_collection.count_documents({"user_id": str(user["_id"])})
        
        user["id"] = str(user["_id"])
        user["services_count"] = services_count
        user["orders_count"] = orders_count
        del user["_id"]
        del user["password"]
        customers.append(user)
    
    return customers

@app.get("/api/admin/customers/{customer_id}")
async def get_customer_details(customer_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Get detailed customer information"""
    user = await users_collection.find_one({"_id": str_to_objectid(customer_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Get customer's services
    services = []
    async for service in services_collection.find({"user_id": customer_id}).sort("created_at", -1):
        service["id"] = str(service["_id"])
        del service["_id"]
        services.append(service)
    
    # Get customer's orders
    orders = []
    async for order in orders_collection.find({"user_id": customer_id}).sort("created_at", -1):
        order["id"] = str(order["_id"])
        del order["_id"]
        orders.append(order)
    
    # Get customer's invoices
    invoices = []
    async for invoice in invoices_collection.find({"user_id": customer_id}).sort("created_at", -1):
        invoice["id"] = str(invoice["_id"])
        del invoice["_id"]
        invoices.append(invoice)
    
    user["id"] = str(user["_id"])
    del user["_id"]
    del user["password"]
    
    return {
        "customer": user,
        "services": services,
        "orders": orders,
        "invoices": invoices
    }

@app.put("/api/admin/customers/{customer_id}")
async def update_customer(customer_id: str, update_data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update customer information"""
    user = await users_collection.find_one({"_id": str_to_objectid(customer_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Prepare update data
    update_fields = {}
    if "name" in update_data:
        update_fields["name"] = update_data["name"]
    if "email" in update_data:
        # Check if new email already exists
        existing = await email_in_use(update_data["email"], exclude_user_id=customer_id)
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        update_fields["email"] = update_data["email"]
    
    if update_fields:
        await users_collection.update_one(
            {"_id": str_to_objectid(customer_id)},
            {"$set": update_fields}
        )
    
    return {"message": "Customer updated successfully"}

@app.get("/api/refunds/enabled")
async def check_refunds_enabled():
    """Public endpoint to check if refunds are enabled (no auth required)"""
    settings = await get_settings()
    return {"enabled": settings.get("refunds_enabled", True)}
    return {"message": "Customer updated successfully"}

@app.delete("/api/admin/customers/{customer_id}")
async def delete_customer(customer_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete customer and all associated data"""
    user = await users_collection.find_one({"_id": str_to_objectid(customer_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Delete customer's orders, invoices, and services
    await orders_collection.delete_many({"user_id": customer_id})
    await invoices_collection.delete_many({"user_id": customer_id})
    await services_collection.delete_many({"user_id": customer_id})
    
    # Delete customer
    await users_collection.delete_one({"_id": str_to_objectid(customer_id)})
    
    return {"message": "Customer and all associated data deleted successfully"}

@app.get("/api/admin/orders")
async def get_all_orders(current_user: dict = Depends(get_current_admin_user)):
    """Get all orders"""
    orders = []
    
    async for order in orders_collection.find().sort("created_at", -1):
        user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
        order["id"] = str(order["_id"])
        order["customer_name"] = user["name"] if user else "Unknown"
        order["customer_email"] = user["email"] if user else "Unknown"
        del order["_id"]
        orders.append(order)
    
    return orders

@app.get("/api/payment/config")
async def get_payment_config():
    """Get public payment configuration (no auth required)"""
    settings = await get_settings()
    
    return {
        "paypal": {
            "enabled": settings.get("paypal", {}).get("enabled", False),
            "client_id": settings.get("paypal", {}).get("client_id", ""),
            "mode": settings.get("paypal", {}).get("mode", "sandbox")
        },
        "stripe": {
            "enabled": settings.get("stripe", {}).get("enabled", False),
            "crypto_enabled": settings.get("stripe", {}).get("crypto_enabled", True),
            "mode": settings.get("stripe", {}).get("mode", "test"),
            "publishable_key": settings.get("stripe", {}).get("live_publishable_key", "") if settings.get("stripe", {}).get("mode") == "live" else settings.get("stripe", {}).get("test_publishable_key", "")
        },
        "square": {
            "enabled": settings.get("square", {}).get("enabled", False),
            "application_id": settings.get("square", {}).get("application_id", ""),
            "location_id": settings.get("square", {}).get("location_id", ""),
            "environment": settings.get("square", {}).get("environment", "sandbox")
        },
        "blockonomics": {
            "enabled": settings.get("blockonomics", {}).get("enabled", False)
        },
        "emt": {
            "enabled": settings.get("emt", {}).get("enabled", False),
            "instructions": settings.get("emt", {}).get("instructions", "")
        },
        "zelle": {
            "enabled": settings.get("zelle", {}).get("enabled", False),
            "instructions": settings.get("zelle", {}).get("instructions", "")
        },
        "cashapp": {
            "enabled": settings.get("cashapp", {}).get("enabled", False),
            "instructions": settings.get("cashapp", {}).get("instructions", "")
        },
        "venmo": {
            "enabled": settings.get("venmo", {}).get("enabled", False),
            "instructions": settings.get("venmo", {}).get("instructions", "")
        },
        "wise": {
            "enabled": settings.get("wise", {}).get("enabled", False),
            "instructions": settings.get("wise", {}).get("instructions", "")
        },
        "helcim": {
            "enabled": settings.get("helcim", {}).get("enabled", False)
        },
        "ghostpay": {
            "enabled": settings.get("ghostpay", {}).get("enabled", False),
            "api_key": settings.get("ghostpay", {}).get("api_key", "")
        },
        "tagadapay": {
            "enabled": settings.get("tagadapay", {}).get("enabled", False),
            "store_id": settings.get("tagadapay", {}).get("store_id", "")
        },
        "manual": {
            "enabled": settings.get("manual", {}).get("enabled", True)
        },
        "payment_method_order": settings.get("payment_method_order", ["manual", "emt", "zelle", "cashapp", "venmo", "wise", "helcim", "stripe", "paypal", "square", "blockonomics", "ghostpay", "tagadapay"]),
        "currency": {"code": settings.get("currency", "USD"), "symbol": CURRENCY_SYMBOLS.get(settings.get("currency", "USD"), "$")}
    }

@app.post("/api/admin/orders/{order_id}/mark-paid")
async def mark_order_paid(order_id: str, background_tasks: BackgroundTasks, 
                          current_user: dict = Depends(get_current_admin_user)):
    """Mark order as paid and provision services"""
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")
    
    # Update order status
    await orders_collection.update_one(
        {"_id": str_to_objectid(order_id)},
        {"$set": {"status": "paid", "paid_at": datetime.utcnow()}}
    )
    
    # Update invoice status
    await invoices_collection.update_one(
        {"order_id": order_id},
        {"$set": {"status": "paid", "paid_date": datetime.utcnow()}}
    )
    
    # Get user
    user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
    
    # Send payment received email
    email_service = await get_configured_email_service()
    if email_service and email_service.enabled:
        await email_service.send_payment_received(
            user_email=user["email"],
            user_name=user["name"],
            order_id=order_id,
            total=order["total"]
        )
    
    # Send "Payment Received" Telegram notification
    order_items_text = "\n".join([f"- {item['product_name']}" for item in order.get('items', [])])
    await send_telegram_notification(
        "payment_received",
        f"💰 *Payment Received*\n\nCustomer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nAmount: ${order['total']:.2f}\n\nItems:\n{order_items_text}"
    )
    await send_email_notification(
        "payment_received",
        "Payment Received",
        f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nAmount: ${order['total']:.2f}\n\nItems:\n{order_items_text}"
    )
    await send_sms_notification("payment_received", f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nAmount: ${order['total']:.2f}\n\nItems:\n{order_items_text}")
    
    # Provision services
    background_tasks.add_task(provision_order_services, order_id, order, user)
    
    return {"message": "Order marked as paid, provisioning services..."}

@app.post("/api/admin/orders/{order_id}/cancel")
async def cancel_order(order_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Cancel a pending order"""
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order["status"] == "paid":
        raise HTTPException(status_code=400, detail="Cannot cancel a paid order")
    
    if order["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="Order already cancelled")
    
    # Update order status to cancelled
    await orders_collection.update_one(
        {"_id": str_to_objectid(order_id)},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}}
    )
    
    # CMTV local change 2026-09-24: credits are deducted when the order is created, so give them back on cancel
    if (order.get("credits_used") or 0) > 0:
        await credit_service.add_credits(
            user_id=order["user_id"], amount=float(order["credits_used"]),
            transaction_type="order_cancelled_refund", description=f"Credits returned: order {order_id} cancelled",
            order_id=order_id, bypass_enabled_check=True
        )
    
    # Update invoice status
    await invoices_collection.update_one(
        {"order_id": order_id},
        {"$set": {"status": "cancelled"}}
    )
    
    # Delete any pending payment transactions
    await db.payment_transactions.delete_many({
        "order_id": order_id,
        "payment_status": "pending"
    })
    
    # Send cancellation email
    try:
        user = await users_collection.find_one({"_id": str_to_objectid(order["user_id"])})
        if user:
            email_service = await get_configured_email_service()
            if email_service and email_service.enabled:
                await email_service.send_order_cancelled(
                    user["email"], 
                    user["name"], 
                    order_id,
                    "Order cancelled by administrator"
                )
    except Exception as e:
        logger.error(f"Failed to send cancellation email: {e}")
    
    logger.info(f"Order {order_id} cancelled by admin {current_user['sub']}")
    
    return {"message": "Order cancelled successfully"}

@app.delete("/api/admin/orders/{order_id}")
async def delete_order(order_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Permanently delete an order and its related records"""
    order = await orders_collection.find_one({"_id": str_to_objectid(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Delete the order
    await orders_collection.delete_one({"_id": str_to_objectid(order_id)})
    
    # Delete related invoice
    await invoices_collection.delete_many({"order_id": order_id})
    
    # Delete related payment transactions
    await db.payment_transactions.delete_many({"order_id": order_id})
    
    logger.info(f"Order {order_id} deleted by admin {current_user['sub']}")
    
    return {"message": "Order deleted successfully"}

# ===== ADMIN INVOICES =====

@app.get("/api/admin/invoices")
async def get_all_invoices(search: str = "", status: str = "", current_user: dict = Depends(get_current_admin_user)):
    """Get all invoices with optional search and filter"""
    query = {}
    if status:
        query["status"] = status
    
    invoices = []
    async for inv in invoices_collection.find(query).sort("created_at", -1):
        inv["id"] = str(inv["_id"])
        del inv["_id"]
        
        # Get user info
        user = None
        if inv.get("user_id"):
            user = await users_collection.find_one({"_id": str_to_objectid(inv["user_id"])})
        inv["customer_name"] = user["name"] if user else "Unknown"
        inv["customer_email"] = user.get("email", "") if user else ""
        
        # Get order items for product/service info
        if inv.get("order_id"):
            order = await orders_collection.find_one({"_id": str_to_objectid(inv["order_id"])})
            if order:
                inv["items"] = order.get("items", [])
                inv["payment_method"] = order.get("payment_method", "")
        
        # Get associated service username
        if inv.get("order_id"):
            service = await services_collection.find_one({"order_id": inv["order_id"]})
            if service:
                inv["line_username"] = service.get("xtream_username", "")
        
        # Apply search filter
        if search:
            s = search.lower()
            searchable = f"{inv.get('invoice_number','')} {inv.get('customer_name','')} {inv.get('customer_email','')} {inv.get('line_username','')} {inv.get('order_id','')}".lower()
            if s not in searchable:
                continue
        
        invoices.append(inv)
    
    return invoices

@app.post("/api/admin/invoices")
async def create_manual_invoice(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Create a manual invoice"""
    user_id = data.get("user_id", "")
    amount = float(data.get("amount", 0))
    description = data.get("description", "")
    due_date_str = data.get("due_date", "")
    status = data.get("status", "pending")
    
    if not user_id or amount <= 0:
        raise HTTPException(status_code=400, detail="User and amount are required")
    
    user = await users_collection.find_one({"_id": str_to_objectid(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Use invoice settings for numbering
    settings_doc = await get_settings()
    inv_config = settings_doc.get("invoice", {})
    prefix = inv_config.get("invoice_prefix", "INV")
    next_num = inv_config.get("next_number", 1000)
    padding = inv_config.get("number_padding", 4)
    
    invoice_number = f"{prefix}-{str(next_num).zfill(padding)}"
    
    # Increment next_number
    await settings_collection.update_one({}, {"$set": {"invoice.next_number": next_num + 1}})
    
    due_date = datetime.utcnow() + timedelta(days=7)
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
        except ValueError:
            pass
    
    invoice_doc = {
        "user_id": user_id,
        "order_id": "",
        "invoice_number": invoice_number,
        "total": amount,
        "status": status,
        "description": description,
        "due_date": due_date,
        "paid_date": datetime.utcnow() if status == "paid" else None,
        "created_at": datetime.utcnow(),
        "created_by": current_user["sub"],
        "is_manual": True
    }
    
    result = await invoices_collection.insert_one(invoice_doc)
    invoice_doc["id"] = str(result.inserted_id)
    del invoice_doc["_id"]
    
    logger.info(f"Manual invoice {invoice_number} created by admin {current_user['sub']} for user {user_id}: ${amount}")
    
    # Send invoice email if requested
    if data.get("send_email"):
        try:
            email_service = await get_configured_email_service()
            if email_service and email_service.enabled:
                items_html = f'<p>Description: {description}</p><p>Amount: ${amount:.2f}</p>'
                if status == "pending":
                    items_html += f'<p>Due Date: {due_date.strftime("%B %d, %Y")}</p>'
                    items_html += f'<p>Status: Pending payment</p>'
                else:
                    items_html += f'<p>Status: Paid</p>'
                
                content = f"""<p>Hi {user["name"]},</p>
<p>Invoice <strong>{invoice_number}</strong> has been created for your account.</p>
{items_html}
<p>If you have any questions, please contact support.</p>"""
                text = f"Hi {user['name']},\n\nInvoice {invoice_number} for ${amount:.2f}.\nDescription: {description}\nDue: {due_date.strftime('%Y-%m-%d')}\nStatus: {status}"
                
                await email_service.send_email(
                    to_email=user["email"],
                    subject=f"Invoice {invoice_number} - ${amount:.2f}",
                    html_content=email_service._wrap_email(content, "", user["email"], "transactional"),
                    text_content=text,
                    email_type="transactional",
                    customer_id=user_id
                )
                logger.info(f"Invoice email sent to {user['email']}")
        except Exception as e:
            logger.warning(f"Failed to send invoice email: {e}")
    
    return {"message": f"Invoice {invoice_number} created", "invoice": invoice_doc}

@app.put("/api/admin/invoices/{invoice_id}")
async def update_invoice(invoice_id: str, data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update invoice status"""
    update_fields = {}
    if "status" in data:
        update_fields["status"] = data["status"]
        if data["status"] == "paid":
            update_fields["paid_date"] = datetime.utcnow()
    if "amount" in data:
        update_fields["total"] = float(data["amount"])
    if "due_date" in data:
        try:
            update_fields["due_date"] = datetime.strptime(data["due_date"], "%Y-%m-%d")
        except ValueError:
            pass
    if "description" in data:
        update_fields["description"] = data["description"]
    
    if update_fields:
        await invoices_collection.update_one(
            {"_id": str_to_objectid(invoice_id)},
            {"$set": update_fields}
        )
    
    return {"message": "Invoice updated"}

@app.delete("/api/admin/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete an invoice"""
    await invoices_collection.delete_one({"_id": str_to_objectid(invoice_id)})
    return {"message": "Invoice deleted"}

@app.get("/api/admin/invoices/{invoice_id}/pdf")
async def admin_download_invoice_pdf(invoice_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Generate and download invoice PDF"""
    from invoice_pdf import generate_invoice_pdf
    from fastapi.responses import Response
    
    invoice = await invoices_collection.find_one({"_id": str_to_objectid(invoice_id)})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    user = None
    if invoice.get("user_id"):
        user = await users_collection.find_one({"_id": str_to_objectid(invoice["user_id"])})
    
    items = []
    if invoice.get("order_id"):
        try:
            order = await orders_collection.find_one({"_id": str_to_objectid(invoice["order_id"])})
            if order:
                items = order.get("items", [])
        except Exception:
            pass
    
    settings = await get_settings()
    pdf_bytes = generate_invoice_pdf(invoice, user, items, settings)
    
    filename = f"{invoice.get('invoice_number', 'invoice')}.pdf"
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/invoices/{invoice_id}/pdf")
async def customer_download_invoice_pdf(invoice_id: str, current_user: dict = Depends(get_current_user)):
    """Customer download their own invoice PDF"""
    from invoice_pdf import generate_invoice_pdf
    from fastapi.responses import Response
    
    invoice = await invoices_collection.find_one({"_id": str_to_objectid(invoice_id)})
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.get("user_id") != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not your invoice")
    
    user = await users_collection.find_one({"_id": str_to_objectid(current_user["sub"])})
    
    items = []
    if invoice.get("order_id"):
        try:
            order = await orders_collection.find_one({"_id": str_to_objectid(invoice["order_id"])})
            if order:
                items = order.get("items", [])
        except Exception:
            pass
    
    settings = await get_settings()
    pdf_bytes = generate_invoice_pdf(invoice, user, items, settings)
    
    filename = f"{invoice.get('invoice_number', 'invoice')}.pdf"
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# CMTV local change 2026-09-24 (bug report 2.3): a paid order was always marked "provisioned", even when nothing
# happened on the panel (product deleted, panel not configured, panel API error): the provision_*_service functions
# log the error and return, and the caller couldn't tell. Now each item is checked by what actually changed
# (a non-failed service saved for this order, or the renewed line's expiry moved), the order records
# provisioning_status / provisioning_errors, and the admin is alerted.
_provision_log = contextvars.ContextVar("provision_log", default=None)

class _ProvisionErrorCollector(logging.Handler):
    """Collects the ERROR messages logged while an order is being provisioned, so the alert can say why"""
    def emit(self, record):
        log = _provision_log.get()
        if log is None or record.levelno < logging.ERROR:
            return
        try:
            msg = record.getMessage().strip()
        except Exception:
            return
        if msg and not msg.startswith("Traceback"):
            log.append(msg.splitlines()[0][:300])

logging.getLogger().addHandler(_ProvisionErrorCollector())

async def _provision_snapshot(order_id: str, item: dict):
    """What provisioning this item can change: working services saved for the order, and the renewed line's expiry"""
    created = await services_collection.count_documents({"order_id": order_id, "status": {"$ne": "failed"}})
    renewed = None
    renewal_id = str(item.get("renewal_service_id") or "")
    if ObjectId.is_valid(renewal_id):
        svc = await services_collection.find_one({"_id": ObjectId(renewal_id)}, {"expiry_date": 1, "updated_at": 1})
        renewed = ((svc or {}).get("expiry_date"), (svc or {}).get("updated_at"))
    return created, renewed

async def _alert_provisioning_failure(order_id: str, order: dict, user: dict, failures: list):
    """Tell the admin that a paid order was not (fully) provisioned. Always sent: not tied to a notification switch."""
    paid = float(order.get("total") or 0) + float(order.get("credits_used") or 0)
    text = (f"⚠️ PAID ORDER NOT PROVISIONED\n\n"
            f"Order {order_id} (${paid:.2f}, {order.get('payment_method') or 'payment'})\n"
            f"Customer: {user.get('name', '')} <{user.get('email', '')}>\n\n"
            + "\n".join(f"• {f}" for f in failures) +
            "\n\nThe customer has paid, but the line was NOT created or extended on the panel. "
            "Fix it on the panel, then let the customer know. The order shows 'Not provisioned' in Admin > Orders.")
    settings = await get_settings()
    tg = settings.get("notifications", {}).get("telegram", {})
    if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                                  json={"chat_id": tg["chat_id"], "text": text[:4000]}, timeout=10.0)
        except Exception as e:
            logger.warning(f"Provisioning alert: Telegram failed: {e}")
    em = settings.get("notifications", {}).get("email", {})
    if em.get("enabled") and em.get("recipient_email"):
        try:
            email_service = await get_configured_email_service()
            if email_service and email_service.enabled:
                await email_service.send_email(to_email=em["recipient_email"], subject="Paid order NOT provisioned",
                                               html_content=f"<pre>{html_escape(text)}</pre>", text_content=text,
                                               email_type="transactional")
        except Exception as e:
            logger.warning(f"Provisioning alert: email failed: {e}")

async def provision_order_services(order_id: str, order: dict, user: dict):
    """Provision services (XtreamUI or XuiOne) for paid order"""
    acquired = False
    failures = []   # CMTV: "<item>: <why>" for each item that wasn't provisioned
    units = 0
    errors = []
    log_token = _provision_log.set(errors)

    async def run_item(label: str, item: dict, call):
        """Run one provision_*_service call and check that it actually created or extended something"""
        nonlocal units
        units += 1
        mark = len(errors)
        before = await _provision_snapshot(order_id, item)
        try:
            await call
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}"[:300])
        after = await _provision_snapshot(order_id, item)
        if after == before:
            why = "; ".join(dict.fromkeys(errors[mark:])) or "the panel made no change (no line created or extended)"
            failures.append(f"{label}: {why}")

    try:
        # Atomic provisioning lock — prevents duplicate provisioning from concurrent calls
        lock_result = await orders_collection.update_one(
            {"_id": str_to_objectid(order_id), "provisioning": {"$ne": True}},
            {"$set": {"provisioning": True, "provisioning_started_at": datetime.utcnow()}}
        )
        if lock_result.modified_count == 0:
            logger.info(f"Order {order_id} already being provisioned, skipping")
            return
        acquired = True

        logger.info(f"Provisioning order {order_id} — lock acquired")
        
        settings = await get_settings()
        
        # === Referral completion check (covers ALL payment paths) ===
        if user.get("referred_by") and referral_service:
            try:
                # CMTV local change 2026-09-24: enforce the referral minimum purchase (was ignored, so $0 trials paid out).
                # Any paid order worth at least the minimum completes a still-pending referral; complete_referral only
                # acts on pending referrals, so the reward is paid once.
                ref_settings = await referral_service.get_referral_settings()
                minimum = float(ref_settings.get("minimum_purchase") or 0)
                order_value = float(order.get("total") or 0) + float(order.get("credits_used") or 0)
                if order_value > 0 and order_value >= minimum:
                    await referral_service.complete_referral(order["user_id"], order_id)
                    logger.info(f"Referral completed for user {order['user_id']}")
                else:
                    logger.info(f"Referral not completed for user {order['user_id']}: order value ${order_value:.2f} below minimum ${minimum:.2f}")
            except Exception as e:
                logger.error(f"Referral completion error for order {order_id}: {e}")
        
        # Get configured email service with all required params
        email_service = await get_configured_email_service()
        
        for item in order["items"]:
            # Get product details to determine which panel to use
            product = await products_collection.find_one({"_id": str_to_objectid(item["product_id"])})
            
            if not product:
                logger.error(f"Product {item['product_id']} not found")
                units += 1
                failures.append(f"{item.get('product_name', item['product_id'])}: the product no longer exists (deleted?), so nothing was provisioned")
                continue

            # Bundle product - provision each included product separately
            if product.get("is_bundle") and product.get("bundle_product_ids"):
                logger.info(f"Provisioning bundle: {product.get('name')} ({len(product['bundle_product_ids'])} products)")
                for bp_id in product["bundle_product_ids"]:
                    bp = await products_collection.find_one({"_id": str_to_objectid(bp_id)})
                    if not bp:
                        logger.error(f"Bundle sub-product {bp_id} not found, skipping")
                        units += 1
                        failures.append(f"{item.get('product_name', '')} (bundle part {bp_id}): the product no longer exists, so it was skipped")
                        continue
                    bp_item = {**item, "product_id": bp_id, "product_name": f"{item['product_name']} — {bp.get('name', '')}"}
                    bp_panel_type = safe_panel_type(bp.get("panel_type"))
                    logger.info(f"  Provisioning bundle item: {bp.get('name')} (Panel: {bp_panel_type})")
                    if bp_panel_type == "manual" and bp.get("cockpit_module"):
                        await run_item(bp_item["product_name"], bp_item, provision_cockpit_service(order_id, order, user, bp_item, bp, settings, email_service))
                    elif bp_panel_type == "manual":
                        svc = {"user_id": order["user_id"], "order_id": order_id, "product_id": bp_id, "product_name": bp_item["product_name"], "account_type": "manual", "term_months": item.get("term_months", 1), "status": "active", "panel_type": "manual", "setup_instructions": bp.get("setup_instructions", ""), "start_date": datetime.utcnow(), "created_at": datetime.utcnow()}
                        await services_collection.insert_one(svc)
                    elif bp_panel_type == "xuione":
                        await run_item(bp_item["product_name"], bp_item, provision_xuione_service(order_id, order, user, bp_item, bp, settings, email_service))
                    elif bp_panel_type == "onestream":
                        await run_item(bp_item["product_name"], bp_item, provision_onestream_service(order_id, order, user, bp_item, bp, settings, email_service))
                    elif bp_panel_type == "nxtdash":
                        await run_item(bp_item["product_name"], bp_item, provision_nxtdash_service(order_id, order, user, bp_item, bp, settings, email_service))
                    elif bp_panel_type == "ghostsurf":
                        await run_item(bp_item["product_name"], bp_item, provision_ghostsurf_service(order_id, order, user, bp_item, bp, settings, email_service))
                    elif bp_panel_type == "aether":
                        await run_item(bp_item["product_name"], bp_item, provision_aether_service(order_id, order, user, bp_item, bp, settings, email_service))
                    else:
                        await run_item(bp_item["product_name"], bp_item, provision_xtream_service(order_id, order, user, bp_item, bp, settings, email_service))
                continue
            
            # Get panel type and index from product
            panel_type = safe_panel_type(product.get("panel_type"))
            panel_index = safe_panel_index(product.get("panel_index"))
            
            logger.info(f"Provisioning service for product: {product.get('name')} (Panel: {panel_type}, Index: {panel_index})")
            
            # Route to correct panel type
            if panel_type == "manual" and product.get("cockpit_module"):
                # CMTV local change 2026-09-24: manual product linked to Cockpit -> create/renew the account automatically
                await run_item(item["product_name"], item, provision_cockpit_service(order_id, order, user, item, product, settings, email_service))
            elif panel_type == "manual":
                # Manual product - create service record without panel provisioning
                service_dict = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "account_type": "manual",
                    "term_months": item.get("term_months", 1),
                    "status": "active",
                    "panel_type": "manual",
                    "setup_instructions": product.get("setup_instructions", ""),
                    "start_date": datetime.utcnow(),
                    "created_at": datetime.utcnow()
                }
                await services_collection.insert_one(service_dict)
                logger.info(f"Manual product provisioned: {product.get('name')}")
                
                if email_service:
                    try:
                        await email_service.send_service_activated(
                            customer_email=user["email"],
                            customer_name=user["name"],
                            service_name=item["product_name"],
                            username="N/A",
                            password="N/A",
                            streaming_url="",
                            max_connections=0,
                            expiry_date="N/A",
                            customer_id=order["user_id"]
                        )
                    except Exception:
                        pass
            elif panel_type == "xuione":
                await run_item(item["product_name"], item, provision_xuione_service(order_id, order, user, item, product, settings, email_service))
            elif panel_type == "onestream":
                await run_item(item["product_name"], item, provision_onestream_service(order_id, order, user, item, product, settings, email_service))
            elif panel_type == "nxtdash":
                await run_item(item["product_name"], item, provision_nxtdash_service(order_id, order, user, item, product, settings, email_service))
            elif panel_type == "ghostsurf":
                await run_item(item["product_name"], item, provision_ghostsurf_service(order_id, order, user, item, product, settings, email_service))
            elif panel_type == "aether":
                await run_item(item["product_name"], item, provision_aether_service(order_id, order, user, item, product, settings, email_service))
            else:
                await run_item(item["product_name"], item, provision_xtream_service(order_id, order, user, item, product, settings, email_service))

    except Exception as e:
        logger.error(f"Provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        failures.append(f"provisioning stopped with an error: {e}"[:300])
    finally:
        _provision_log.reset(log_token)
        # Mark provisioning complete (release lock but keep flag for idempotency)
        update = {"provisioned": True, "provisioned_at": datetime.utcnow()}
        if acquired:
            if not failures:
                update["provisioning_status"] = "ok"
            else:
                update["provisioning_status"] = "failed" if len(failures) >= max(units, 1) else "partial"
            update["provisioning_errors"] = failures
        await orders_collection.update_one(
            {"_id": str_to_objectid(order_id)},
            {"$set": update}
        )
        if acquired and failures:
            logger.error(f"PROVISIONING FAILED for order {order_id}: {failures}")
            try:
                await _alert_provisioning_failure(order_id, order, user, failures)
            except Exception as e:
                logger.error(f"Provisioning alert failed for order {order_id}: {e}")

async def provision_cockpit_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """CMTV local change 2026-09-24: create or renew the customer's account in the Cockpit panel (Stremio / CMTVpn).
    Like the other provision_*_service functions it logs an error and returns on failure; provision_order_services
    then flags the order "Not provisioned" and alerts the admin."""
    module = product.get("cockpit_module")
    label = cockpit_service.MODULES.get(module, str(module))
    if product.get("is_trial"):
        amount, unit = int(product.get("trial_duration") or 1), (product.get("trial_duration_unit") or "days")
        months, days = (amount, 0) if unit.startswith("month") else (0, max(1, amount if unit.startswith("day") else 1))
    else:
        months, days = max(1, int(item.get("term_months") or 1)), 0

    renewal_service_id = item.get("renewal_service_id")
    if renewal_service_id and item.get("action_type", "create_new") in ("renew", "extend"):
        existing = await services_collection.find_one({"_id": str_to_objectid(renewal_service_id), "user_id": order["user_id"]})
        if not existing:
            logger.error(f"Cockpit {label} renewal: service {renewal_service_id} not found")
            return
        if existing.get("cockpit_module") != module or not existing.get("username"):
            logger.error(f"Cockpit {label} renewal: this service isn't linked to a Cockpit {label} account "
                         f"(it was set up by hand), so extend it in Cockpit by hand")
            return
        result = await cockpit_service.extend_account(module, existing["username"], months=months, days=days)
        if not result.get("success"):
            logger.error(f"Cockpit {label} renew failed for {existing['username']}: {result.get('error')}")
            return
        new_expiry = cockpit_service.expiry_datetime(result["expires"])
        await services_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {"expiry_date": new_expiry, "status": "active", "updated_at": datetime.utcnow()}}
        )
        logger.info(f"Cockpit {label} account renewed: {existing['username']} -> {result['expires']}")
        if email_service:
            try:
                await email_service.send_service_renewed(
                    customer_email=user["email"], customer_name=user.get("name", "Customer"),
                    service_name=existing.get("product_name", product.get("name", label)),
                    username=existing["username"], new_expiry_date=result["expires"], customer_id=order["user_id"]
                )
            except Exception as email_err:
                logger.warning(f"Cockpit {label} renewal email failed: {email_err}")
        return

    result = await cockpit_service.create_account(module, months=months, days=days)
    if not result.get("success"):
        logger.error(f"Cockpit {label} account creation failed: {result.get('error')}")
        return
    expiry = cockpit_service.expiry_datetime(result["expires"])
    service_doc = {
        "user_id": order["user_id"],
        "order_id": order_id,
        "product_id": str(product.get("_id", item.get("product_id", ""))),
        "product_name": product.get("name", label),
        "account_type": "subscriber",       # shows login, expiry and the Renew button on My Services
        "panel_type": "manual",
        "panel_name": f"Cockpit ({label})",
        "cockpit_module": module,
        "cockpit_account_id": result.get("id"),
        "username": result["username"],
        "password": result["password"],
        "xtream_username": result["username"],
        "xtream_password": result["password"],
        "term_months": months,
        "max_connections": product.get("max_connections") or 0,
        "is_trial": product.get("is_trial", False),
        "setup_instructions": product.get("setup_instructions", ""),
        "start_date": datetime.utcnow(),
        "expiry_date": expiry,
        "status": "active",
        "created_at": datetime.utcnow(),
    }
    await services_collection.insert_one(service_doc)
    logger.info(f"Cockpit {label} account created: {result['username']} (id {result.get('id')}, until {result['expires']})")
    if email_service:
        try:
            await email_service.send_cockpit_account(
                customer_email=user["email"], customer_name=user.get("name", ""),
                service_name=product.get("name", label), username=result["username"], password=result["password"],
                expiry_date=result["expires"], setup_instructions=product.get("setup_instructions", ""),
                customer_id=order["user_id"]
            )
        except Exception as email_err:
            logger.warning(f"Cockpit {label} login email failed: {email_err}")

async def provision_xtream_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision XtreamUI service"""
    try:
        xtream_settings = settings.get("xtream", {})
        panels = xtream_settings.get("panels", [])
        
        if not panels or len(panels) == 0:
            logger.warning("XtreamUI not configured, skipping provisioning")
            return
        
        # Get panel index from product (safe coercion)
        panel_index = safe_panel_index(product.get("panel_index"))
        
        # Validate panel index
        if panel_index >= len(panels):
            logger.error(f"Product references panel {panel_index} but only {len(panels)} panels exist. Using first panel.")
            panel_index = 0
        
        panel = panels[panel_index]
        
        # Get panel name for display
        panel_name = panel.get("name", f"Server {panel_index + 1}")
        
        # ===== API-KEY PANEL: Use JSON POST API =====
        if panel.get("api_key"):
            logger.info(f"Using API-key provisioning for panel: {panel_name}")
            
            username = generate_username()
            password = generate_password()
            
            if item["account_type"] == "reseller" and order.get("reseller_credentials"):
                username = order["reseller_credentials"].get("username", username)
                password = order["reseller_credentials"].get("password", password)
            
            package_id = product.get("xtream_package_id")
            bouquets = product.get("bouquets", [])
            term_months = item.get("term_months", 1)
            
            # Check for renewal
            action_type = item.get("action_type", "create_new")
            renewal_service_id = item.get("renewal_service_id")
            
            if renewal_service_id and action_type in ("renew", "extend"):
                existing = await services_collection.find_one({"_id": str_to_objectid(renewal_service_id)})
                if existing and existing.get("xtream_user_id"):
                    # Extend existing line
                    try:
                        result = await _xtream_api_call(panel, "extend_line", {
                            "user_id": existing["xtream_user_id"],
                            "package_id": package_id
                        })
                        logger.info(f"API extend_line result: {result}")
                        
                        # Update expiry
                        pkg_duration = product.get("duration") or term_months
                        pkg_unit = product.get("duration_unit", "months")
                        if pkg_unit in ("months", "month"):
                            new_expiry = datetime.utcnow() + timedelta(days=int(pkg_duration) * 30)
                        elif pkg_unit in ("years", "year"):
                            new_expiry = datetime.utcnow() + timedelta(days=int(pkg_duration) * 365)
                        else:
                            new_expiry = datetime.utcnow() + timedelta(days=int(pkg_duration))
                        
                        await services_collection.update_one(
                            {"_id": str_to_objectid(renewal_service_id)},
                            {"$set": {"expiry_date": new_expiry, "status": "active"}}
                        )
                        logger.info(f"Extended line {existing['xtream_user_id']} until {new_expiry}")
                        return
                    except Exception as e:
                        logger.error(f"API extend_line failed: {e}, creating new line")
            
            # Create new line
            try:
                create_data = {
                    "username": username,
                    "password": password,
                    "package_id": package_id,
                }
                if bouquets:
                    create_data["bouquets"] = [int(b) for b in bouquets if b]
                
                result = await _xtream_api_call(panel, "create_line", create_data)
                logger.info(f"API create_line result: {result}")
                
                line_id = result.get("user_id") or result.get("line_id") or result.get("id")
                created_user = result.get("username", username)
                created_pass = result.get("password", password)
                
                pkg_duration = product.get("duration") or term_months
                pkg_unit = product.get("duration_unit", "months")
                if pkg_unit in ("months", "month"):
                    expiry_date = datetime.utcnow() + timedelta(days=int(pkg_duration) * 30)
                elif pkg_unit in ("years", "year"):
                    expiry_date = datetime.utcnow() + timedelta(days=int(pkg_duration) * 365)
                else:
                    expiry_date = datetime.utcnow() + timedelta(days=int(pkg_duration))
                
                service_dict = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "account_type": item.get("account_type", "subscriber"),
                    "term_months": term_months,
                    "xtream_username": created_user,
                    "xtream_password": created_pass,
                    "xtream_user_id": line_id,
                    "streaming_url": panel.get("streaming_url", ""),
                    "status": "active",
                    "panel_type": "xtream",
                    "panel_index": panel_index,
                    "panel_name": panel_name,
                    "expiry_date": expiry_date,
                    "start_date": datetime.utcnow(),
                    "created_at": datetime.utcnow()
                }
                await services_collection.insert_one(service_dict)
                logger.info(f"API-key provisioned: user={created_user}, line_id={line_id}")
                
                if email_service:
                    try:
                        await email_service.send_service_activated(
                            customer_email=user["email"],
                            customer_name=user["name"],
                            service_name=item["product_name"],
                            username=created_user,
                            password=created_pass,
                            streaming_url=panel.get("streaming_url", ""),
                            max_connections=product.get("max_connections", 1),
                            expiry_date=expiry_date.strftime("%Y-%m-%d"),
                            customer_id=order["user_id"]
                        )
                    except Exception as e:
                        logger.error(f"Email send error: {e}")
                return
            except Exception as e:
                logger.error(f"API create_line failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return
        
        # ===== STANDARD PANEL: Session-based provisioning =====
        
        # Initialize XtreamUI service for this specific panel
        xtream_service = XtreamUIService(
            panel_url=panel["panel_url"],
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            ssl_verify=panel.get("ssl_verify", False),
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", ""),
            api_key=panel.get("api_key", "")
        )
        
        # Generate or use custom credentials
        if item["account_type"] == "reseller" and order.get("reseller_credentials"):
            username = order["reseller_credentials"].get("username", generate_username())
            password = order["reseller_credentials"].get("password", generate_password())
            logger.info(f"Using custom reseller credentials: {username}")
        else:
            username = generate_username()
            password = generate_password()
        
        # For resellers, check if adding credits to existing account
        existing_reseller = None
        if item["account_type"] == "reseller":
            reseller_creds = order.get("reseller_credentials", {})
            if reseller_creds and reseller_creds.get("add_credits_to_existing"):
                # Check services collection
                existing_reseller = await services_collection.find_one({
                    "xtream_username": reseller_creds.get("username", ""),
                    "account_type": "reseller",
                    "status": "active"
                })
                # Also check imported users (panel-synced resellers)
                if not existing_reseller:
                    imported = await imported_users_collection.find_one({
                        "username": reseller_creds.get("username", ""),
                        "account_type": "reseller"
                    })
                    if imported:
                        existing_reseller = {
                            "xtream_username": imported["username"],
                            "xtream_password": imported.get("password", ""),
                            "panel_index": imported.get("panel_index", 0),
                            "_from_imported": True
                        }
                if existing_reseller:
                    logger.info(f"Found existing reseller to add credits: {existing_reseller['xtream_username']}")
            
            if not existing_reseller:
                existing_reseller = await services_collection.find_one({
                    "user_id": order["user_id"],
                    "account_type": "reseller",
                    "status": "active",
                    "panel_index": panel_index
                })
                if existing_reseller:
                    logger.info(f"Found existing reseller by user_id: {existing_reseller['xtream_username']}")
        
        # Calculate expiry date
        term_months = item["term_months"]
        
        # For trial products, use actual trial duration instead of term_months
        if product.get("is_trial") and product.get("trial_duration"):
            trial_duration = int(product.get("trial_duration", 1))
            trial_unit = (product.get("trial_duration_unit") or "days").lower()
            if trial_unit in ("hours", "hour"):
                expiry_date = datetime.utcnow() + timedelta(hours=trial_duration)
            elif trial_unit in ("days", "day"):
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration)
            elif trial_unit in ("months", "month"):
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration * 30)
            else:
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration)
            logger.info(f"Trial product: duration={trial_duration} {trial_unit}, expiry={expiry_date}")
        else:
            # Use product's actual duration from panel package, fallback to term_months
            pkg_duration = product.get("duration") or product.get("official_duration")
            pkg_duration_unit = product.get("duration_unit") or product.get("official_duration_in") or "months"
            
            # If duration is a string like "12 months", parse it
            if isinstance(pkg_duration, str):
                parts = pkg_duration.strip().split()
                try:
                    pkg_duration = int(parts[0])
                    if len(parts) > 1:
                        pkg_duration_unit = parts[1]
                except (ValueError, IndexError):
                    pkg_duration = None
            
            # If still no duration, infer from product name
            if not pkg_duration:
                pname = (product.get("name") or "").upper()
                if "ANNUAL" in pname or "YEARLY" in pname or "12 MONTH" in pname or "1 YEAR" in pname:
                    pkg_duration = 12
                    pkg_duration_unit = "months"
                    logger.info(f"Inferred 12-month duration from product name: {product.get('name')}")
                elif "6 MONTH" in pname:
                    pkg_duration = 6
                    pkg_duration_unit = "months"
                elif "3 MONTH" in pname:
                    pkg_duration = 3
                    pkg_duration_unit = "months"
                elif "24 HOUR" in pname or "1 DAY" in pname:
                    pkg_duration = 1
                    pkg_duration_unit = "days"
            
            if pkg_duration:
                pkg_duration = int(pkg_duration)
                if pkg_duration_unit.lower() in ("months", "month"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
                elif pkg_duration_unit.lower() in ("years", "year"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 365)
                elif pkg_duration_unit.lower() in ("days", "day"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration)
                else:
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
                logger.info(f"Using product duration: {pkg_duration} {pkg_duration_unit}")
            else:
                expiry_date = datetime.utcnow() + timedelta(days=term_months * 30)
                logger.info(f"Using term_months fallback: {term_months} months")
        
        expiry_timestamp = int(expiry_date.timestamp())
        
        # Check if item has action_type and renewal_service_id from cart
        action_type = item.get("action_type", "create_new")  # Default to create_new
        renewal_service_id = item.get("renewal_service_id")
        
        # For subscribers, check if they're renewing
        existing_subscriber = None
        if item["account_type"] == "subscriber":
            if renewal_service_id:
                # Customer explicitly chose to extend a specific service
                existing_subscriber = await services_collection.find_one({
                    "_id": str_to_objectid(renewal_service_id),
                    "user_id": order["user_id"]
                })
                if existing_subscriber:
                    logger.info(f"Customer chose to extend service: {existing_subscriber['xtream_username']}")
            elif action_type == "extend":
                    # Legacy: find any active service with same product (only if explicitly set to extend)
                    existing_subscriber = await services_collection.find_one({
                        "user_id": order["user_id"],
                        "product_id": item["product_id"],
                        "status": "active"
                    })
                    if existing_subscriber:
                        logger.info(f"Legacy extend mode: extending {existing_subscriber['xtream_username']}")
                # If action_type is "create_new" or not set, existing_subscriber remains None
            
        # Create service record (runs for both subscribers and resellers)
        service_dict = {
            "user_id": order["user_id"],
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "account_type": item["account_type"],
            "term_months": term_months,
            "xtream_username": (existing_reseller or {}).get("xtream_username") or (existing_subscriber or {}).get("xtream_username") or username,
            "xtream_password": (existing_reseller or {}).get("xtream_password") or (existing_subscriber or {}).get("xtream_password") or password,
            "status": "pending",
            "panel_type": product.get("panel_type", "xtream"),
            "panel_index": panel_index,
            "panel_name": panel_name,
            "created_at": datetime.utcnow()
        }
        
        logger.info(f"Provisioning: account_type={item['account_type']}, existing_reseller={existing_reseller is not None}, existing_subscriber={existing_subscriber is not None}")
        
        if item["account_type"] == "subscriber":
                # Check if this is a renewal (existing subscriber)
                if existing_subscriber:
                    # Use the SERVICE's panel_index, not the product's — the user lives on this panel
                    actual_panel_index = existing_subscriber.get("panel_index", panel_index)
                    if actual_panel_index != panel_index:
                        logger.info(f"Service panel_index ({actual_panel_index}) differs from product panel_index ({panel_index}), using service's panel")
                        panel_index = actual_panel_index
                        if panel_index < len(panels):
                            panel = panels[panel_index]
                            panel_name = panel.get("name", f"Panel {panel_index + 1}")
                            xtream_service = XtreamUIService(
                                panel_url=panel["panel_url"],
                                admin_username=panel["admin_username"],
                                admin_password=panel["admin_password"],
                                ssl_verify=panel.get("ssl_verify", False),
                                http_basic_user=panel.get("http_basic_user", ""),
                                http_basic_pass=panel.get("http_basic_pass", ""),
                                proxy_url=panel.get("proxy_url", "")
                            )
                    
                    # Renewal - extend existing service in XtreamUI
                    logger.info(f"Renewal: Extending XtreamUI line for {existing_subscriber['xtream_username']} on panel {panel_name} (index {panel_index})")
                    
                    # Get package ID from product
                    package_id = product.get("xtream_package_id", 52)
                    
                    # Extend in XtreamUI with product bouquets
                    extend_result = xtream_service.extend_subscriber(
                        username=existing_subscriber["xtream_username"],
                        password=existing_subscriber["xtream_password"],
                        package_id=package_id,
                        bouquets=product["bouquets"],
                        max_connections=product["max_connections"],
                        reseller_notes=f"Renewal: Order {order_id}"
                    )
                    
                    if extend_result.get("success"):
                        logger.info(f"✓ XtreamUI line extended")
                    else:
                        logger.error(f"XtreamUI extend FAILED for {existing_subscriber['xtream_username']}: {extend_result.get('error')}")
                        # DO NOT update billing record or send email if panel extend failed
                        service_dict["status"] = "failed"
                        service_dict["error"] = f"Panel extend failed: {extend_result.get('error')}"
                        await services_collection.insert_one(service_dict)
                        return
                    
                    # Get actual expiry from the panel instead of calculating
                    new_expiry = None
                    if extend_result.get("success") and extend_result.get("new_expiry"):
                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                            try:
                                new_expiry = datetime.strptime(str(extend_result["new_expiry"]).strip(), fmt)
                                break
                            except (ValueError, TypeError):
                                continue
                    
                    # Fallback: fetch expiry from panel via table_search
                    if not new_expiry:
                        try:
                            import time, re as _re
                            session_client = xtream_service._get_session_client()
                            search_params = {
                                'draw': '1', 'start': '0', 'length': '10',
                                'search[value]': existing_subscriber["xtream_username"],
                                'search[regex]': 'false', 'id': 'users',
                                '_': str(int(time.time() * 1000))
                            }
                            for i in range(12):
                                search_params[f'columns[{i}][data]'] = str(i)
                                search_params[f'columns[{i}][searchable]'] = 'true'
                                search_params[f'columns[{i}][orderable]'] = 'true'
                            search_url = f"{session_client.panel_url}/table_search.php"
                            resp = session_client.session.get(search_url, params=search_params, auth=session_client.http_auth, timeout=15)
                            if resp.status_code == 200 and len(resp.text.strip()) == 0:
                                resp = session_client.session.post(search_url, data=search_params, auth=session_client.http_auth, timeout=15)
                            if resp.status_code == 200 and resp.text.strip():
                                search_data = resp.json()
                                users_data = search_data.get('data', [])
                                if users_data and len(users_data[0]) > 7:
                                    exp_raw = _re.sub(r'<[^>]+>', ' ', str(users_data[0][7])).strip()
                                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                        try:
                                            new_expiry = datetime.strptime(exp_raw.strip(), fmt)
                                            logger.info(f"Fetched actual panel expiry via search: {new_expiry}")
                                            break
                                        except ValueError:
                                            continue
                        except Exception as e:
                            logger.warning(f"Could not fetch panel expiry via search: {e}")
                    
                    # Final fallback: calculate
                    if not new_expiry:
                        if product.get("is_trial") and product.get("trial_duration"):
                            trial_dur = int(product.get("trial_duration", 1))
                            trial_u = (product.get("trial_duration_unit") or "days").lower()
                            if trial_u in ("hours", "hour"):
                                extend_td = timedelta(hours=trial_dur)
                            elif trial_u in ("days", "day"):
                                extend_td = timedelta(days=trial_dur)
                            else:
                                extend_td = timedelta(days=trial_dur * 30)
                        else:
                            # Use product duration, not term_months
                            pkg_dur = product.get("duration") or product.get("official_duration")
                            pkg_dur_unit = (product.get("duration_unit") or product.get("official_duration_in") or "months").lower()
                            if pkg_dur:
                                pkg_dur = int(pkg_dur)
                                if pkg_dur_unit in ("months", "month"):
                                    extend_td = timedelta(days=pkg_dur * 30)
                                elif pkg_dur_unit in ("years", "year"):
                                    extend_td = timedelta(days=pkg_dur * 365)
                                elif pkg_dur_unit in ("days", "day"):
                                    extend_td = timedelta(days=pkg_dur)
                                else:
                                    extend_td = timedelta(days=pkg_dur * 30)
                            else:
                                extend_td = timedelta(days=term_months * 30)
                        current_expiry = existing_subscriber.get("expiry_date", datetime.utcnow())
                        if current_expiry < datetime.utcnow():
                            new_expiry = datetime.utcnow() + extend_td
                        else:
                            new_expiry = current_expiry + extend_td
                    
                    # Update existing service expiry, connections, and product info
                    update_fields = {
                        "expiry_date": new_expiry,
                        "status": "active",
                        "product_id": item["product_id"],
                        "product_name": item["product_name"],
                    }
                    # Update max_connections from the new product
                    new_max_conn = product.get("max_connections")
                    if new_max_conn:
                        update_fields["max_connections"] = int(new_max_conn)
                    
                    await services_collection.update_one(
                        {"_id": existing_subscriber["_id"]},
                        {"$set": update_fields}
                    )
                    
                    logger.info(f"Existing service updated: expiry={new_expiry}, connections={new_max_conn}, product={item['product_name']}")
                    
                    # Send renewal email
                    if email_service:
                        await email_service.send_service_renewed(
                            customer_email=user["email"],
                            customer_name=user["name"],
                            service_name=item["product_name"],
                            username=existing_subscriber["xtream_username"],
                            new_expiry_date=new_expiry.strftime("%Y-%m-%d"),
                            customer_id=order["user_id"]
                        )
                    
                    logger.info(f"Service renewed and extended to {new_expiry}")
                    # Renewal complete, return (service updated)
                    return
                    
                else:
                    # New subscription - create XtreamUI account
                    # Get XtreamUI package ID from product
                    package_id = product.get("xtream_package_id", 52)
                    
                    # Create subscriber via form POST
                    result = xtream_service.create_subscriber_via_form(
                        username=username,
                        password=password,
                        package_id=package_id,
                        bouquets=product["bouquets"],
                        customer_name=user["name"],
                        is_trial=product.get("is_trial", False),
                        exp_date=expiry_timestamp if product.get("is_trial") else None
                    )
                    
                    if result["success"]:
                        xtream_user_id = result.get("user_id")
                        
                        # Wait for panel to process, then fetch ACTUAL expiry from panel
                        logger.info(f"Waiting for panel to process new user {username}...")
                        await asyncio.sleep(3)
                        
                        actual_expiry = expiry_date
                        try:
                            # Search for the user to get real expiry
                            import time, re as _re
                            search_params = {
                                'draw': '1', 'start': '0', 'length': '10',
                                'search[value]': username, 'search[regex]': 'false',
                                'id': 'users', '_': str(int(time.time() * 1000))
                            }
                            for i in range(12):
                                search_params[f'columns[{i}][data]'] = str(i)
                                search_params[f'columns[{i}][searchable]'] = 'true'
                                search_params[f'columns[{i}][orderable]'] = 'true'
                            search_params['order[0][column]'] = '0'
                            search_params['order[0][dir]'] = 'desc'
                            
                            session_client = xtream_service._get_session_client()
                            search_url = f"{session_client.panel_url}/table_search.php"
                            resp = session_client.session.get(search_url, params=search_params, auth=session_client.http_auth, timeout=15)
                            if resp.status_code == 200 and len(resp.text.strip()) == 0:
                                resp = session_client.session.post(search_url, data=search_params, auth=session_client.http_auth, timeout=15)
                            
                            if resp.status_code == 200 and resp.text.strip():
                                search_data = resp.json()
                                users_data = search_data.get('data', [])
                                if users_data:
                                    # Expiry is typically column 7 (format: "2026-03-06<br>18:08:16")
                                    exp_raw = str(users_data[0][7]) if len(users_data[0]) > 7 else ""
                                    exp_clean = _re.sub(r'<[^>]+>', ' ', exp_raw).strip()
                                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                        try:
                                            actual_expiry = datetime.strptime(exp_clean.strip(), fmt)
                                            logger.info(f"Actual panel expiry for {username}: {actual_expiry}")
                                            break
                                        except ValueError:
                                            continue
                        except Exception as e:
                            logger.warning(f"Could not fetch actual expiry from panel: {e}")
                        
                        service_dict.update({
                            "bouquets": product["bouquets"],
                            "max_connections": product["max_connections"],
                            "status": "active",
                            "start_date": datetime.utcnow(),
                            "expiry_date": actual_expiry,
                            "dedicatedip": xtream_user_id  # Store XtreamUI user ID for suspend/terminate
                        })
                    
                    # Insert service
                    await services_collection.insert_one(service_dict)
                    
                    # Send activation email
                    if email_service:
                        await email_service.send_service_activated(
                            customer_email=user["email"],
                            customer_name=user["name"],
                            service_name=item["product_name"],
                            username=username,
                            password=password,
                            streaming_url=panel.get("streaming_url", panel["panel_url"]),
                            max_connections=product["max_connections"],
                            expiry_date=actual_expiry.strftime("%Y-%m-%d"),
                            customer_id=order["user_id"]
                        )
                        
                        # Send "Service Activated" Telegram notification  
                        await send_telegram_notification(
                            "service_activated",
                            f"✅ *Service Activated*\n\nCustomer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XtreamUI)\nUsername: {username}\nExpiry: {actual_expiry.strftime('%Y-%m-%d')}"
                        )
                        await send_email_notification(
                            "service_activated",
                            "Service Activated",
                            f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XtreamUI)\nUsername: {username}\nExpiry: {actual_expiry.strftime('%Y-%m-%d')}"
                        )
                        await send_sms_notification("service_activated", f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XtreamUI)\nUsername: {username}\nExpiry: {actual_expiry.strftime('%Y-%m-%d')}")
                        
                        logger.info(f"Subscriber provisioned: {username}")
                    else:
                        logger.error(f"Failed to provision subscriber: {result.get('error')}")
                        service_dict["status"] = "failed"
                        await services_collection.insert_one(service_dict)
                    
        else:  # reseller
            logger.info(f"Reseller provisioning: existing_reseller={existing_reseller is not None}")
            if existing_reseller:
                # User already has a reseller panel - add credits
                logger.info(f"Adding {product['reseller_credits']} credits to existing reseller {existing_reseller['xtream_username']}")
                if xtream_service:
                    credits_result = xtream_service.add_credits(
                        username=existing_reseller["xtream_username"],
                        email=user["email"],
                        credits=product["reseller_credits"]
                    )
                    if credits_result.get("success"):
                        logger.info(f"Credits added to existing reseller in XtreamUI")
                    else:
                        logger.error(f"Failed to add credits: {credits_result.get('error')}")
                else:
                    logger.warning("XtreamUI service not available")
                
                service_dict.update({
                    "reseller_credits": product["reseller_credits"],
                    "reseller_max_lines": 0,
                    "panel_url": product.get("custom_panel_url", ""),
                    "status": "active",
                    "start_date": datetime.utcnow(),
                    "expiry_date": expiry_date,
                    "is_credit_addon": True
                })
                await services_collection.insert_one(service_dict)
                
                if email_service:
                    await email_service.send_credits_added(
                        customer_email=user["email"],
                        customer_name=user["name"],
                        username=existing_reseller["xtream_username"],
                        credits=product["reseller_credits"],
                        customer_id=order["user_id"]
                    )
                logger.info(f"Credits added to existing reseller panel")
            else:
                # Create new reseller panel (create with 0 credits, then add separately)
                result = xtream_service.create_reseller(
                    username=username,
                    password=password,
                    credits=0,
                    email=user["email"],
                    member_group_id=2
                )
                if result["success"]:
                    logger.info("Waiting 10 seconds for account creation...")
                    await asyncio.sleep(10)
                    if product["reseller_credits"] > 0:
                        logger.info(f"Adding {product['reseller_credits']} credits to new reseller {username}")
                        credits_result = xtream_service.add_credits(username=username, email=user["email"], credits=product["reseller_credits"])
                        if credits_result.get("success"):
                            logger.info(f"Credits added successfully")
                        else:
                            logger.warning(f"Failed to add credits: {credits_result.get('error')}")
                    
                    service_dict.update({
                        "reseller_credits": product["reseller_credits"],
                        "reseller_max_lines": product.get("reseller_max_lines", 0),
                        "panel_url": product.get("custom_panel_url", ""),
                        "status": "active",
                        "start_date": datetime.utcnow(),
                        "expiry_date": expiry_date
                    })
                    await services_collection.insert_one(service_dict)
                    
                    if email_service:
                        panel_url_for_email = product.get("custom_panel_url", "")
                        if panel_url_for_email:
                            await email_service.send_reseller_activated(
                                customer_email=user["email"], customer_name=user["name"],
                                service_name=item["product_name"], username=username, password=password,
                                panel_url=panel_url_for_email, credits=product["reseller_credits"],
                                expiry_date=expiry_date.strftime("%Y-%m-%d"), customer_id=order["user_id"]
                            )
                    logger.info(f"Reseller provisioned: {username}")
                else:
                    logger.error(f"Failed to provision reseller: {result.get('error')}")
                    service_dict["status"] = "failed"
                    await services_collection.insert_one(service_dict)
        
    except Exception as e:
        logger.error(f"Provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

async def extend_xuione_line(xuione_service, existing_service: dict, item: dict, product: dict, order: dict, order_id: str, user: dict, email_service):
    """Extend/renew an existing XuiOne line using edit_line API"""
    try:
        logger.info(f"Extending XuiOne line: {existing_service.get('xtream_username')}")
        
        # Login first to get session cookie
        if not xuione_service.logged_in:
            if not xuione_service.login():
                logger.error("XuiOne: Login failed for extension")
                return
        
        # Get the line ID from the existing service
        line_id = existing_service.get("dedicatedip") or existing_service.get("xuione_line_id") or existing_service.get("xtream_user_id")
        
        # If no line_id stored, try to find it by looking up the username on the panel
        if not line_id:
            username = existing_service.get("xtream_username", "")
            logger.warning(f"No line ID stored, looking up by username: {username}")
            try:
                api_url = xuione_service.get_api_url()
                lines_resp = xuione_service.session.get(
                    api_url,
                    params={'api_key': xuione_service.api_key, 'action': 'get_lines'},
                    timeout=15
                )
                if lines_resp.status_code == 200:
                    lines_data = lines_resp.json().get('data', [])
                    for line in lines_data:
                        if line.get('username') == username:
                            line_id = line.get('id')
                            # Store it for future renewals
                            await services_collection.update_one(
                                {"_id": existing_service["_id"]},
                                {"$set": {"xuione_line_id": line_id, "dedicatedip": line_id}}
                            )
                            logger.info(f"Found and stored line_id: {line_id}")
                            break
            except Exception as e:
                logger.error(f"Failed to lookup line by username: {e}")
        
        if not line_id:
            logger.error(f"No line ID found for service {existing_service.get('_id')} - cannot extend")
            return
        
        # Calculate extend days from product duration, fallback to term_months
        pkg_duration = product.get("duration") or product.get("official_duration")
        pkg_dur_unit = (product.get("duration_unit") or product.get("official_duration_in") or "months").lower()
        
        # Infer from name if missing
        if not pkg_duration:
            pname = (product.get("name") or "").upper()
            if "ANNUAL" in pname or "12 MONTH" in pname or "1 YEAR" in pname:
                pkg_duration = 12
                pkg_dur_unit = "months"
            elif "6 MONTH" in pname:
                pkg_duration = 6
                pkg_dur_unit = "months"
            elif "3 MONTH" in pname:
                pkg_duration = 3
                pkg_dur_unit = "months"
        
        if pkg_duration:
            pkg_duration = int(pkg_duration)
            if pkg_dur_unit in ("months", "month"):
                extend_days = pkg_duration * 30
            elif pkg_dur_unit in ("years", "year"):
                extend_days = pkg_duration * 365
            elif pkg_dur_unit in ("days", "day"):
                extend_days = pkg_duration
            else:
                extend_days = pkg_duration * 30
        else:
            extend_days = item.get("term_months", 1) * 30
        
        # Parse current expiry safely
        current_expiry = existing_service.get("expiry_date")
        if isinstance(current_expiry, str):
            try:
                current_expiry = datetime.fromisoformat(current_expiry.replace("Z", ""))
            except ValueError:
                current_expiry = datetime.utcnow()
        if not current_expiry:
            current_expiry = datetime.utcnow()
        
        if current_expiry < datetime.utcnow():
            new_expiry = datetime.utcnow() + timedelta(days=extend_days)
        else:
            new_expiry = current_expiry + timedelta(days=extend_days)
        
        new_expiry_str = new_expiry.strftime("%Y-%m-%d")
        
        # Prepare edit_line request data
        request_data = {
            'id': str(line_id),
            'package': str(product.get('xtream_package_id', '')),
            'trial': '1' if product.get('is_trial') else '0',
            'reseller_notes': f'Renewal - Order {order_id}',
            'is_isplock': '0'
        }
        
        logger.info(f"Extending line {line_id} to {new_expiry_str}")
        
        # Get API URL
        api_url = xuione_service.get_api_url()
        
        # Make API request to edit_line
        import requests
        response = xuione_service.session.post(
            api_url,
            params={
                'api_key': xuione_service.api_key,
                'action': 'edit_line'
            },
            data=request_data,
            headers={
                'User-Agent': 'IPTV-Billing-System/1.0',
                'Accept': '*/*'
            },
            timeout=30
        )
        
        logger.info(f"XuiOne edit_line response: status={response.status_code}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                logger.info(f"XuiOne edit_line result: {result}")
                
                if result.get('status') == 'STATUS_SUCCESS':
                    logger.info(f"✓ XuiOne line extended successfully")
                    
                    # Fetch actual expiry from panel
                    actual_expiry = new_expiry
                    try:
                        lines_resp = xuione_service.session.get(
                            api_url,
                            params={'api_key': xuione_service.api_key, 'action': 'get_lines'},
                            timeout=15
                        )
                        if lines_resp.status_code == 200:
                            lines_data = lines_resp.json().get('data', [])
                            for line in lines_data:
                                if str(line.get('id')) == str(line_id) or line.get('username') == existing_service.get('xtream_username'):
                                    exp_str = line.get('exp_date', '')
                                    if exp_str:
                                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                            try:
                                                actual_expiry = datetime.strptime(str(exp_str).strip(), fmt)
                                                logger.info(f"Got actual expiry from XuiOne panel: {actual_expiry}")
                                                break
                                            except ValueError:
                                                continue
                                    break
                    except Exception as e:
                        logger.warning(f"Could not fetch actual expiry from XuiOne: {e}")
                    
                    # Update existing service expiry in our database
                    await services_collection.update_one(
                        {"_id": existing_service["_id"]},
                        {"$set": {
                            "expiry_date": actual_expiry,
                            "status": "active"
                        }}
                    )
                    
                    # Send renewal email
                    if email_service:
                        await email_service.send_service_renewed(
                            customer_email=user["email"],
                            customer_name=user["name"],
                            service_name=item["product_name"],
                            username=existing_service["xtream_username"],
                            new_expiry_date=new_expiry_str,
                            customer_id=order["user_id"]
                        )
                    
                    logger.info(f"Service renewed and extended to {new_expiry}")
                else:
                    logger.error(f"XuiOne edit_line failed: {result}")
                    
            except ValueError as json_err:
                logger.error(f"XuiOne edit_line: Invalid JSON response")
        else:
            logger.error(f"XuiOne edit_line HTTP error: {response.status_code}")
            
    except Exception as e:
        logger.error(f"XuiOne extension error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

async def provision_xuione_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision XuiOne service using API"""
    try:
        xuione_settings = settings.get("xuione", {})
        panels = xuione_settings.get("panels", [])
        
        if not panels or len(panels) == 0:
            logger.warning("XuiOne not configured, skipping provisioning")
            return
        
        # Get panel index from product
        panel_index = safe_panel_index(product.get("panel_index"))
        
        # Validate panel index
        if panel_index >= len(panels):
            logger.error(f"Product references XuiOne panel {panel_index} but only {len(panels)} panels exist. Using first panel.")
            panel_index = 0
        
        panel = panels[panel_index]
        panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
        
        logger.info(f"Provisioning XuiOne service on panel: {panel_name}")
        
        # Initialize XuiOne service
        xuione_service = XuiOneService(
            panel_url=panel["panel_url"],
            api_access_code=panel.get("api_access_code", ""),
            api_key=panel.get("api_key", ""),
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            ssl_verify=panel.get("ssl_verify", False)
        )
        
        # Generate or use custom credentials
        if item["account_type"] == "reseller" and order.get("reseller_credentials"):
            username = order["reseller_credentials"].get("username", generate_username())
            password = order["reseller_credentials"].get("password", generate_password())
            logger.info(f"Using custom reseller credentials: {username}")
        else:
            username = generate_username()
            password = generate_password()
        
        # Calculate expiry date
        term_months = item["term_months"]
        
        # For trial products, use actual trial duration instead of term_months
        if product.get("is_trial") and product.get("trial_duration"):
            trial_duration = int(product.get("trial_duration", 1))
            trial_unit = (product.get("trial_duration_unit") or "days").lower()
            if trial_unit in ("hours", "hour"):
                expiry_date = datetime.utcnow() + timedelta(hours=trial_duration)
            elif trial_unit in ("days", "day"):
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration)
            elif trial_unit in ("months", "month"):
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration * 30)
            else:
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration)
            logger.info(f"Trial product (XuiOne): duration={trial_duration} {trial_unit}, expiry={expiry_date}")
        else:
            # Use product duration from package, fallback to term_months
            pkg_duration = product.get("duration") or product.get("official_duration")
            pkg_dur_unit = (product.get("duration_unit") or product.get("official_duration_in") or "months").lower()
            if pkg_duration:
                pkg_duration = int(pkg_duration)
                if pkg_dur_unit in ("months", "month"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
                elif pkg_dur_unit in ("years", "year"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 365)
                elif pkg_dur_unit in ("days", "day"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration)
                else:
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
            else:
                expiry_date = datetime.utcnow() + timedelta(days=term_months * 30)
        
        expiry_date_str = expiry_date.strftime("%Y-%m-%d")
        
        # Create service record
        service_dict = {
            "user_id": order["user_id"],
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "account_type": item["account_type"],
            "term_months": term_months,
            "xtream_username": username,  # Keep field name for compatibility
            "xtream_password": password,
            "status": "pending",
            "panel_type": "xuione",
            "panel_index": panel_index,
            "panel_name": panel_name,
            "created_at": datetime.utcnow()
        }
        
        if item["account_type"] == "subscriber":
            # Check for existing service (renewal scenario)
            existing_service = None
            renewal_service_id = item.get("renewal_service_id")
            
            if renewal_service_id:
                # Customer explicitly chose to extend a specific service
                existing_service = await services_collection.find_one({
                    "_id": str_to_objectid(renewal_service_id),
                    "user_id": order["user_id"],
                    "panel_type": "xuione"
                })
                if existing_service:
                    logger.info(f"Renewal: Extending XuiOne line {existing_service.get('xtream_username')}")
            
            # Also check by action_type=renew without explicit service ID
            if not existing_service and item.get("action_type") in ("renew", "extend"):
                existing_service = await services_collection.find_one({
                    "user_id": order["user_id"],
                    "product_id": item["product_id"],
                    "panel_type": "xuione",
                    "status": {"$in": ["active", "expired"]}
                })
                if existing_service:
                    logger.info(f"Renewal (by product match): Extending XuiOne line {existing_service.get('xtream_username')}")
            
            if existing_service:
                # RENEWAL - Extend existing line using edit_line API
                await extend_xuione_line(xuione_service, existing_service, item, product, order, order_id, user, email_service)
                return
            else:
                # NEW SUBSCRIPTION - Create new line
                logger.info(f"Creating XuiOne subscriber: {username}")
            
            # XuiOne API requires api_key
            if not xuione_service.api_key:
                logger.error("XuiOne API key not configured!")
                service_dict["status"] = "failed"
                service_dict["error"] = "API key not configured"
                await services_collection.insert_one(service_dict)
                return
            
            # Make API request to create line
            # Note: XuiOne API might require BOTH api_key AND session cookies
            import requests
            try:
                # Login first to get session cookie
                if not xuione_service.logged_in:
                    login_result = xuione_service.login()
                    if not login_result:
                        logger.error("XuiOne: Failed to login before API call")
                        service_dict["status"] = "failed"
                        service_dict["error"] = "Login failed"
                        await services_collection.insert_one(service_dict)
                        return
                
                # Use the logged-in session (with cookies) for API calls
                logger.info(f"Using session with cookies: {bool(xuione_service.session.cookies)}")
                
                # Use the API URL (with API access code) instead of web URL
                api_url = xuione_service.get_api_url()
                
                logger.info(f"XuiOne API URL: {api_url}/?api_key=***&action=create_line")
                
                logger.info(f"Creating line: package={product.get('xtream_package_id', '')}, connections={product['max_connections']}, expiry={expiry_date_str}, is_trial={product.get('is_trial', False)}")
                
                # XuiOne WHMCS module format (from working implementation)
                request_data = {
                    'username': username,
                    'password': password,
                    'package': str(product.get('xtream_package_id', '')),  # Package ID from XuiOne
                    'trial': '1' if product.get('is_trial') else '0',  # Important: trial flag!
                    'reseller_notes': f'Billing System - Order {order_id}',
                    'is_isplock': '0'  # ISP lock disabled by default
                }
                
                logger.info(f"Request data: {request_data}")
                
                # Use the logged-in session (has cookies) instead of fresh session
                response = xuione_service.session.post(
                    api_url,
                    params={
                        'api_key': xuione_service.api_key,
                        'action': 'create_line'
                    },
                    data=request_data,
                    headers={
                        'User-Agent': 'IPTV-Billing-System/1.0',
                        'Accept': '*/*'
                    },
                    timeout=30
                )
                
                logger.info(f"XuiOne create_line response: status={response.status_code}, content-type={response.headers.get('content-type')}")
                logger.info(f"Response preview: {response.text[:500]}")
                
                if response.status_code == 200:
                    # Try to parse as JSON regardless of content-type (XuiOne sends wrong headers)
                    try:
                        result = response.json()
                        logger.info(f"XuiOne create_line result: {result}")
                        
                        if result.get('status') == 'STATUS_SUCCESS':
                            logger.info(f"✓ XuiOne line created successfully")
                            
                            # Store the line ID for future renewals
                            line_id = result.get('data', {}).get('id')
                            
                            # Try to get actual expiry from response
                            actual_expiry = expiry_date
                            resp_data = result.get('data', {})
                            if resp_data.get('exp_date'):
                                exp_val = resp_data['exp_date']
                                try:
                                    if str(exp_val).isdigit():
                                        actual_expiry = datetime.fromtimestamp(int(exp_val))
                                    else:
                                        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                            try:
                                                actual_expiry = datetime.strptime(str(exp_val).strip(), fmt)
                                                break
                                            except ValueError:
                                                continue
                                    logger.info(f"Actual XuiOne expiry: {actual_expiry}")
                                except Exception:
                                    pass
                            expiry_date = actual_expiry
                            expiry_date_str = actual_expiry.strftime("%Y-%m-%d")
                            
                            service_dict.update({
                                "bouquets": product["bouquets"],
                                "max_connections": product["max_connections"],
                                "status": "active",
                                "start_date": datetime.utcnow(),
                                "expiry_date": actual_expiry,
                                "dedicatedip": line_id,  # Store XuiOne line ID for renewals
                                "xuione_line_id": line_id,  # Alternative field name
                                "panel_url": panel.get("panel_url", "")  # Store panel URL for customer display
                            })
                        elif result.get('status') == 'STATUS_INVALID_PACKAGE':
                            logger.error(f"XuiOne: Invalid package - check bouquets configuration")
                            service_dict["status"] = "failed"
                            service_dict["error"] = "Invalid package/bouquets configuration"
                        else:
                            logger.error(f"XuiOne API returned error: {result}")
                            service_dict["status"] = "failed"
                            service_dict["error"] = result.get("message", result.get("status", "Unknown error"))
                    except ValueError as json_err:
                        # If it's truly not JSON, it might be HTML login page
                        if '<html' in response.text.lower():
                            logger.error("XuiOne API returned HTML (login page) - authentication failed")
                            service_dict["status"] = "failed"
                            service_dict["error"] = "API authentication failed - check API key"
                        else:
                            logger.error(f"XuiOne response is not valid JSON: {json_err}")
                            service_dict["status"] = "failed"
                            service_dict["error"] = "Invalid API response"
                else:
                    logger.error(f"XuiOne API HTTP error: {response.status_code}")
                    service_dict["status"] = "failed"
                    service_dict["error"] = f"HTTP {response.status_code}"
                    
            except Exception as api_err:
                logger.error(f"XuiOne API error: {api_err}")
                service_dict["status"] = "failed"
                service_dict["error"] = str(api_err)
            
            # Insert service record
            await services_collection.insert_one(service_dict)
            
            # Send activation email if successful
            if service_dict["status"] == "active" and email_service:
                await email_service.send_service_activated(
                    customer_email=user["email"],
                    customer_name=user["name"],
                    service_name=item["product_name"],
                    username=username,
                    password=password,
                    streaming_url=panel.get("streaming_url") or panel.get("panel_url", ""),  # XuiOne streaming URL
                    max_connections=product["max_connections"],
                    expiry_date=expiry_date_str,
                    customer_id=order["user_id"]
                )
                
                # Send "Service Activated" Telegram notification
                await send_telegram_notification(
                    "service_activated",
                    f"✅ *Service Activated*\n\nCustomer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XuiOne)\nUsername: {username}\nExpiry: {expiry_date_str}"
                )
                await send_email_notification(
                    "service_activated",
                    "Service Activated",
                    f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XuiOne)\nUsername: {username}\nExpiry: {expiry_date_str}"
                )
                await send_sms_notification("service_activated", f"Customer: {user.get('name', 'Unknown')}\nEmail: {user.get('email', 'N/A')}\nService: {item['product_name']}\nPanel: {panel_name} (XuiOne)\nUsername: {username}\nExpiry: {expiry_date_str}")
        
        else:
            # RESELLER PROVISIONING
            logger.info(f"Creating XuiOne reseller: {username}")
            
            # XuiOne API requires api_key
            if not xuione_service.api_key:
                logger.error("XuiOne API key not configured!")
                service_dict["status"] = "failed"
                service_dict["error"] = "API key not configured"
                await services_collection.insert_one(service_dict)
                return
            
            # Login first to get session cookie
            if not xuione_service.logged_in:
                if not xuione_service.login():
                    logger.error("XuiOne: Login failed")
                    service_dict["status"] = "failed"
                    service_dict["error"] = "Login failed"
                    await services_collection.insert_one(service_dict)
                    return
            
            # Get API URL
            api_url = xuione_service.get_api_url()
            
            # Prepare create_user request for reseller
            request_data = {
                'username': username,
                'password': password,
                'email': user.get('email', ''),
                'member_group_id': '2',  # 2 = Reseller
                'credits': str(int(product.get('reseller_credits', 0))),  # Integer string
                'notes': f'Billing System - Order {order_id}',
                'owner_id': '247'  # Parent reseller ID (numeric)
            }
            
            logger.info(f"Creating reseller with {product.get('reseller_credits', 0)} credits")
            
            import requests
            try:
                response = xuione_service.session.post(
                    api_url,
                    params={
                        'api_key': xuione_service.api_key,
                        'action': 'create_user'
                    },
                    data=request_data,
                    headers={
                        'User-Agent': 'IPTV-Billing-System/1.0',
                        'Accept': '*/*'
                    },
                    timeout=30
                )
                
                logger.info(f"XuiOne create_user response: status={response.status_code}")
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        logger.info(f"XuiOne create_user result: {result}")
                        
                        if result.get('status') == 'STATUS_SUCCESS':
                            logger.info(f"✓ XuiOne reseller created successfully")
                            
                            # Store the reseller ID
                            reseller_id = result.get('data', {}).get('id')
                            
                            # Add credits via adjust_credits action (all params in query string)
                            if product.get('reseller_credits', 0) > 0:
                                credits_amount = int(product['reseller_credits'])
                                logger.info(f"Adding {credits_amount} credits to reseller {reseller_id}")
                                
                                credits_response = xuione_service.session.post(
                                    api_url,
                                    params={
                                        'api_key': xuione_service.api_key,
                                        'action': 'adjust_credits',
                                        'id': reseller_id,
                                        'credits': str(credits_amount),
                                        'reason': f'Initial allocation - Order {order_id}'
                                    },
                                    headers={
                                        'User-Agent': 'IPTV-Billing-System/1.0',
                                        'Accept': '*/*'
                                    },
                                    timeout=30
                                )
                                
                                if credits_response.status_code == 200:
                                    try:
                                        credits_result = credits_response.json()
                                        logger.info(f"Adjust credits result: {credits_result}")
                                        
                                        if credits_result.get('status') == 'STATUS_SUCCESS':
                                            logger.info(f"✓ Credits adjusted successfully")
                                            
                                            # Verify new balance
                                            verify_response = xuione_service.session.get(
                                                api_url,
                                                params={
                                                    'api_key': xuione_service.api_key,
                                                    'action': 'get_user',
                                                    'id': reseller_id
                                                },
                                                timeout=10
                                            )
                                            if verify_response.status_code == 200:
                                                verify_data = verify_response.json()
                                                new_balance = verify_data.get('data', {}).get('credits', 'unknown')
                                                logger.info(f"✓ Verified new credit balance: {new_balance}")
                                        else:
                                            logger.warning(f"Failed to adjust credits: {credits_result}")
                                    except ValueError:
                                        logger.warning("Credits response not JSON")
                                else:
                                    logger.warning(f"Adjust credits HTTP error: {credits_response.status_code}")
                            
                            service_dict.update({
                                "status": "active",
                                "start_date": datetime.utcnow(),
                                "expiry_date": None,  # Resellers don't expire
                                "dedicatedip": reseller_id,  # Store reseller ID
                                "xuione_reseller_id": reseller_id,
                                "reseller_credits": product.get('reseller_credits', 0),
                                "panel_url": panel.get("panel_url", "")  # Store panel URL for customer display
                            })
                        else:
                            logger.error(f"XuiOne create_user failed: {result}")
                            service_dict["status"] = "failed"
                            service_dict["error"] = result.get("message", result.get("status", "Unknown error"))
                    except ValueError as json_err:
                        logger.error(f"XuiOne response is not valid JSON")
                        service_dict["status"] = "failed"
                        service_dict["error"] = "Invalid API response"
                else:
                    logger.error(f"XuiOne create_user HTTP error: {response.status_code}")
                    service_dict["status"] = "failed"
                    service_dict["error"] = f"HTTP {response.status_code}"
                    
            except Exception as api_err:
                logger.error(f"XuiOne create_user error: {api_err}")
                service_dict["status"] = "failed"
                service_dict["error"] = str(api_err)
            
            # Insert service record
            await services_collection.insert_one(service_dict)
            
            # Send activation email if successful
            if service_dict["status"] == "active" and email_service:
                # Note: Email templates may need to be adapted for reseller accounts
                logger.info(f"Reseller {username} created with {product.get('reseller_credits', 0)} credits")

    except Exception as e:
        logger.error(f"XuiOne provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

async def provision_onestream_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision 1-Stream service via API"""
    try:
        os_panels = settings.get("onestream", {}).get("panels", [])
        panel_index = safe_panel_index(product.get("panel_index"))
        
        if not os_panels or panel_index >= len(os_panels):
            logger.error(f"1-Stream panel not configured (index {panel_index}, {len(os_panels)} panels available)")
            if os_panels:
                panel_index = 0
            else:
                return
        
        panel = os_panels[panel_index]
        panel_name = panel.get("name", f"1-Stream Panel {panel_index + 1}")
        
        os_service = get_onestream_service(panel)
        if not os_service:
            logger.error("1-Stream service not available")
            return
        
        # Use customer's chosen credentials for resellers, auto-generate for subscribers
        if item.get("account_type") == "reseller" and order.get("reseller_credentials"):
            username = order["reseller_credentials"].get("username", generate_username())
            password = order["reseller_credentials"].get("password", generate_password())
            logger.info(f"Using custom reseller credentials: {username}")
        else:
            username = generate_username()
            password = generate_password()
        
        # Calculate expiry
        term_months = item["term_months"]
        if product.get("is_trial") and product.get("trial_duration"):
            trial_duration = int(product.get("trial_duration", 1))
            trial_unit = (product.get("trial_duration_unit") or "days").lower()
            if trial_unit in ("hours", "hour"):
                expiry_date = datetime.utcnow() + timedelta(hours=trial_duration)
            elif trial_unit in ("days", "day"):
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration)
            else:
                expiry_date = datetime.utcnow() + timedelta(days=trial_duration * 30)
        else:
            pkg_duration = product.get("duration") or product.get("official_duration")
            pkg_dur_unit = (product.get("duration_unit") or product.get("official_duration_in") or "months").lower()
            if pkg_duration:
                pkg_duration = int(pkg_duration)
                if pkg_dur_unit in ("months", "month"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
                elif pkg_dur_unit in ("years", "year"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 365)
                elif pkg_dur_unit in ("days", "day"):
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration)
                else:
                    expiry_date = datetime.utcnow() + timedelta(days=pkg_duration * 30)
            else:
                expiry_date = datetime.utcnow() + timedelta(days=term_months * 30)
        
        package_id = product.get("xtream_package_id")
        
        if item.get("account_type") == "subscriber":
            # Check if extending an existing service
            action_type = item.get("action_type", "create_new")
            renewal_service_id = item.get("renewal_service_id")
            existing_subscriber = None
            
            if renewal_service_id and action_type == "extend":
                existing_subscriber = await services_collection.find_one({
                    "_id": str_to_objectid(renewal_service_id),
                    "user_id": order["user_id"],
                    "status": "active"
                })
                if existing_subscriber:
                    logger.info(f"Extending existing 1-Stream line: {existing_subscriber.get('xtream_username')}")
            
            if existing_subscriber:
                # EXTEND existing line via /ext/line/{uuid}/renew
                line_id = existing_subscriber.get("onestream_line_id", "")
                if not line_id:
                    # Try to find by username
                    find_result = os_service.find_line(
                        existing_subscriber.get("xtream_username", ""),
                        existing_subscriber.get("xtream_password", "")
                    )
                    if find_result.get("success"):
                        line_id = find_result.get("line_id", "")
                
                if line_id:
                    renew_result = os_service.renew_line(line_id, package_id)
                    if renew_result.get("success"):
                        # Update expiry from API response
                        new_expiry = expiry_date
                        if renew_result.get("expire_at"):
                            try:
                                api_expiry = datetime.fromisoformat(renew_result["expire_at"].replace("Z", "+00:00"))
                                if api_expiry.tzinfo:
                                    api_expiry = api_expiry.replace(tzinfo=None)
                                new_expiry = api_expiry
                            except Exception:
                                # Calculate from current expiry
                                current_exp = existing_subscriber.get("expiry_date", datetime.utcnow())
                                if isinstance(current_exp, str):
                                    current_exp = datetime.fromisoformat(current_exp.replace('Z', '+00:00')).replace(tzinfo=None)
                                if current_exp < datetime.utcnow():
                                    current_exp = datetime.utcnow()
                                new_expiry = current_exp + timedelta(days=term_months * 30)
                                # Use product duration if available
                                pkg_dur = product.get("duration") or product.get("official_duration")
                                pkg_dur_unit = (product.get("duration_unit") or "months").lower()
                                if pkg_dur:
                                    pkg_dur = int(pkg_dur)
                                    if pkg_dur_unit in ("months", "month"):
                                        new_expiry = current_exp + timedelta(days=pkg_dur * 30)
                                    elif pkg_dur_unit in ("years", "year"):
                                        new_expiry = current_exp + timedelta(days=pkg_dur * 365)
                                    elif pkg_dur_unit in ("days", "day"):
                                        new_expiry = current_exp + timedelta(days=pkg_dur)
                        
                        await services_collection.update_one(
                            {"_id": existing_subscriber["_id"]},
                            {"$set": {"expiry_date": new_expiry, "status": "active"}}
                        )
                        logger.info(f"1-Stream line extended, new expiry: {new_expiry}")
                        
                        if email_service:
                            await email_service.send_service_renewed(
                                customer_email=user["email"],
                                customer_name=user["name"],
                                service_name=item["product_name"],
                                username=existing_subscriber.get("xtream_username", ""),
                                new_expiry_date=new_expiry.strftime("%Y-%m-%d"),
                                customer_id=order["user_id"]
                            )
                        return
                    else:
                        logger.error(f"1-Stream renew failed: {renew_result.get('error')}")
                else:
                    logger.error("Could not find line_id for existing 1-Stream subscriber")
            
            # CREATE new line (no existing subscriber or extend failed)
            logger.info(f"Creating 1-Stream line: user={username}, package={package_id}")
            result = os_service.create_line(
                username=username,
                password=password,
                package_id=package_id,
                reseller_notes=f"Order {order_id} - {user['name']}",
                max_connections=product.get("max_connections", 1)
            )
            
            if result.get("success"):
                # Use expiry from API response if available
                if result.get("expire_at"):
                    try:
                        api_expiry = datetime.fromisoformat(result["expire_at"].replace("Z", "+00:00"))
                        if api_expiry.tzinfo:
                            api_expiry = api_expiry.replace(tzinfo=None)
                        expiry_date = api_expiry
                    except Exception:
                        pass
                
                service_dict = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "account_type": "subscriber",
                    "term_months": term_months,
                    "xtream_username": username,
                    "xtream_password": password,
                    "status": "active",
                    "panel_index": panel_index,
                    "panel_name": panel_name,
                    "panel_type": "onestream",
                    "onestream_line_id": result.get("line_id", ""),
                    "bouquets": product.get("bouquets", []),
                    "max_connections": product.get("max_connections", 1),
                    "is_trial": product.get("is_trial", False),
                    "streaming_url": panel.get("streaming_url") or panel.get("panel_url", ""),
                    "start_date": datetime.utcnow(),
                    "expiry_date": expiry_date,
                    "created_at": datetime.utcnow()
                }
                await services_collection.insert_one(service_dict)
                
                # Send activation email
                if email_service:
                    streaming_url = panel.get("panel_url", "")
                    await email_service.send_service_activated(
                        customer_email=user["email"],
                        customer_name=user["name"],
                        service_name=item["product_name"],
                        username=username,
                        password=password,
                        streaming_url=streaming_url,
                        max_connections=product.get("max_connections", 1),
                        expiry_date=expiry_date.strftime("%Y-%m-%d"),
                        customer_id=order["user_id"]
                    )
                
                await send_telegram_notification(
                    "service_activated",
                    f"✅ *Service Activated (1-Stream)*\n\nCustomer: {user.get('name')}\nEmail: {user.get('email')}\nService: {item['product_name']}\nPanel: {panel_name}\nUsername: {username}\nExpiry: {expiry_date.strftime('%Y-%m-%d')}"
                )
                await send_email_notification(
                    "service_activated",
                    "Service Activated (1-Stream)",
                    f"Customer: {user.get('name')}\nEmail: {user.get('email')}\nService: {item['product_name']}\nPanel: {panel_name}\nUsername: {username}\nExpiry: {expiry_date.strftime('%Y-%m-%d')}"
                )
                await send_sms_notification("service_activated", f"Customer: {user.get('name')}\nEmail: {user.get('email')}\nService: {item['product_name']}\nPanel: {panel_name}\nUsername: {username}\nExpiry: {expiry_date.strftime('%Y-%m-%d')}")
                
                logger.info(f"1-Stream subscriber provisioned: {username}")
            else:
                logger.error(f"Failed to create 1-Stream line: {result.get('error')}")
                service_dict = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "account_type": "subscriber",
                    "term_months": term_months,
                    "xtream_username": username,
                    "xtream_password": password,
                    "status": "failed",
                    "panel_index": panel_index,
                    "panel_name": panel_name,
                    "panel_type": "onestream",
                    "created_at": datetime.utcnow()
                }
                await services_collection.insert_one(service_dict)
        
        else:  # reseller
            # Check if user already has an active reseller on this 1-Stream panel
            existing_reseller = await services_collection.find_one({
                "user_id": order["user_id"],
                "account_type": "reseller",
                "status": "active",
                "panel_type": "onestream",
                "panel_index": panel_index
            })
            
            if existing_reseller:
                # Add credits to existing reseller
                reseller_name = existing_reseller.get("xtream_username", "")
                new_credits = product.get("reseller_credits", 0)
                logger.info(f"Adding {new_credits} credits to existing 1-Stream reseller: {reseller_name}")
                
                # Find the reseller's user_id on the 1-Stream panel
                resellers = os_service.get_subresellers()
                os_user_id = None
                if resellers.get("success"):
                    for r in resellers.get("users", []):
                        if r.get("username") == reseller_name:
                            os_user_id = r.get("user_id")
                            break
                
                if os_user_id:
                    credit_result = os_service.update_subreseller_credits(os_user_id, new_credits)
                    if credit_result.get("success"):
                        logger.info(f"Credits added to 1-Stream reseller {reseller_name}")
                    else:
                        logger.error(f"Failed to add credits: {credit_result.get('error')}")
                else:
                    logger.error(f"Could not find 1-Stream user_id for reseller {reseller_name}")
                
                # Create service record for the credit addition
                service_dict = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "account_type": "reseller",
                    "term_months": term_months,
                    "xtream_username": existing_reseller.get("xtream_username"),
                    "xtream_password": existing_reseller.get("xtream_password"),
                    "status": "active",
                    "panel_index": panel_index,
                    "panel_name": panel_name,
                    "panel_type": "onestream",
                    "reseller_credits": new_credits,
                    "is_credit_addon": True,
                    "start_date": datetime.utcnow(),
                    "created_at": datetime.utcnow()
                }
                await services_collection.insert_one(service_dict)
                logger.info(f"Credit addon service record created for {reseller_name}")
                
            else:
                # Create new reseller
                logger.info(f"Creating 1-Stream sub-reseller: {username}")
                result = os_service.create_subreseller(
                    name=username,
                    email=user.get("email", f"{username}@billing.local"),
                    password=password,
                    credits=product.get("reseller_credits", 0),
                    notes=f"Order {order_id} - {user['name']}"
                )
                
                if result.get("success"):
                    service_dict = {
                        "user_id": order["user_id"],
                        "order_id": order_id,
                        "product_id": item["product_id"],
                        "product_name": item["product_name"],
                        "account_type": "reseller",
                        "term_months": term_months,
                        "xtream_username": username,
                        "xtream_password": password,
                        "status": "active",
                        "panel_index": panel_index,
                        "panel_name": panel_name,
                        "panel_type": "onestream",
                        "reseller_credits": product.get("reseller_credits", 0),
                        "start_date": datetime.utcnow(),
                        "created_at": datetime.utcnow()
                    }
                    await services_collection.insert_one(service_dict)
                    logger.info(f"1-Stream reseller provisioned: {username}")
                else:
                    logger.error(f"Failed to create 1-Stream reseller: {result.get('error')}")
    
    except Exception as e:
        logger.error(f"1-Stream provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


async def provision_nxtdash_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision NXT Dash service via API"""
    try:
        nd_panels = settings.get("nxtdash", {}).get("panels", [])
        panel_index = safe_panel_index(product.get("panel_index"))

        if not nd_panels or panel_index >= len(nd_panels):
            logger.error(f"NXT Dash panel not configured (index {panel_index}, {len(nd_panels)} panels available)")
            if nd_panels:
                panel_index = 0
            else:
                return

        panel = nd_panels[panel_index]
        panel_name = panel.get("name", f"NXT Dash Panel {panel_index + 1}")

        nd_service = get_nxtdash_service(panel)
        if not nd_service:
            logger.error("NXT Dash service not available")
            return

        account_type = product.get("account_type", "subscriber")
        is_trial = product.get("is_trial", False)
        package_id = product.get("panel_package_id") or product.get("xtream_package_id") or product.get("package_id", 0)
        action_type = item.get("action_type", "create_new")
        renewal_service_id = item.get("renewal_service_id")

        # Generate or reuse credentials
        import random, string
        username = item.get("reseller_username", "")
        password = item.get("reseller_password", "")
        if not username:
            username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        if not password:
            password = "".join(random.choices(string.ascii_letters + string.digits, k=10))

        if renewal_service_id and action_type == "extend" and account_type == "subscriber":
            # Find existing service to extend
            existing = await services_collection.find_one({
                "_id": str_to_objectid(renewal_service_id),
                "user_id": order["user_id"],
            })
            if existing:
                line_id = existing.get("nxtdash_line_id", "")
                if not line_id:
                    line_id = await nd_service.get_line_id(existing.get("username", ""), existing.get("password", ""))
                if line_id:
                    result = await nd_service.extend_line(str(line_id), int(package_id))
                    if result.get("success"):
                        expire_ts = result.get("expire_date")
                        expiry_str = ""
                        if expire_ts:
                            from datetime import timezone
                            expiry_str = datetime.fromtimestamp(int(expire_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        await services_collection.update_one(
                            {"_id": existing["_id"]},
                            {"$set": {"expiry_date": expiry_str, "status": "active", "updated_at": datetime.utcnow()}}
                        )
                        logger.info(f"NXT Dash line extended: {existing.get('username')} -> {expiry_str}")
                    else:
                        logger.error(f"NXT Dash extend failed: {result.get('error')}")
                return

        if account_type == "subscriber":
            description = f"Billing:{order_id[:8]}"
            # Pass product bouquets — only selected bouquets will be provisioned
            product_bouquets = product.get("bouquets", None)
            if product_bouquets is not None and len(product_bouquets) > 0:
                product_bouquets = [int(b) for b in product_bouquets]
            else:
                product_bouquets = None  # None = use package defaults
            
            result = await nd_service.create_line(
                username=username,
                password=password,
                package_id=int(package_id),
                description=description,
                is_trial=is_trial,
                bouquets=product_bouquets,
            )
            if result.get("success"):
                api_user = result.get("username", username)
                api_pass = result.get("password", password)
                expire_ts = result.get("expire_date")
                expiry_str = ""
                if expire_ts:
                    from datetime import timezone
                    expiry_str = datetime.fromtimestamp(int(expire_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                portal_url = panel.get("streaming_url") or panel.get("portal_url") or panel.get("panel_url", "")

                service_doc = {
                    "user_id": order["user_id"],
                    "order_id": order_id,
                    "product_id": str(product.get("_id", item.get("product_id", ""))),
                    "product_name": product.get("name", "NXT Dash Service"),
                    "username": api_user,
                    "password": api_pass,
                    "xtream_username": api_user,
                    "xtream_password": api_pass,
                    "panel_type": "nxtdash",
                    "panel_name": panel_name,
                    "panel_index": panel_index,
                    "nxtdash_line_id": result.get("line_id", ""),
                    "account_type": "subscriber",
                    "max_connections": product.get("max_connections", 1),
                    "is_trial": product.get("is_trial", False),
                    "streaming_url": portal_url,
                    "expiry_date": expiry_str,
                    "status": "active",
                    "created_at": datetime.utcnow(),
                }
                await services_collection.insert_one(service_doc)
                logger.info(f"NXT Dash subscriber provisioned: {api_user}")

                # Send activation email
                if email_service:
                    try:
                        await email_service.send_service_activated(
                            customer_email=user["email"],
                            customer_name=user.get("name", "Customer"),
                            service_name=product.get("name", "NXT Dash Service"),
                            username=api_user,
                            password=api_pass,
                            streaming_url=portal_url,
                            max_connections=product.get("max_connections", 1),
                            expiry_date=expiry_str.split(" ")[0] if expiry_str else "N/A",
                            customer_id=order["user_id"]
                        )
                    except Exception as email_err:
                        logger.warning(f"NXT Dash activation email failed: {email_err}")
            else:
                logger.error(f"NXT Dash create line failed: {result.get('error')}")

    except Exception as e:
        logger.error(f"NXT Dash provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


async def provision_aether_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision an Aether panel line via the /api/v1 Reseller API"""
    try:
        ae_panels = settings.get("aether", {}).get("panels", [])
        panel_index = safe_panel_index(product.get("panel_index"))
        if not ae_panels:
            logger.error("Aether panel not configured")
            return
        if panel_index >= len(ae_panels):
            panel_index = 0
        panel = ae_panels[panel_index]
        panel_name = panel.get("name", f"Aether Panel {panel_index + 1}")

        ae = get_aether_service(panel)
        if not ae:
            logger.error("Aether service not available (missing panel_url or api_token)")
            return

        account_type = product.get("account_type", "subscriber")
        if account_type != "subscriber":
            logger.error("Aether: only subscriber lines can be provisioned via the API")
            return

        package_id = product.get("panel_package_id") or product.get("xtream_package_id") or product.get("package_id", 0)
        if not package_id:
            logger.error(f"Aether: product '{product.get('name')}' has no package_id")
            return
        action_type = item.get("action_type", "create_new")
        renewal_service_id = item.get("renewal_service_id")

        # Renewal of an existing line
        if renewal_service_id and action_type in ("renew", "extend"):
            existing = await services_collection.find_one({
                "_id": str_to_objectid(renewal_service_id),
                "user_id": order["user_id"],
            })
            if not existing:
                logger.error(f"Aether renewal: service {renewal_service_id} not found")
                return
            line_user = existing.get("xtream_username") or existing.get("username", "")
            result = await ae.renew_line(line_user, int(package_id), idem_key=f"billing-{order_id}-renew-{renewal_service_id}")
            if result.get("success"):
                new_exp = result.get("new_expiry")
                await services_collection.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"expiry_date": new_exp, "status": "active", "updated_at": datetime.utcnow()}}
                )
                logger.info(f"Aether line renewed: {line_user} -> {new_exp}")
                if email_service and new_exp:
                    try:
                        await email_service.send_service_renewed(
                            customer_email=user["email"], customer_name=user.get("name", "Customer"),
                            service_name=existing.get("product_name", product.get("name", "Aether Service")),
                            username=line_user, new_expiry_date=new_exp.strftime("%Y-%m-%d"),
                            customer_id=order["user_id"]
                        )
                    except Exception as email_err:
                        logger.warning(f"Aether renewal email failed: {email_err}")
            else:
                logger.error(f"Aether renew failed: {result.get('error')}")
            return

        username = item.get("reseller_username") or generate_username()
        password = item.get("reseller_password") or generate_password()
        product_bouquets = product.get("bouquets") or None
        notes = render_provision_notes(
            settings.get("branding", {}).get("provision_notes_template", ""),
            customer_name=user.get("name", ""), email=user.get("email", ""), order_id=order_id[:8]
        )

        result = await ae.create_line(
            package_id=int(package_id), username=username, password=password,
            bouquet_ids=[int(b) for b in product_bouquets] if product_bouquets else None,
            notes=notes, idem_key=f"billing-{order_id}-{item.get('product_id', '')}-create",
        )
        if not result.get("success"):
            logger.error(f"Aether create line failed: {result.get('error')}")
            return

        api_user = result.get("username") or username
        api_pass = result.get("password") or password
        expiry_dt = AetherService.parse_exp(result.get("exp_date"))
        streaming_url = await ae.resolve_streaming_url(api_user)

        service_doc = {
            "user_id": order["user_id"],
            "order_id": order_id,
            "product_id": str(product.get("_id", item.get("product_id", ""))),
            "product_name": product.get("name", "Aether Service"),
            "username": api_user,
            "password": api_pass,
            "xtream_username": api_user,
            "xtream_password": api_pass,
            "panel_type": "aether",
            "panel_name": panel_name,
            "panel_index": panel_index,
            "aether_line_id": result.get("line_id", ""),
            "aether_package_id": int(package_id),
            "account_type": "subscriber",
            "term_months": item.get("term_months", 1),
            "max_connections": product.get("max_connections", 1),
            "is_trial": product.get("is_trial", False),
            "streaming_url": streaming_url,
            "start_date": datetime.utcnow(),
            "expiry_date": expiry_dt,
            "status": "active",
            "created_at": datetime.utcnow(),
        }
        await services_collection.insert_one(service_doc)
        logger.info(f"Aether subscriber provisioned: {api_user} (line {result.get('line_id')}, charged {result.get('charged')})")

        if email_service:
            try:
                await email_service.send_service_activated(
                    customer_email=user["email"],
                    customer_name=user.get("name", "Customer"),
                    service_name=product.get("name", "Aether Service"),
                    username=api_user,
                    password=api_pass,
                    streaming_url=streaming_url,
                    max_connections=product.get("max_connections", 1),
                    expiry_date=expiry_dt.strftime("%Y-%m-%d") if expiry_dt else "N/A",
                    customer_id=order["user_id"]
                )
            except Exception as email_err:
                logger.warning(f"Aether activation email failed: {email_err}")

    except Exception as e:
        logger.error(f"Aether provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def _aether_for_service(service: dict, settings: dict):
    panels = settings.get("aether", {}).get("panels", [])
    idx = safe_panel_index(service.get("panel_index"))
    if idx >= len(panels):
        return None
    return get_aether_service(panels[idx])


@app.post("/api/admin/services/{service_id}/suspend")
async def suspend_service(service_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Suspend a service"""
    service = await services_collection.find_one({"_id": str_to_objectid(service_id)})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    settings = await get_settings()
    panel_type = safe_panel_type(service.get("panel_type"))
    line_user = service.get("xtream_username") or service.get("username", "")

    if panel_type == "aether":
        ae = _aether_for_service(service, settings)
        if not ae:
            raise HTTPException(status_code=500, detail="Aether panel not configured")
        result = await ae.suspend_line(line_user)
    elif panel_type == "xtream":
        xtream_service = get_xtream_service(settings.get("xtream", {}))
        if not xtream_service:
            raise HTTPException(status_code=500, detail="XtreamUI service not configured")
        result = xtream_service.suspend_account(username=line_user, password=service.get("xtream_password", ""))
    else:
        raise HTTPException(status_code=400, detail=f"Suspend via API not supported for panel type '{panel_type}'")

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to suspend"))

    await services_collection.update_one({"_id": service["_id"]}, {"$set": {"status": "suspended"}})
    return {"message": "Service suspended successfully"}

@app.post("/api/admin/services/{service_id}/unsuspend")
async def unsuspend_service(service_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Unsuspend a service"""
    service = await services_collection.find_one({"_id": str_to_objectid(service_id)})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    settings = await get_settings()
    panel_type = safe_panel_type(service.get("panel_type"))
    line_user = service.get("xtream_username") or service.get("username", "")

    if panel_type == "aether":
        ae = _aether_for_service(service, settings)
        if not ae:
            raise HTTPException(status_code=500, detail="Aether panel not configured")
        result = await ae.unsuspend_line(line_user)
    elif panel_type == "xtream":
        xtream_service = get_xtream_service(settings.get("xtream", {}))
        if not xtream_service:
            raise HTTPException(status_code=500, detail="XtreamUI service not configured")
        result = xtream_service.unsuspend_account(username=line_user, password=service.get("xtream_password", ""))
    else:
        raise HTTPException(status_code=400, detail=f"Unsuspend via API not supported for panel type '{panel_type}'")

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to unsuspend"))

    await services_collection.update_one({"_id": service["_id"]}, {"$set": {"status": "active"}})
    return {"message": "Service unsuspended successfully"}

@app.post("/api/admin/services/{service_id}/cancel")
async def cancel_service(service_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Cancel/terminate a service"""
    service = await services_collection.find_one({"_id": str_to_objectid(service_id)})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    settings = await get_settings()
    panel_type = safe_panel_type(service.get("panel_type"))
    line_user = service.get("xtream_username") or service.get("username", "")

    if panel_type == "aether":
        ae = _aether_for_service(service, settings)
        if not ae:
            raise HTTPException(status_code=500, detail="Aether panel not configured")
        result = await ae.suspend_line(line_user)
    elif panel_type == "xtream":
        xtream_service = get_xtream_service(settings.get("xtream", {}))
        if not xtream_service:
            raise HTTPException(status_code=500, detail="XtreamUI service not configured")
        result = xtream_service.terminate_account(username=line_user, password=service.get("xtream_password", ""))
    else:
        raise HTTPException(status_code=400, detail=f"Cancel via API not supported for panel type '{panel_type}'")

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to cancel"))

    await services_collection.update_one({"_id": service["_id"]}, {"$set": {"status": "cancelled"}})
    return {"message": "Service cancelled successfully"}

@app.get("/api/panels/names")
async def get_panel_names():
    """Get panel names (public endpoint for homepage categorization)"""
    settings = await get_settings()
    
    # Get XtreamUI panels
    xtream_panels = settings.get("xtream", {}).get("panels", [])
    panel_info = []
    for i, panel in enumerate(xtream_panels):
        panel_info.append({
            "index": i,
            "name": panel.get("name", f"Server {i + 1}")
        })
    
    # Get XuiOne panels
    xuione_panels = settings.get("xuione", {}).get("panels", [])
    xuione_info = []
    for i, panel in enumerate(xuione_panels):
        xuione_info.append({
            "index": i,
            "name": panel.get("name", f"XuiOne Panel {i + 1}")
        })
    
    # Get 1-Stream panels
    onestream_panels = settings.get("onestream", {}).get("panels", [])
    onestream_info = []
    for i, panel in enumerate(onestream_panels):
        onestream_info.append({
            "index": i,
            "name": panel.get("name", f"1-Stream Panel {i + 1}")
        })

    nxtdash_panels = settings.get("nxtdash", {}).get("panels", [])
    nxtdash_info = []
    for i, panel in enumerate(nxtdash_panels):
        nxtdash_info.append({
            "index": i,
            "name": panel.get("name", f"NXT Dash Panel {i + 1}")
        })

    aether_info = [
        {"index": i, "name": panel.get("name", f"Aether Panel {i + 1}")}
        for i, panel in enumerate(settings.get("aether", {}).get("panels", []))
    ]
    
    return {
        "panels": panel_info,
        "xuione_panels": xuione_info,
        "onestream_panels": onestream_info,
        "nxtdash_panels": nxtdash_info,
        "aether_panels": aether_info
    }

class ManualServiceCreate(BaseModel):
    user_id: str
    product_id: str
    term_months: int = 1

@app.post("/api/admin/services/create-manual")
async def create_manual_service(service_data: ManualServiceCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_admin_user)):
    """Manually create a service for a customer (admin only)"""
    import uuid
    
    # Get user
    user = await users_collection.find_one({"_id": str_to_objectid(service_data.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get product
    product = await products_collection.find_one({"_id": str_to_objectid(service_data.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Create a manual order
    order_dict = {
        "_id": ObjectId(),
        "user_id": service_data.user_id,
        "items": [{
            "product_id": service_data.product_id,
            "product_name": product.get("name"),
            "account_type": product.get("account_type"),
            "term_months": service_data.term_months,
            "price": 0,
            "action_type": "create_new"
        }],
        "subtotal": 0,
        "discount_amount": 0,
        "credits_used": 0,
        "total": 0,
        "status": "paid",
        "payment_method": "manual_admin",
        "created_at": datetime.utcnow(),
        "paid_at": datetime.utcnow()
    }
    
    await orders_collection.insert_one(order_dict)
    order_id = str(order_dict["_id"])
    
    # Provision service in background
    background_tasks.add_task(provision_order_services, order_id, order_dict, user)
    
    return {
        "message": "Service creation initiated. Provisioning in background...",
        "order_id": order_id
    }

@app.get("/api/admin/products")
async def get_all_products_admin(current_user: dict = Depends(get_current_admin_user)):
    """Get all products (admin) sorted by display_order"""
    products = []
    async for product in products_collection.find().sort([("display_order", 1), ("created_at", 1)]):
        product["id"] = str(product["_id"])
        del product["_id"]
        products.append(product)
    return products

@app.post("/api/admin/products")
async def create_product(product: ProductCreate, current_user: dict = Depends(get_current_admin_user)):
    """Create new product"""
    product_dict = product.dict()
    product_dict["created_at"] = datetime.utcnow()
    
    # Auto-assign display_order if not set
    if "display_order" not in product_dict or product_dict["display_order"] is None:
        # Get the max display_order for this panel_index and account_type
        max_order = 0
        async for p in products_collection.find({
            "panel_index": product_dict.get("panel_index", 0),
            "account_type": product_dict.get("account_type", "subscriber")
        }).sort("display_order", -1).limit(1):
            max_order = p.get("display_order", 0)
        
        product_dict["display_order"] = max_order + 1
    
    result = await products_collection.insert_one(product_dict)
    
    # Fetch the created product to return
    created_product = await products_collection.find_one({"_id": result.inserted_id})
    
    # Serialize for JSON response
    created_product["id"] = str(created_product["_id"])
    del created_product["_id"]
    created_product["created_at"] = created_product["created_at"].isoformat()
    
    return created_product

@app.put("/api/admin/products/{product_id}")
async def update_product(product_id: str, product: ProductCreate, 
                        current_user: dict = Depends(get_current_admin_user)):
    """Update product"""
    await products_collection.update_one(
        {"_id": str_to_objectid(product_id)},
        {"$set": product.dict()}
    )
    return {"message": "Product updated successfully"}

@app.delete("/api/admin/products/{product_id}")
async def delete_product(product_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete product"""
    await products_collection.delete_one({"_id": str_to_objectid(product_id)})
    return {"message": "Product deleted successfully"}

@app.post("/api/admin/products/{product_id}/reorder")
async def reorder_product(product_id: str, direction: str = Query(...), current_user: dict = Depends(get_current_admin_user)):
    """Reorder product (move up or down) in the global display list"""
    if direction not in ['up', 'down']:
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")
    
    # Get ALL products sorted by display_order (same as admin page shows)
    all_products = []
    async for p in products_collection.find().sort([("display_order", 1), ("created_at", 1)]):
        all_products.append(p)
    
    # Find current product index
    current_index = next((i for i, p in enumerate(all_products) if str(p["_id"]) == product_id), None)
    if current_index is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Determine swap index
    if direction == 'up' and current_index == 0:
        return {"message": "Already first"}
    if direction == 'down' and current_index == len(all_products) - 1:
        return {"message": "Already last"}
    
    swap_index = current_index - 1 if direction == 'up' else current_index + 1
    
    # Swap display_order values
    cur = all_products[current_index]
    swp = all_products[swap_index]
    cur_order = cur.get("display_order", current_index)
    swp_order = swp.get("display_order", swap_index)
    
    # If they have the same display_order, use their indices instead
    if cur_order == swp_order:
        cur_order = current_index
        swp_order = swap_index
    
    await products_collection.update_one({"_id": cur["_id"]}, {"$set": {"display_order": swp_order}})
    await products_collection.update_one({"_id": swp["_id"]}, {"$set": {"display_order": cur_order}})
    
    return {"message": "Product reordered successfully"}



# ===== AETHER PANEL ROUTES =====

def _get_aether_panel(settings: dict, panel_index: int):
    panels = settings.get("aether", {}).get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="No Aether panels configured")
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found")
    panel = panels[panel_index]
    service = get_aether_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="Aether service not available - check panel_url and api_token")
    return panel, service


@app.post("/api/admin/aether/test")
async def test_aether_connection(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Test connection to an Aether panel (GET /api/v1/me) and report missing scopes"""
    settings = await get_settings()
    _, service = _get_aether_panel(settings, panel_index)
    result = await service.test_connection()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Connection failed"))
    data = result.get("data", {})
    msg = result["message"]
    if data.get("balance") is not None:
        msg += f" — Balance: {data['balance']} credits"
    return {"success": True, "message": msg, "data": data, "missing_scopes": result.get("missing_scopes", [])}


@app.get("/api/admin/aether/packages")
async def get_aether_packages(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch sellable packages (official / trial / extension) from an Aether panel"""
    settings = await get_settings()
    panel, service = _get_aether_panel(settings, panel_index)
    result = await service.get_packages()
    if not result.get("success"):
        raise HTTPException(status_code=429 if result.get("code") == "rate_limited" else 500, detail=result.get("error", "Failed to fetch packages"))
    return {
        "packages": result["packages"],
        "trial_packages": result["trial_packages"],
        "extension_packages": result["extension_packages"],
        "count": len(result["packages"]),
        "trial_count": len(result["trial_packages"]),
        "panel_name": panel.get("name", f"Aether Panel {panel_index + 1}"),
    }


@app.get("/api/admin/aether/packages/{package_id}/bouquets")
async def get_aether_package_bouquets(package_id: int, panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Bouquets offered by one Aether package (with default_included flags)"""
    settings = await get_settings()
    _, service = _get_aether_panel(settings, panel_index)
    result = await service.get_package_bouquets(package_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch bouquets"))
    return {"bouquets": result["bouquets"], "count": len(result["bouquets"])}


@app.get("/api/admin/aether/bouquets")
async def sync_aether_bouquets(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Aggregate bouquets across all packages (real names) and store on the panel settings"""
    settings = await get_settings()
    _, service = _get_aether_panel(settings, panel_index)
    result = await service.get_all_bouquets()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch bouquets"))
    bouquets = [{"id": b["id"], "name": b["name"]} for b in result["bouquets"]]
    await db.settings.update_one({}, {"$set": {f"aether.panels.{panel_index}.bouquets": bouquets}})
    return {"bouquets": bouquets, "count": len(bouquets)}


def _aether_line_to_doc(line: dict, panel_index: int, panel_name: str) -> dict:
    return {
        "panel_index": panel_index,
        "panel_type": "aether",
        "panel_name": panel_name,
        "aether_line_id": str(line.get("id", "")),
        "aether_package_id": line.get("package_id"),
        "username": line.get("username", ""),
        "password": line.get("password", ""),
        "expiry_date": None if line.get("unlimited") else AetherService.parse_exp(line.get("exp_date")),
        "status": AetherService.line_status(line),
        "max_connections": safe_int(line.get("max_connections", 1)),
        "account_type": "subscriber",
        "is_trial": 1 if line.get("trial") else 0,
        "notes": line.get("reseller_notes", ""),
        "last_synced": datetime.utcnow(),
    }


async def _aether_ensure_streaming_url(ae, panel: dict, panel_index: int, lines: list) -> str:
    """Resolve the customer-facing host once per sync and fix services that fell back to the panel URL."""
    streaming_url = panel.get("streaming_url") or ""
    if not streaming_url and lines:
        streaming_url = await ae.resolve_streaming_url(lines[0].get("username", ""))
        if streaming_url and streaming_url != panel.get("resolved_streaming_url"):
            await db.settings.update_one({}, {"$set": {f"aether.panels.{panel_index}.resolved_streaming_url": streaming_url}})
    if streaming_url:
        stale = [panel.get("panel_url", ""), panel.get("panel_url", "").rstrip("/"), ""]
        await services_collection.update_many(
            {"panel_type": "aether", "panel_index": panel_index, "streaming_url": {"$in": stale}},
            {"$set": {"streaming_url": streaming_url}}
        )
    return streaming_url


@app.post("/api/admin/aether/sync-users")
async def sync_aether_users(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync all lines from an Aether panel into imported_users"""
    settings = await get_settings()
    panel, service = _get_aether_panel(settings, panel_index)
    panel_name = panel.get("name", f"Aether Panel {panel_index + 1}")

    result = await service.get_all_lines()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch lines"))

    synced_count = 0
    updated_count = 0
    for line in result.get("lines", []):
        username = line.get("username", "")
        if not username:
            continue
        r = await safe_upsert_imported_user(
            {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
            _aether_line_to_doc(line, panel_index, panel_name),
        )
        if r.upserted_id:
            synced_count += 1
        elif r.modified_count:
            updated_count += 1

    await _aether_ensure_streaming_url(service, panel, panel_index, result.get("lines", []))

    accounts_created = 0
    try:
        unlinked = await imported_users_collection.find({
            "panel_name": panel_name,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": ""}, {"user_id": None}]
        }).to_list(length=10000)
        for iu in unlinked:
            try:
                if await create_customer_for_imported_user(iu):
                    accounts_created += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Aether auto-account creation failed: {e}")

    return {"success": True, "synced": synced_count, "updated": updated_count,
            "total": result.get("total", 0), "accounts_created": accounts_created, "panel_name": panel_name}


# ===== GHOSTSURF VPN ROUTES =====

@app.post("/api/admin/ghostsurf/test")
async def test_ghostsurf_connection(current_user: dict = Depends(get_current_admin_user)):
    """Test GhostSurf VPN API connection"""
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    gs = get_ghostsurf_service(settings, 0)
    if not gs:
        raise HTTPException(status_code=400, detail="GhostSurf panel not configured")
    result = await gs.test_connection()
    if result["success"]:
        balance = result["balance"]
        # Convert cents to dollars if balance is in cents
        credit_cents = balance.get("credit_cents", 0) if isinstance(balance, dict) else 0
        currency = balance.get("currency", "USD") if isinstance(balance, dict) else "USD"
        balance_dollars = credit_cents / 100
        return {"message": f"Connected! Balance: ${balance_dollars:.2f} {currency}, Plans: {result['plans_count']}"}
    raise HTTPException(status_code=400, detail=result["error"])

@app.get("/api/admin/ghostsurf/plans/{panel_index}")
async def get_ghostsurf_plans(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Get available GhostSurf VPN plans"""
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    gs = get_ghostsurf_service(settings, panel_index)
    if not gs:
        raise HTTPException(status_code=400, detail="GhostSurf panel not configured")
    try:
        plans = await gs.get_plans()
        # Normalize plans to match the package format expected by the product form
        packages = []
        for plan in plans:
            plan_id = plan.get("id") or plan.get("slug", "")
            name = plan.get("name", "Unknown Plan")
            months = plan.get("months", 1)
            wholesale_cents = plan.get("wholesale_cents", 0)
            retail_cents = plan.get("retail_cents", 0)
            packages.append({
                "id": plan_id,
                "name": f"{name} ({months} mo) - Wholesale: ${wholesale_cents/100:.2f}, Retail: ${retail_cents/100:.2f}",
                "duration": months,
                "duration_unit": "months",
                "credits": wholesale_cents / 100,
                "max_connections": plan.get("max_devices", 5),
                "is_trial": False,
                "bouquets": [],
                "plan_id": str(plan_id),
            })
        return {"packages": packages, "raw_plans": plans}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/ghostsurf/balance/{panel_index}")
async def get_ghostsurf_balance(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Get GhostSurf reseller balance"""
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    gs = get_ghostsurf_service(settings, panel_index)
    if not gs:
        raise HTTPException(status_code=400, detail="GhostSurf panel not configured")
    try:
        return await gs.get_balance()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/ghostsurf/accounts/{panel_index}")
async def list_ghostsurf_accounts(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """List GhostSurf VPN accounts"""
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    gs = get_ghostsurf_service(settings, panel_index)
    if not gs:
        raise HTTPException(status_code=400, detail="GhostSurf panel not configured")
    try:
        return await gs.list_accounts()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/services/{service_id}/ghostsurf-credentials")
async def get_ghostsurf_service_credentials(service_id: str, current_user: dict = Depends(get_current_user)):
    """Get VPN credentials for a GhostSurf service"""
    user_id = current_user["sub"]
    service = await services_collection.find_one({"_id": str_to_objectid(service_id)})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    if service.get("user_id") != user_id and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if service.get("panel_type") != "ghostsurf":
        raise HTTPException(status_code=400, detail="Not a GhostSurf service")
    
    gs_account_id = service.get("ghostsurf_account_id")
    if not gs_account_id:
        return {"username": service.get("vpn_username", ""), "password": service.get("vpn_password", "")}
    
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    panel_index = service.get("panel_index", 0)
    gs = get_ghostsurf_service(settings, panel_index)
    if not gs:
        return {"username": service.get("vpn_username", ""), "password": service.get("vpn_password", "")}
    
    try:
        creds = await gs.get_credentials(gs_account_id)
        return creds
    except Exception:
        return {"username": service.get("vpn_username", ""), "password": service.get("vpn_password", "")}


@app.post("/api/admin/ghostsurf/sync-users/{panel_index}")
async def sync_ghostsurf_users(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync VPN accounts from GhostSurf into imported users"""
    settings = await get_settings()
    from ghostsurf_service import get_ghostsurf_service
    gs = get_ghostsurf_service(settings, panel_index)
    if not gs:
        raise HTTPException(status_code=400, detail="GhostSurf panel not configured")
    
    gs_panels = settings.get("ghostsurf", {}).get("panels", [])
    panel_name = gs_panels[panel_index].get("name", f"GhostSurf VPN {panel_index + 1}") if panel_index < len(gs_panels) else "GhostSurf"
    
    try:
        accounts = await gs.list_accounts()
        if not isinstance(accounts, list):
            accounts = accounts.get("accounts", accounts.get("data", []))
        
        synced = 0
        updated = 0
        for acct in accounts:
            acct_id = str(acct.get("id") or acct.get("account_id", ""))
            username = acct.get("username", "")
            if not acct_id:
                continue
            
            # Fetch password via credentials endpoint
            password = acct.get("password", "")
            if not password:
                try:
                    creds = await gs.get_credentials(acct_id)
                    password = creds.get("password", "")
                except Exception:
                    pass
            
            expiry_date = None
            expiry_str = acct.get("expires_at") or acct.get("expiry") or acct.get("expiry_date", "")
            if expiry_str:
                for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                    try:
                        expiry_date = datetime.strptime(str(expiry_str).split(".")[0].replace("Z",""), fmt)
                        break
                    except ValueError:
                        continue
            
            status = acct.get("status", "active")
            if expiry_date and expiry_date < datetime.utcnow():
                status = "expired"
            
            plan_name_val = acct.get("plan", {}).get("name", "") if isinstance(acct.get("plan"), dict) else acct.get("plan_name", acct.get("plan", ""))
            
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "ghostsurf",
                "panel_name": panel_name,
                "username": username or acct_id,
                "password": password,
                "expiry_date": expiry_date,
                "status": status,
                "max_connections": acct.get("max_devices", 5),
                "account_type": "subscriber",
                "ghostsurf_account_id": acct_id,
                "ghostsurf_plan_id": acct.get("plan_id") or (acct.get("plan", {}).get("id") if isinstance(acct.get("plan"), dict) else ""),
                "plan_name": plan_name_val,
                "last_synced": datetime.utcnow()
            }
            
            result = await safe_upsert_imported_user(
                {"panel_type": "ghostsurf", "panel_index": panel_index, "ghostsurf_account_id": acct_id},
                user_doc,
            )
            if result.upserted_id:
                synced += 1
            elif result.modified_count:
                updated += 1
        
        # Remove imported users that no longer exist on GhostSurf
        synced_ids = [str(a.get("id") or a.get("account_id", "")) for a in accounts if a.get("id") or a.get("account_id")]
        if synced_ids:
            removed = await imported_users_collection.delete_many({
                "panel_type": "ghostsurf",
                "panel_index": panel_index,
                "ghostsurf_account_id": {"$nin": synced_ids}
            })
            removed_count = removed.deleted_count
        else:
            # If API returned 0 accounts, remove all for this panel
            removed = await imported_users_collection.delete_many({
                "panel_type": "ghostsurf",
                "panel_index": panel_index
            })
            removed_count = removed.deleted_count
        
        return {"success": True, "synced": synced, "updated": updated, "removed": removed_count, "total_accounts": len(accounts), "message": f"Synced {synced} new, updated {updated}, removed {removed_count} from {panel_name}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



async def provision_ghostsurf_service(order_id: str, order: dict, user: dict, item: dict, product: dict, settings: dict, email_service):
    """Provision GhostSurf VPN service"""
    try:
        gs_panels = settings.get("ghostsurf", {}).get("panels", [])
        panel_index = safe_panel_index(product.get("panel_index"))
        
        if not gs_panels or panel_index >= len(gs_panels):
            logger.error(f"GhostSurf panel not configured (index {panel_index}, {len(gs_panels)} panels available)")
            if gs_panels:
                panel_index = 0
            else:
                return
        
        panel = gs_panels[panel_index]
        panel_name = panel.get("name", f"GhostSurf VPN Panel {panel_index + 1}")
        
        from ghostsurf_service import get_ghostsurf_service
        gs = get_ghostsurf_service(settings, panel_index)
        if not gs:
            logger.error("GhostSurf service not available")
            return
        
        # Get plan_id from product
        plan_id = product.get("ghostsurf_plan_id") or product.get("xtream_package_id")
        if not plan_id:
            logger.error(f"No GhostSurf plan_id found on product {product.get('name')}")
            return
        
        plan_id = str(plan_id)
        
        # Check for renewal (extending existing service)
        action_type = item.get("action_type", "new")
        renewal_service_id = item.get("renewal_service_id")
        
        if action_type == "renew" and renewal_service_id:
            existing_service = await services_collection.find_one({"_id": str_to_objectid(renewal_service_id)})
            if existing_service and existing_service.get("ghostsurf_account_id"):
                gs_account_id = existing_service["ghostsurf_account_id"]
                logger.info(f"Renewing GhostSurf account {gs_account_id}")
                try:
                    renew_result = await gs.renew_account(gs_account_id)
                    logger.info(f"GhostSurf renewal result: {renew_result}")
                    
                    # Update service expiry
                    term_months = item.get("term_months", 1)
                    current_expiry = existing_service.get("expiry_date", datetime.utcnow())
                    if isinstance(current_expiry, str):
                        current_expiry = datetime.fromisoformat(current_expiry.replace("Z", "+00:00"))
                    new_expiry = current_expiry + timedelta(days=term_months * 30)
                    
                    await services_collection.update_one(
                        {"_id": str_to_objectid(renewal_service_id)},
                        {"$set": {"expiry_date": new_expiry, "status": "active"}}
                    )
                    logger.info(f"GhostSurf service renewed until {new_expiry}")
                    return
                except Exception as e:
                    logger.error(f"GhostSurf renewal failed: {e}, creating new account instead")
        
        # Create new VPN account
        logger.info(f"Creating GhostSurf account with plan {plan_id}")
        result = await gs.create_account(plan_id)
        logger.info(f"GhostSurf create result: {result}")
        
        # Extract account details
        account_id = str(result.get("id") or result.get("account_id") or result.get("account", {}).get("id", ""))
        username = result.get("username") or result.get("account", {}).get("username", "")
        password = result.get("password") or result.get("account", {}).get("password", "")
        
        term_months = item.get("term_months", 1)
        expiry_date = datetime.utcnow() + timedelta(days=term_months * 30)
        
        # Save service
        service_dict = {
            "user_id": order["user_id"],
            "order_id": order_id,
            "product_id": item["product_id"],
            "product_name": item["product_name"],
            "panel_type": "ghostsurf",
            "panel_index": panel_index,
            "panel_name": panel_name,
            "account_type": "vpn",
            "ghostsurf_account_id": account_id,
            "ghostsurf_plan_id": plan_id,
            "vpn_username": username,
            "vpn_password": password,
            "status": "active",
            "start_date": datetime.utcnow(),
            "expiry_date": expiry_date,
            "term_months": term_months,
            "created_at": datetime.utcnow()
        }
        await services_collection.insert_one(service_dict)
        logger.info(f"GhostSurf VPN service created: account={account_id}, user={username}")
        
        # Send VPN activation email with download links
        if email_service:
            try:
                await email_service.send_vpn_activated(
                    customer_email=user["email"],
                    customer_name=user["name"],
                    service_name=item["product_name"],
                    vpn_username=username,
                    vpn_password=password,
                    expiry_date=expiry_date.strftime("%Y-%m-%d"),
                    max_devices=product.get("max_connections", 5),
                    customer_id=order["user_id"]
                )
            except Exception as e:
                logger.error(f"Failed to send GhostSurf activation email: {e}")
    
    except Exception as e:
        logger.error(f"GhostSurf provisioning error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


# ===== PRODUCT GROUPS =====

@app.get("/api/admin/product-groups")
async def get_product_groups(current_user: dict = Depends(get_current_admin_user)):
    """Get all product groups"""
    settings = await get_settings()
    return settings.get("product_groups", [])


@app.get("/api/product-groups")
async def get_product_groups_public():
    """Get product groups (public)"""
    settings = await get_settings()
    return settings.get("product_groups", [])


@app.put("/api/admin/product-groups")
async def save_product_groups(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Save all product groups (order matters)"""
    groups = data.get("groups", [])
    await db.settings.update_one({}, {"$set": {"product_groups": groups}})
    return {"success": True, "count": len(groups)}


@app.post("/api/admin/products/{product_id}/set-group")
async def set_product_group(product_id: str, data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Assign a product to a group and/or subgroup"""
    update = {}
    if "group_id" in data:
        update["group_id"] = data["group_id"]
    if "subgroup_id" in data:
        update["subgroup_id"] = data["subgroup_id"]
    if update:
        await products_collection.update_one(
            {"_id": str_to_objectid(product_id)},
            {"$set": update}
        )
    return {"success": True}

@app.post("/api/admin/products/fix-display-order")
async def fix_display_order(current_user: dict = Depends(get_current_admin_user)):
    """Fix display_order - assign sequential numbers to all products"""
    all_products = []
    async for p in products_collection.find().sort([("display_order", 1), ("created_at", 1)]):
        all_products.append(p)
    
    for index, product in enumerate(all_products):
        await products_collection.update_one(
            {"_id": product["_id"]},
            {"$set": {"display_order": index}}
        )
    
    return {"message": f"Fixed display_order for {len(all_products)} products"}

@app.get("/api/branding")
async def get_branding():
    """Get branding settings (public - no auth required)"""
    settings = await get_settings()
    branding = settings.get("branding", {
        "site_name": "IPTV Billing",
        "logo_url": "",
        "theme": "light",
        "primary_color": "#2563eb",
        "secondary_color": "#7c3aed",
        "accent_color": "#059669",
        "product_card_color": "#2563eb",
        "hero_background_image": "",
        "hero_title": "Premium IPTV Subscriptions",
        "hero_description": "Stream thousands of channels in HD quality",
        "footer_text": "Premium IPTV Services"
    })
    return branding

@app.get("/api/settings/branding")
async def get_public_branding():
    """Public endpoint - returns branding info for SEO and display"""
    settings = await get_settings()
    branding = settings.get("branding", {})
    return {
        "site_name": branding.get("site_name", ""),
        "tagline": branding.get("tagline", ""),
        "logo_url": branding.get("logo_url", ""),
        "timezone": settings.get("timezone", "UTC"),
    }

@app.get("/api/chatbot/config")
async def get_chatbot_config():
    """Public endpoint - get chatbot widget config if enabled"""
    settings = await get_settings()
    chatbot = settings.get("chatbot", {})
    if chatbot.get("enabled") and chatbot.get("widget_key"):
        return {
            "enabled": True,
            "widget_key": chatbot["widget_key"],
            "api_url": chatbot.get("api_url", "https://banterbot.ai")
        }
    return {"enabled": False}

@app.put("/api/admin/chatbot")
async def update_chatbot_settings(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update only the chatbot settings without touching other settings"""
    await settings_collection.update_one(
        {},
        {"$set": {"chatbot": data}},
        upsert=True
    )
    return {"message": "Chatbot settings updated"}

@app.get("/api/admin/settings")
async def get_admin_settings(current_user: dict = Depends(get_current_admin_user)):
    """Get system settings"""
    settings = await get_settings()
    if "_id" in settings:
        settings["id"] = str(settings["_id"])
        del settings["_id"]
    return settings

@app.get("/api/admin/email-provider")
async def get_email_provider_settings(current_user: dict = Depends(get_current_admin_user)):
    """Get email provider configuration"""
    settings = await get_settings()
    return {
        "email_provider": settings.get("email_provider", "smtp"),
        "email_provider_config": settings.get("email_provider_config", {}),
        "smtp": {
            "host": settings.get("smtp", {}).get("host", ""),
            "port": settings.get("smtp", {}).get("port", 587),
            "from_email": settings.get("smtp", {}).get("from_email", ""),
            "from_name": settings.get("smtp", {}).get("from_name", ""),
        }
    }

@app.put("/api/admin/email-provider")
async def update_email_provider_settings(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update email provider and config"""
    provider = data.get("email_provider", "smtp")
    config = data.get("email_provider_config", {})
    
    await settings_collection.update_one(
        {},
        {"$set": {"email_provider": provider, "email_provider_config": config}},
        upsert=True
    )
    return {"message": f"Email provider updated to {provider}"}

@app.post("/api/admin/email-provider/test")
async def test_email_provider(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Test the email provider by sending a test email"""
    test_email = data.get("test_email", "")
    if not test_email:
        raise HTTPException(status_code=400, detail="test_email is required")
    
    provider = data.get("email_provider", "smtp")
    config = data.get("email_provider_config", {})
    
    if provider == "smtp":
        # Use existing SMTP test
        email_service = await get_configured_email_service()
        if not email_service or not email_service.enabled:
            raise HTTPException(status_code=400, detail="SMTP is not configured")
        site_name = email_service.from_name
        success = await email_service.send_email(
            to_email=test_email,
            subject=f"Test email from {site_name}",
            html_content=email_service._wrap_email(f'<p style="font-size:15px;color:#374151;">Test email from {site_name}. Your email settings are working.</p>', "", test_email),
            text_content=f"Test email from {site_name}. Your email settings are working.",
            email_type="transactional"
        )
    else:
        from email_providers import send_via_provider
        from_email = config.get("from_email", "")
        from_name = config.get("from_name", "")
        if not from_email:
            raise HTTPException(status_code=400, detail="From email is required")
        success = await send_via_provider(
            provider=provider, config=config,
            from_email=from_email, from_name=from_name or "Test",
            to_email=test_email,
            subject=f"Test email from {from_name or provider}",
            html=f'<p style="font-size:15px;color:#374151;">Test email sent via {provider}. Your email settings are working.</p>',
            text=f"Test email sent via {provider}. Your email settings are working."
        )
    
    if success:
        return {"message": f"Test email sent to {test_email} via {provider}"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send via {provider}. Check your API key and settings.")

@app.put("/api/admin/settings")
async def update_admin_settings(settings_update: Settings, 
                               current_user: dict = Depends(get_current_admin_user)):
    """Update system settings"""
    settings_dict = settings_update.dict()
    settings_dict["updated_at"] = datetime.utcnow()
    
    # Never overwrite protected fields via general settings update
    for key in ("license_key", "license_validation", "notifications"):
        settings_dict.pop(key, None)
    
    existing = await settings_collection.find_one()
    if existing:
        # Detect removed panels and clean up their data
        for panel_type_key in ["xtream", "xuione", "onestream", "nxtdash", "ghostsurf", "aether"]:
            old_panels = existing.get(panel_type_key, {}).get("panels", [])
            new_panels = settings_dict.get(panel_type_key, {}).get("panels", [])
            old_names = {p.get("name") for p in old_panels if p.get("name")}
            new_names = {p.get("name") for p in new_panels if p.get("name")}
            removed_names = old_names - new_names
            if removed_names:
                logger.info(f"Panels removed from {panel_type_key}: {removed_names}")
                for panel_name in removed_names:
                    orphaned = await imported_users_collection.find(
                        {"panel_name": panel_name, "panel_type": panel_type_key}
                    ).to_list(length=50000)
                    for iu in orphaned:
                        uid = iu.get("user_id")
                        if uid:
                            await users_collection.delete_one({"_id": str_to_objectid(uid), "created_via": "panel_sync"})
                            await services_collection.delete_many({"user_id": uid, "panel_type": panel_type_key, "panel_name": panel_name})
                    del_result = await imported_users_collection.delete_many(
                        {"panel_name": panel_name, "panel_type": panel_type_key}
                    )
                    logger.info(f"Cleaned up {del_result.deleted_count} imported users for removed panel '{panel_name}'")
        
        await settings_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": settings_dict}
        )
    else:
        await settings_collection.insert_one(settings_dict)
    
    # Reinitialize services with new settings
    get_xtream_service(settings_dict.get("xtream", {}))
    get_email_service(settings_dict.get("smtp", {}))
    
    return {"message": "Settings updated successfully"}

# Exchange rates relative to USD
CURRENCY_RATES = {
    "USD": 1.0,
    "CAD": 1.36,
    "EUR": 0.92,
}
CURRENCY_SYMBOLS = {
    "USD": "$",
    "CAD": "C$",
    "EUR": "\u20ac",
}

@app.get("/api/currency")
async def get_currency():
    """Get current currency setting and available currencies with rates (public)"""
    settings = await get_settings()
    code = settings.get("currency", "USD")
    return {
        "code": code,
        "symbol": CURRENCY_SYMBOLS.get(code, "$"),
        "available": [
            {"code": c, "symbol": CURRENCY_SYMBOLS.get(c, "$"), "rate": r}
            for c, r in CURRENCY_RATES.items()
        ],
        "base_currency": code,
    }

class ChangeCurrencyRequest(BaseModel):
    currency: str

@app.post("/api/admin/currency")
async def change_currency(data: ChangeCurrencyRequest, current_user: dict = Depends(get_current_admin_user)):
    """Change system currency and convert all product prices"""
    new_currency = data.currency.upper()
    if new_currency not in CURRENCY_RATES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency. Choose from: {', '.join(CURRENCY_RATES.keys())}")
    
    settings = await get_settings()
    old_currency = settings.get("currency", "USD")
    
    if old_currency == new_currency:
        return {"message": f"Currency is already {new_currency}"}
    
    # Convert: old -> USD -> new
    old_rate = CURRENCY_RATES[old_currency]
    new_rate = CURRENCY_RATES[new_currency]
    conversion_factor = new_rate / old_rate
    
    # Convert all product prices
    converted = 0
    async for product in products_collection.find({}):
        prices = product.get("prices", {})
        new_prices = {}
        for term, price in prices.items():
            new_prices[term] = round(float(price) * conversion_factor, 2)
        await products_collection.update_one(
            {"_id": product["_id"]},
            {"$set": {"prices": new_prices}}
        )
        converted += 1
    
    # Save currency setting
    await settings_collection.update_one({}, {"$set": {"currency": new_currency}}, upsert=True)
    
    logger.info(f"Currency changed from {old_currency} to {new_currency} (factor: {conversion_factor:.4f}), {converted} products converted")
    
    return {
        "message": f"Currency changed to {new_currency}. {converted} products converted.",
        "old_currency": old_currency,
        "new_currency": new_currency,
        "conversion_factor": round(conversion_factor, 4),
        "products_converted": converted
    }

# ===== NOTIFICATION SETTINGS ENDPOINTS =====

class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    events: dict = {}

class TestTelegramRequest(BaseModel):
    bot_token: str
    chat_id: str

class EmailNotificationSettings(BaseModel):
    enabled: bool = False
    recipient_email: str = ""
    events: dict = {}

DEFAULT_NOTIFICATION_EVENTS = {
    "new_order": True,
    "payment_received": True,
    "new_user": True,
    "service_activated": True,
    "service_expired": False,
    "service_expiry_warning": True,
    "credit_low_alert": True,
    "ticket_created": True,
    "ticket_replied": False
}

@app.get("/api/admin/notifications/settings")
async def get_notification_settings(current_user: dict = Depends(get_current_admin_user)):
    """Get notification settings"""
    settings = await get_settings()
    notifications = settings.get("notifications", {})
    return {
        "telegram": notifications.get("telegram", {
            "enabled": False,
            "bot_token": "",
            "chat_id": "",
            "events": DEFAULT_NOTIFICATION_EVENTS.copy()
        }),
        "email": notifications.get("email", {
            "enabled": False,
            "recipient_email": settings.get("support_email", ""),
            "events": DEFAULT_NOTIFICATION_EVENTS.copy()
        }),
        "sms": notifications.get("sms", {
            "enabled": False,
            "provider": "twilio",
            "admin_phone": "",
            "config": {},
            "events": DEFAULT_NOTIFICATION_EVENTS.copy()
        })
    }

@app.put("/api/admin/notifications/telegram")
async def update_telegram_settings(telegram: TelegramSettings, current_user: dict = Depends(get_current_admin_user)):
    """Update Telegram notification settings"""
    settings = await get_settings()
    
    if "notifications" not in settings:
        settings["notifications"] = {}
    
    settings["notifications"]["telegram"] = telegram.dict()
    
    await settings_collection.update_one(
        {},
        {"$set": {"notifications": settings["notifications"]}},
        upsert=True
    )
    
    return {"message": "Telegram settings updated successfully"}

@app.post("/api/admin/notifications/telegram/test")
async def test_telegram_notification(request: TestTelegramRequest, current_user: dict = Depends(get_current_admin_user)):
    """Send a test message to verify Telegram settings"""
    import httpx
    
    if not request.bot_token or not request.chat_id:
        raise HTTPException(status_code=400, detail="Bot token and chat ID are required")
    
    try:
        # Get branding for site name
        settings = await get_settings()
        site_name = settings.get("branding", {}).get("site_name", "IPTV Billing")
        
        message = f"🔔 *Test Notification*\n\nThis is a test message from {site_name}.\n\nYour Telegram notifications are configured correctly! ✅"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{request.bot_token}/sendMessage",
                json={
                    "chat_id": request.chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=10.0
            )
            
            result = response.json()
            
            if response.status_code == 200 and result.get("ok"):
                return {"message": "Test message sent successfully!"}
            else:
                # Get the actual error from Telegram
                error_desc = result.get('description', f'HTTP {response.status_code}')
                
                # Provide helpful messages for common errors
                if response.status_code == 401 or "Unauthorized" in error_desc:
                    raise HTTPException(status_code=400, detail="Invalid bot token. Please check your token from @BotFather.")
                elif "chat not found" in error_desc.lower():
                    raise HTTPException(status_code=400, detail="Chat not found. Please check your Chat ID.")
                elif "bot was blocked" in error_desc.lower():
                    raise HTTPException(status_code=400, detail="Bot was blocked by user. Please unblock the bot and try again.")
                elif "chat_id is empty" in error_desc.lower():
                    raise HTTPException(status_code=400, detail="Chat ID cannot be empty.")
                elif "CHAT_WRITE_FORBIDDEN" in error_desc:
                    raise HTTPException(status_code=400, detail="Bot doesn't have permission to send messages. Make sure you've started a conversation with the bot first (send /start to your bot).")
                else:
                    raise HTTPException(status_code=400, detail=f"Telegram error: {error_desc}")
                
    except httpx.TimeoutException:
        raise HTTPException(status_code=500, detail="Request timed out. Please check your internet connection.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test message: {str(e)}")

@app.put("/api/admin/notifications/email")
async def update_email_notification_settings(email_settings: EmailNotificationSettings, current_user: dict = Depends(get_current_admin_user)):
    """Update email notification settings"""
    settings = await get_settings()
    if "notifications" not in settings:
        settings["notifications"] = {}
    settings["notifications"]["email"] = email_settings.dict()
    await settings_collection.update_one(
        {},
        {"$set": {"notifications": settings["notifications"]}},
        upsert=True
    )
    return {"message": "Email notification settings updated successfully"}

@app.post("/api/admin/notifications/email/test")
async def test_email_notification_endpoint(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Send a test email notification"""
    recipient = data.get("recipient_email", "")
    if not recipient:
        raise HTTPException(status_code=400, detail="Recipient email is required")
    try:
        email_service = await get_configured_email_service()
        if not email_service or not email_service.enabled:
            raise HTTPException(status_code=400, detail="SMTP is not configured. Please set up SMTP in Email Settings first.")
        settings = await get_settings()
        site_name = email_service.from_name
        subject = f"Test notification from {site_name}"
        html_body = f"""<p style="font-size: 15px; color: #374151; line-height: 1.6;">This is a test notification from <strong>{site_name}</strong>.</p>
<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your admin email notifications are configured correctly.</p>"""
        text_body = f"This is a test notification from {site_name}.\n\nYour admin email notifications are configured correctly."
        result = await email_service.send_email(
            to_email=recipient,
            subject=subject,
            html_content=email_service._wrap_email(html_body, subject, recipient, "transactional"),
            text_content=text_body,
            email_type="transactional"
        )
        if result:
            return {"message": "Test email sent successfully!"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send test email. Please check your SMTP settings and server logs for details.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")

@app.put("/api/admin/notifications/sms")
async def update_sms_notification_settings(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update SMS notification settings"""
    settings = await get_settings()
    if "notifications" not in settings:
        settings["notifications"] = {}
    settings["notifications"]["sms"] = data
    await settings_collection.update_one(
        {},
        {"$set": {"notifications": settings["notifications"]}},
        upsert=True
    )
    return {"message": "SMS notification settings updated successfully"}

@app.post("/api/admin/notifications/sms/test")
async def test_sms_notification(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Send a test SMS notification"""
    phone = data.get("phone", "")
    provider = data.get("provider", "")
    config = data.get("config", {})
    if not phone or not provider:
        raise HTTPException(status_code=400, detail="Phone number and provider are required")
    try:
        from sms_providers import send_sms
        settings = await get_settings()
        site_name = settings.get("branding", {}).get("site_name", "Billing System")
        result = await send_sms(provider, config, phone, f"Test notification from {site_name}. SMS notifications are working.")
        if result:
            return {"message": f"Test SMS sent to {phone}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send test SMS. Check your provider credentials.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SMS test failed: {str(e)}")

# Helper function to send Telegram notifications
async def send_telegram_notification(event_type: str, message: str):
    """Send a Telegram notification if enabled for the event type"""
    try:
        settings = await get_settings()
        telegram = settings.get("notifications", {}).get("telegram", {})
        
        if not telegram.get("enabled"):
            return False
        
        events = telegram.get("events", {})
        if not events.get(event_type, False):
            return False
        
        bot_token = telegram.get("bot_token", "")
        chat_id = telegram.get("chat_id", "")
        
        if not bot_token or not chat_id:
            return False
        
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=10.0
            )
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {str(e)}")
        return False

# Helper function to send admin email notifications
async def send_email_notification(event_type: str, subject: str, message: str):
    """Send an admin email notification if enabled for the event type"""
    try:
        settings = await get_settings()
        email_notif = settings.get("notifications", {}).get("email", {})
        
        if not email_notif.get("enabled"):
            return False
        
        events = email_notif.get("events", {})
        if not events.get(event_type, False):
            return False
        
        recipient = email_notif.get("recipient_email", "")
        if not recipient:
            return False
        
        email_service = await get_configured_email_service()
        if not email_service or not email_service.enabled:
            return False
        
        site_name = email_service.from_name
        html_body = f"""<p style="font-size: 15px; color: #374151; line-height: 1.6; white-space: pre-wrap;">{message}</p>"""
        wrapped = email_service._wrap_email(html_body, subject, recipient, "transactional")
        
        return await email_service.send_email(
            to_email=recipient,
            subject=f"[{site_name}] {subject}",
            html_content=wrapped,
            text_content=message,
            email_type="transactional"
        )
    except Exception as e:
        logger.error(f"Failed to send admin email notification: {str(e)}")
        return False

# Helper function to send SMS notifications
async def send_sms_notification(event_type: str, message: str):
    """Send an admin SMS notification if enabled for the event type"""
    try:
        settings = await get_settings()
        sms_settings = settings.get("notifications", {}).get("sms", {})
        
        if not sms_settings.get("enabled"):
            return False
        
        events = sms_settings.get("events", {})
        if not events.get(event_type, False):
            return False
        
        admin_phone = sms_settings.get("admin_phone", "")
        provider = sms_settings.get("provider", "")
        config = sms_settings.get("config", {})
        
        if not admin_phone or not provider:
            return False
        
        from sms_providers import send_sms
        return await send_sms(provider, config, admin_phone, message)
    except Exception as e:
        logger.error(f"Failed to send SMS notification: {str(e)}")
        return False

# ===== XUIONE PANEL ENDPOINTS =====

from xuione_service import XuiOneService, get_xuione_service

@app.post("/api/admin/xuione/test")
async def test_xuione_connection(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Test XuiOne panel connection"""
    settings = await get_settings()
    panels = settings.get("xuione", {}).get("panels", [])
    
    if not panels:
        raise HTTPException(status_code=400, detail="No XuiOne panels configured. Please add a panel first.")
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found")
    
    panel = panels[panel_index]
    logger.info(f"Testing XuiOne panel: {panel.get('name', 'Unknown')}")
    logger.info(f"Panel URL: {panel.get('panel_url', 'Not set')}")
    
    try:
        service = get_xuione_service(panel)
        
        if not service:
            logger.error("Failed to create XuiOne service instance")
            raise HTTPException(status_code=500, detail="Failed to initialize XuiOne service. Check panel configuration.")
        
        result = service.test_connection()
        
        if result.get("success"):
            logger.info(f"✓ XuiOne connection test successful")
            return {"message": result.get("message", "Connection successful")}
        else:
            error_msg = result.get("error", "Connection failed")
            logger.error(f"✗ XuiOne connection test failed: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ XuiOne test connection exception: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Connection test error: {str(e)}")

@app.get("/api/admin/xuione/sync-packages")
async def sync_xuione_packages(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync packages from XuiOne panel - Returns package list for selection, does NOT create products"""
    settings = await get_settings()
    panels = settings.get("xuione", {}).get("panels", [])
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    
    panel = panels[panel_index]
    panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
    
    service = get_xuione_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="XuiOne service not available")
    
    result = service.get_packages()
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch packages"))
    
    packages = result.get("packages", [])
    
    # Separate regular and trial packages
    regular_packages = [p for p in packages if not p.get('is_trial')]
    trial_packages = [p for p in packages if p.get('is_trial')]
    
    # Return packages for selection in the product form (DO NOT create products automatically)
    return {
        "success": True,
        "packages": regular_packages,
        "trial_packages": trial_packages,
        "all_packages": packages,
        "count": len(regular_packages),
        "trial_count": len(trial_packages),
        "total_count": len(packages),
        "panel_name": panel_name,
        "panel_index": panel_index
    }

@app.get("/api/admin/xuione/sync-bouquets")
async def sync_xuione_bouquets(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync bouquets from XuiOne panel"""
    settings = await get_settings()
    panels = settings.get("xuione", {}).get("panels", [])
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    
    panel = panels[panel_index]
    panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
    
    service = get_xuione_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="XuiOne service not available")
    
    result = service.get_bouquets()
    
    if not result.get("success"):
        return {
            "success": False,
            "warning": result.get("error", "Could not fetch bouquets from this panel"),
            "bouquets": [],
            "count": 0,
            "panel_name": panel_name
        }
    
    bouquets = result.get("bouquets", [])
    
    # Store bouquets in settings
    if "xuione" not in settings:
        settings["xuione"] = {}
    if "panels" not in settings["xuione"]:
        settings["xuione"]["panels"] = panels
    
    # Update panel with bouquets
    settings["xuione"]["panels"][panel_index]["bouquets"] = bouquets
    
    await settings_collection.update_one(
        {},
        {"$set": {"xuione": settings["xuione"]}},
        upsert=True
    )
    
    return {
        "message": f"Synced {len(bouquets)} bouquets from {panel_name}",
        "bouquets": bouquets,
        "panel_name": panel_name
    }

@app.post("/api/admin/xuione/sync-users")
async def sync_xuione_users(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync users from XuiOne panel to billing system (1:1 mirror)"""
    settings = await get_settings()
    panels = settings.get("xuione", {}).get("panels", [])
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    
    panel = panels[panel_index]
    panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
    
    service = get_xuione_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="XuiOne service not available")
    
    synced_count = 0
    updated_count = 0
    removed_count = 0
    total_users = 0
    
    xuione_subscriber_usernames = set()
    xuione_reseller_usernames = set()
    
    # Sync subscribers
    result = service.get_users()
    
    if result.get("success"):
        users_data = result.get("users", [])
        total_users += len(users_data)
        
        for user_data in users_data:
            username = user_data.get("username", "")
            if not username:
                continue
            
            xuione_subscriber_usernames.add(username)
            
            expiry_str = user_data.get("expiry", "")
            expiry_date = None
            if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                # Try epoch timestamp first
                try:
                    _epoch = int(str(expiry_str).strip())
                    if _epoch > 0:
                        expiry_date = datetime.utcfromtimestamp(_epoch)
                except (ValueError, TypeError, OSError):
                    pass
                if not expiry_date:
                    date_formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
                    for fmt in date_formats:
                        try:
                            expiry_date = datetime.strptime(expiry_str.strip(), fmt)
                            break
                        except ValueError:
                            continue
            
            status = "active"
            if expiry_date and expiry_date < datetime.utcnow():
                status = "expired"
            
            user_doc = {
                "panel_index": panel_index,
                "panel_name": panel_name,
                "panel_type": "xuione",
                "username": username,
                "password": user_data.get("password", ""),
                "expiry_date": expiry_date,
                "status": status,
                "max_connections": safe_int(user_data.get("max_connections", 1)),
                "account_type": "subscriber",
                "xtream_user_id": user_data.get("user_id", 0),
                "last_synced": datetime.utcnow()
            }
            
            result_up = await safe_upsert_imported_user(
                {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                {**user_doc, "created_at": user_doc.get("created_at", datetime.utcnow())}
            )
            if result_up.upserted_id:
                synced_count += 1
            elif result_up.modified_count:
                updated_count += 1
    # Sync subresellers
    reseller_result = service.get_subresellers()
    reseller_synced = 0
    reseller_updated = 0
    
    if reseller_result.get("success"):
        resellers_data = reseller_result.get("users", [])
        total_users += len(resellers_data)
        
        for reseller_data in resellers_data:
            username = reseller_data.get("username", "")
            if not username:
                continue
            
            xuione_reseller_usernames.add(username)
            
            expiry_str = reseller_data.get("expiry", "NEVER")
            expiry_date = None
            if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                # Try epoch timestamp first
                try:
                    _epoch = int(str(expiry_str).strip())
                    if _epoch > 0:
                        expiry_date = datetime.utcfromtimestamp(_epoch)
                except (ValueError, TypeError, OSError):
                    pass
                if not expiry_date:
                    date_formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
                    for fmt in date_formats:
                        try:
                            expiry_date = datetime.strptime(expiry_str.strip(), fmt)
                            break
                        except ValueError:
                            continue
            
            reseller_doc = {
                "panel_index": panel_index,
                "panel_name": panel_name,
                "panel_type": "xuione",
                "username": username,
                "password": "",
                "expiry_date": expiry_date,
                "status": "active",
                "credits": float(reseller_data.get("credits", 0) or 0),
                "member_group": reseller_data.get("member_group", ""),
                "owner": reseller_data.get("owner", ""),
                "account_type": "reseller",
                "xtream_user_id": reseller_data.get("user_id", 0),
                "last_synced": datetime.utcnow()
            }
            
            result_up = await safe_upsert_imported_user(
                {"username": username, "panel_name": panel_name, "account_type": "reseller"},
                reseller_doc,
            )
            if result_up.upserted_id:
                reseller_synced += 1
                synced_count += 1
            elif result_up.modified_count:
                reseller_updated += 1
                updated_count += 1
    
    # Cleanup stale users
    if xuione_subscriber_usernames:
        stale = await imported_users_collection.find({
            "panel_index": panel_index,
            "panel_type": "xuione",
            "account_type": "subscriber",
            "username": {"$nin": list(xuione_subscriber_usernames)}
        }).to_list(None)
        if stale:
            await imported_users_collection.delete_many({"_id": {"$in": [s["_id"] for s in stale]}})
            removed_count += len(stale)
    
    stale_resellers = await imported_users_collection.find({
        "panel_index": panel_index,
        "panel_type": "xuione",
        "account_type": "reseller",
        "username": {"$nin": list(xuione_reseller_usernames)}
    }).to_list(None)
    if stale_resellers:
        await imported_users_collection.delete_many({"_id": {"$in": [s["_id"] for s in stale_resellers]}})
        removed_count += len(stale_resellers)
    
    # Auto-create customer accounts for newly synced XuiOne users
    accounts_created = 0
    try:
        unlinked_list = await imported_users_collection.find({
            "panel_name": panel_name,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": ""}, {"user_id": None}]
        }).to_list(length=10000)
        for iu in unlinked_list:
            try:
                uid = await create_customer_for_imported_user(iu)
                if uid:
                    accounts_created += 1
            except Exception:
                pass
        if accounts_created > 0:
            logger.info(f"Auto-created {accounts_created} customer accounts from {panel_name} sync")
    except Exception as e:
        logger.warning(f"Account creation after XuiOne sync failed: {e}")
    
    return {
        "success": True,
        "synced": synced_count,
        "updated": updated_count,
        "removed": removed_count,
        "total": total_users,
        "accounts_created": accounts_created,
        "panel_name": panel_name
    }

# ===== 1-STREAM PANEL ENDPOINTS =====

@app.post("/api/admin/onestream/test")
async def test_onestream_connection(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Test connection to 1-Stream panel"""
    settings = await get_settings()
    panels = settings.get("onestream", {}).get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="No 1-Stream panels configured")
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found")
    panel = panels[panel_index]
    service = get_onestream_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="1-Stream service not available - check panel_url, api_key and auth_user_token")
    result = service.test_connection()
    if result.get("success"):
        return {"success": True, "message": f"Connected! User: {result.get('name')}, Credits: {result.get('credits')}"}
    raise HTTPException(status_code=500, detail=result.get("error", "Connection failed"))

@app.get("/api/admin/onestream/packages")
async def sync_onestream_packages(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch packages from 1-Stream panel"""
    settings = await get_settings()
    panels = settings.get("onestream", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    service = get_onestream_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="1-Stream service not available")
    result = service.get_packages()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch packages"))
    return {
        "packages": result["packages"],
        "trial_packages": result.get("trial_packages", []),
        "count": result["count"],
        "trial_count": result.get("trial_count", 0),
        "panel_name": panel.get("name", f"1-Stream Panel {panel_index + 1}")
    }

@app.get("/api/admin/onestream/bouquets")
async def sync_onestream_bouquets(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch bouquets from 1-Stream panel"""
    settings = await get_settings()
    panels = settings.get("onestream", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    service = get_onestream_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="1-Stream service not available")
    result = service.get_bouquets()
    if not result.get("success"):
        # Bouquets endpoint may require extra permissions - try extracting from packages instead
        logger.warning(f"Bouquets endpoint failed: {result.get('error')}. Trying to extract from packages...")
        pkg_result = service.get_packages()
        if pkg_result.get("success"):
            bouquet_ids = set()
            for pkg in pkg_result.get("packages", []) + pkg_result.get("trial_packages", []):
                for b_id in pkg.get("bouquets", []):
                    bouquet_ids.add(b_id)
            bouquets = [{"id": b_id, "name": f"Bouquet {b_id}"} for b_id in sorted(bouquet_ids)]
            result = {"success": True, "bouquets": bouquets}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to fetch bouquets. Check API token permissions."))
    # Store bouquets in settings
    if "onestream" not in settings:
        settings["onestream"] = {"panels": panels}
    settings["onestream"]["panels"][panel_index]["bouquets"] = result["bouquets"]
    await db.settings.update_one({}, {"$set": {"onestream": settings["onestream"]}})
    return {"bouquets": result["bouquets"], "count": len(result["bouquets"])}

@app.post("/api/admin/onestream/sync-users")
async def sync_onestream_users(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync users from 1-Stream panel"""
    settings = await get_settings()
    panels = settings.get("onestream", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    panel_name = panel.get("name", f"1-Stream Panel {panel_index + 1}")
    service = get_onestream_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="1-Stream service not available")

    synced_count = 0
    updated_count = 0

    # Get the reseller's username to filter direct lines only
    reseller_username = panel.get("admin_username", "").strip()

    # Sync lines (subscribers) — only direct lines owned by this reseller
    lines_result = service.get_lines()
    if lines_result.get("success"):
        for line in lines_result.get("users", []):
            username = line.get("username", "")
            if not username:
                continue
            # Filter: only import lines directly owned by this reseller
            line_owner = line.get("owner", "").strip()
            if reseller_username and line_owner and line_owner != reseller_username:
                continue
            existing = await imported_users_collection.find_one({
                "panel_index": panel_index, "panel_type": "onestream",
                "username": username, "account_type": "subscriber"
            })
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "onestream",
                "panel_name": panel_name,
                "onestream_line_id": line.get("line_id", ""),
                "username": username,
                "password": line.get("password", ""),
                "expiry_date": line.get("expiry_date"),
                "status": line.get("status", "active"),
                "max_connections": line.get("max_connections", 1),
                "account_type": "subscriber",
                "owner": line.get("owner", ""),
                "last_synced": datetime.utcnow()
            }
            if existing:
                await imported_users_collection.update_one({"_id": existing["_id"]}, {"$set": user_doc})
                updated_count += 1
            else:
                try:
                    await safe_upsert_imported_user(
                        {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                        user_doc,
                            )
                    synced_count += 1
                except Exception:
                    await imported_users_collection.update_one(
                        {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                        {"$set": user_doc}
                        )
                    updated_count += 1
    # Sync sub-resellers
    resellers_result = service.get_subresellers()
    if resellers_result.get("success"):
        for reseller in resellers_result.get("users", []):
            username = reseller.get("username", "")
            if not username:
                continue
            existing = await imported_users_collection.find_one({
                "panel_index": panel_index, "panel_type": "onestream",
                "username": username, "account_type": "reseller"
            })
            reseller_doc = {
                "panel_index": panel_index,
                "panel_type": "onestream",
                "panel_name": panel_name,
                "onestream_user_id": reseller.get("user_id", 0),
                "username": username,
                "password": "",
                "credits": float(reseller.get("credits", 0) or 0),
                "status": "active",
                "account_type": "reseller",
                "last_synced": datetime.utcnow()
            }
            if existing:
                await imported_users_collection.update_one({"_id": existing["_id"]}, {"$set": reseller_doc})
                updated_count += 1
            else:
                try:
                    await safe_upsert_imported_user(
                        {"username": username, "panel_name": panel_name, "account_type": "reseller"},
                        reseller_doc,
                            )
                    synced_count += 1
                except Exception:
                    await imported_users_collection.update_one(
                        {"username": username, "panel_name": panel_name, "account_type": "reseller"},
                        {"$set": reseller_doc}
                        )
                    updated_count += 1
    
    # Auto-create customer accounts for newly synced 1-Stream users
    accounts_created = 0
    try:
        unlinked_list = await imported_users_collection.find({
            "panel_name": panel_name,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": ""}, {"user_id": None}]
        }).to_list(length=10000)
        for iu in unlinked_list:
            try:
                uid = await create_customer_for_imported_user(iu)
                if uid:
                    accounts_created += 1
            except Exception:
                pass
        if accounts_created > 0:
            logger.info(f"Auto-created {accounts_created} customer accounts from {panel_name} sync")
    except Exception as e:
        logger.warning(f"Account creation after 1-Stream sync failed: {e}")
    
    return {"success": True, "synced": synced_count, "updated": updated_count, "accounts_created": accounts_created, "panel_name": panel_name}

# ===== NXT DASH PANEL ROUTES =====

@app.post("/api/admin/nxtdash/test")
async def test_nxtdash_connection(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Test connection to NXT Dash panel"""
    settings = await get_settings()
    panels = settings.get("nxtdash", {}).get("panels", [])
    if not panels:
        raise HTTPException(status_code=400, detail="No NXT Dash panels configured")
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found")
    panel = panels[panel_index]
    service = get_nxtdash_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="NXT Dash service not available - check panel_url, token, username and password")
    result = await service.test_connection()
    if result.get("success"):
        data = result.get("data", {})
        credits = data.get("credits", "N/A")
        return {"success": True, "message": f"Connected! Credits: {credits}", "data": data}
    raise HTTPException(status_code=500, detail=result.get("error", "Connection failed"))


@app.get("/api/admin/nxtdash/packages")
async def get_nxtdash_packages(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch packages from NXT Dash panel"""
    settings = await get_settings()
    panels = settings.get("nxtdash", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    service = get_nxtdash_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="NXT Dash service not available")

    regular = await service.get_packages(trial=False)
    trial = await service.get_packages(trial=True)

    return {
        "packages": regular.get("packages", []),
        "trial_packages": trial.get("packages", []),
        "count": len(regular.get("packages", [])),
        "trial_count": len(trial.get("packages", [])),
        "panel_name": panel.get("name", f"NXT Dash Panel {panel_index + 1}")
    }


@app.get("/api/admin/nxtdash/bouquets")
async def get_nxtdash_bouquets(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Extract bouquets from NXT Dash lines data and store in panel settings."""
    settings = await get_settings()
    panels = settings.get("nxtdash", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    service = get_nxtdash_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="NXT Dash service not available")

    # Get existing custom names (handle both int and string keys)
    existing_bouquets = {}
    for b in panel.get("bouquets", []):
        existing_bouquets[int(b.get("id", 0))] = b.get("name", "")

    # Extract unique bouquet IDs from lines data
    all_bouquet_ids = set()
    result = await service.get_lines()
    if result.get("success"):
        for line in result.get("lines", []):
            bouquet_raw = line.get("bouquet", "[]")
            if isinstance(bouquet_raw, str):
                import ast
                try:
                    bouquet_ids = ast.literal_eval(bouquet_raw)
                except Exception:
                    bouquet_ids = []
            elif isinstance(bouquet_raw, list):
                bouquet_ids = bouquet_raw
            else:
                bouquet_ids = []
            for bid in bouquet_ids:
                all_bouquet_ids.add(int(bid))

    # Build bouquets list preserving any custom names
    bouquets = []
    for bid in sorted(all_bouquet_ids):
        existing_name = existing_bouquets.get(bid, "")
        # Only use default if no custom name exists or name is still the generic default
        name = existing_name if existing_name and not existing_name.startswith("Bouquet ") else existing_name or f"Bouquet {bid}"
        bouquets.append({"id": bid, "name": name})

    # Save bouquets to panel settings
    panels[panel_index]["bouquets"] = bouquets
    await db.settings.update_one({}, {"$set": {f"nxtdash.panels.{panel_index}.bouquets": bouquets}})

    return {"bouquets": bouquets, "count": len(bouquets)}


@app.put("/api/admin/nxtdash/bouquets")
async def update_nxtdash_bouquet_names(data: dict, panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Update bouquet names for a NXT Dash panel."""
    settings = await get_settings()
    panels = settings.get("nxtdash", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    bouquets = data.get("bouquets", [])
    await db.settings.update_one({}, {"$set": {f"nxtdash.panels.{panel_index}.bouquets": bouquets}})
    return {"success": True, "count": len(bouquets)}


@app.post("/api/admin/nxtdash/sync-users")
async def sync_nxtdash_users(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync all subscriber lines from NXT Dash panel."""
    settings = await get_settings()
    panels = settings.get("nxtdash", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    panel_name = panel.get("name", f"NXT Dash Panel {panel_index + 1}")
    service = get_nxtdash_service(panel)
    if not service:
        raise HTTPException(status_code=500, detail="NXT Dash service not available")

    synced_count = 0
    updated_count = 0

    # Paginate through all lines
    page = 1
    while True:
        result = await service.get_lines(page=page)
        if not result.get("success"):
            break
        lines = result.get("lines", [])
        if not lines:
            break

        for line in lines:
            username = line.get("username", "")
            if not username:
                continue

            expire_ts = line.get("expire_date")
            expiry_str = ""
            if expire_ts:
                try:
                    from datetime import timezone
                    expiry_str = datetime.fromtimestamp(int(expire_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    expiry_str = line.get("exp_date", "")

            user_doc = {
                "panel_index": panel_index,
                "panel_type": "nxtdash",
                "panel_name": panel_name,
                "nxtdash_line_id": str(line.get("id", "")),
                "username": username,
                "password": line.get("password", ""),
                "expiry_date": expiry_str,
                "status": "active" if line.get("enabled") == 1 and line.get("admin_enabled") == 1 else "disabled",
                "max_connections": line.get("user_connection", 1),
                "account_type": "subscriber",
                "is_trial": line.get("is_trial", 0),
                "owner": line.get("owner", ""),
                "last_synced": datetime.utcnow(),
            }

            try:
                result_db = await safe_upsert_imported_user(
                    {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                    user_doc,
                    )
                if result_db.upserted_id:
                    synced_count += 1
                else:
                    updated_count += 1
            except Exception:
                await imported_users_collection.update_one(
                    {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                    {"$set": user_doc},
                )
                updated_count += 1

        last_page = result.get("last_page", 1)
        if page >= last_page:
            break
        page += 1

    # Auto-create customer accounts for newly synced NXT Dash users
    accounts_created = 0
    try:
        unlinked_list = await imported_users_collection.find({
            "panel_name": panel_name,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": ""}, {"user_id": None}]
        }).to_list(length=10000)
        for iu in unlinked_list:
            try:
                uid = await create_customer_for_imported_user(iu)
                if uid:
                    accounts_created += 1
            except Exception:
                pass
        if accounts_created > 0:
            logger.info(f"Auto-created {accounts_created} customer accounts from {panel_name} sync")
    except Exception as e:
        logger.warning(f"Account creation after NXT Dash sync failed: {e}")

    return {"success": True, "synced": synced_count, "updated": updated_count, "accounts_created": accounts_created, "panel_name": panel_name}


# ===== EMAIL MANAGEMENT ENDPOINTS =====

class TestEmailRequest(BaseModel):
    email: str

class MassEmailRequest(BaseModel):
    subject: str
    content: str
    recipient_filter: str = "all"  # all, active, inactive

@app.post("/api/admin/email/test")
async def send_test_email(request: TestEmailRequest, current_user: dict = Depends(get_current_admin_user)):
    """Send a test email to verify SMTP settings"""
    email_service = await get_configured_email_service()
    
    if not email_service or not email_service.enabled:
        raise HTTPException(status_code=400, detail="SMTP is not configured. Please configure SMTP settings first.")
    
    site_name = email_service.from_name
    test_html = f"""<p style="font-size: 15px; color: #374151; line-height: 1.6;">This is a test email from {site_name}.</p>
<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your email settings are configured correctly.</p>"""
    test_text = f"This is a test email from {site_name}.\n\nYour email settings are configured correctly."
    
    try:
        success = await email_service.send_email(
            to_email=request.email,
            subject=f"Test email from {site_name}",
            html_content=email_service._wrap_email(test_html, "", request.email, "transactional"),
            text_content=test_text,
            email_type="transactional"
        )
        
        if success:
            return {"message": f"Test email sent successfully to {request.email}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to send test email. Please check your SMTP settings and server logs for details.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test email error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")

@app.post("/api/admin/email/mass")
async def send_mass_email(request: MassEmailRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_admin_user)):
    """Send mass email to customers"""
    email_service = await get_configured_email_service()
    
    if not email_service or not email_service.enabled:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    
    # Get recipients based on filter
    query = {"role": "user"}
    # CMTV local change 2026-09-23: skip placeholder addresses of panel-imported accounts (they can't receive mail)
    query["email"] = {"$not": {"$regex": r"@panel\.local$", "$options": "i"}}
    
    if request.recipient_filter == "active":
        # Users with active services
        active_user_ids = await db.services.distinct("user_id", {"status": "active"})
        query["_id"] = {"$in": [str_to_objectid(uid) for uid in active_user_ids]}
    elif request.recipient_filter == "inactive":
        # Users without active services
        active_user_ids = await db.services.distinct("user_id", {"status": "active"})
        query["_id"] = {"$nin": [str_to_objectid(uid) for uid in active_user_ids]}
    
    recipients = []
    async for user in users_collection.find(query):
        recipients.append({
            "email": user["email"],
            "name": user["name"],
            "customer_id": str(user["_id"])
        })
    
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipients found matching the filter")
    
    # Send emails in background (wrapping will happen per-recipient in send_bulk_email)
    async def send_emails_task():
        results = await email_service.send_bulk_email(
            recipients, 
            request.subject,
            request.content,  # Raw content, will be wrapped and personalized per recipient
            email_type="marketing",
            sent_by=current_user["sub"]
        )
        logger.info(f"Mass email completed: {results['sent']} sent, {results['failed']} failed")
        
        # Result is already logged by email_service per email
    
    background_tasks.add_task(send_emails_task)
    
    return {
        "message": f"Mass email queued for {len(recipients)} recipients",
        "recipient_count": len(recipients)
    }

@app.get("/api/admin/email/logs")
async def get_email_logs(current_user: dict = Depends(get_current_admin_user)):
    """Get mass email logs"""
    logs = []
    async for log in db.email_logs.find().sort("created_at", -1).limit(50):
        log["id"] = str(log["_id"])
        del log["_id"]
        logs.append(log)
    return logs

# ===== EMAIL TEMPLATE ENDPOINTS =====

@app.get("/api/admin/email/templates")
async def get_email_templates(current_user: dict = Depends(get_current_admin_user)):
    """Get all email templates"""
    templates = []
    async for template in email_templates_collection.find().sort("created_at", 1):
        template["id"] = str(template["_id"])
        del template["_id"]
        templates.append(template)
    return templates

@app.post("/api/admin/email/templates/reset-defaults")
async def reset_email_templates_to_defaults(current_user: dict = Depends(get_current_admin_user)):
    """Reset all email templates to clean, spam-filter-friendly defaults"""
    clean_templates = {
        "email_verification": {
            "subject": "Confirm your email",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Please confirm your email address to complete your account setup.</p>\n<p style="margin: 24px 0; text-align: center;">\n    <a href="{{verification_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">Confirm Email</a>\n</p>\n<p style="font-size: 13px; color: #6b7280; line-height: 1.5;">If the button does not work, copy this link into your browser:</p>\n<p style="font-size: 13px; color: #6b7280; word-break: break-all; background: #f9fafb; padding: 10px; border-radius: 4px;">{{verification_link}}</p>',
            "text_content": "Hi {{customer_name}},\n\nPlease confirm your email by visiting:\n{{verification_link}}\n\nThis link expires in 24 hours."
        },
        "welcome": {
            "subject": "Welcome, {{customer_name}}",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your account has been verified and is ready to use.</p>\n<p style="margin: 24px 0; text-align: center;">\n    <a href="{{dashboard_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">Go to Dashboard</a>\n</p>',
            "text_content": "Hi {{customer_name}},\n\nYour account has been verified. Visit your dashboard:\n{{dashboard_link}}"
        },
        "order_confirmation": {
            "subject": "Order confirmed - {{order_id}}",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your order <strong>{{order_id}}</strong> has been confirmed.</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;"><strong>Total:</strong> ${{total}}</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">We are setting up your service now. You will receive another email once it is ready.</p>',
            "text_content": "Hi {{customer_name}},\n\nYour order {{order_id}} has been confirmed.\nTotal: ${{total}}\n\nWe are setting up your service now."
        },
        "service_activated": {
            "subject": "Your service is ready",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your service has been activated. Here are your connection details:</p>\n<div style="background-color: #f9fafb; padding: 16px; border-radius: 4px; border-left: 3px solid #16a34a; margin: 16px 0;">\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Service:</strong> {{service_name}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Username:</strong> {{username}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Password:</strong> {{password}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Server:</strong> {{streaming_url}}</p>\n    <p style="margin: 0; font-size: 14px;"><strong>Valid until:</strong> {{expiry_date}}</p>\n</div>\n{{provision_notes}}',
            "text_content": "Hi {{customer_name}},\n\nYour service is ready.\n\nService: {{service_name}}\nUsername: {{username}}\nPassword: {{password}}\nServer: {{streaming_url}}\nValid until: {{expiry_date}}"
        },
        "payment_received": {
            "subject": "Payment received - Order {{order_id}}",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">We received your payment of ${{amount}} for order {{order_id}}. Your service is being set up now.</p>',
            "text_content": "Hi {{customer_name}},\n\nPayment of ${{amount}} received for order {{order_id}}. Your service is being set up."
        },
        "service_expiry_warning": {
            "subject": "Your service expires in {{days_remaining}} days",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your service <strong>{{service_name}}</strong> expires on <strong>{{expiry_date}}</strong> ({{days_remaining}} days from now).</p>\n<p style="margin: 24px 0; text-align: center;">\n    <a href="{{renewal_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">Renew Now</a>\n</p>',
            "text_content": "Hi {{customer_name}},\n\nYour service {{service_name}} expires on {{expiry_date}} ({{days_remaining}} days).\n\nRenew at: {{renewal_link}}"
        },
        "service_expired": {
            "subject": "Your service has expired",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your service <strong>{{service_name}}</strong> has expired and has been suspended.</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">To reactivate your service, please renew your subscription.</p>\n<p style="margin: 24px 0; text-align: center;">\n    <a href="{{renewal_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">Reactivate Service</a>\n</p>',
            "text_content": "Hi {{customer_name}},\n\nYour service {{service_name}} has expired and been suspended.\n\nRenew at: {{renewal_link}}"
        },
        "service_renewed": {
            "subject": "Service renewed - {{service_name}}",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your service has been renewed successfully.</p>\n<div style="background-color: #f9fafb; padding: 16px; border-radius: 4px; border-left: 3px solid #16a34a; margin: 16px 0;">\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Service:</strong> {{service_name}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Username:</strong> {{username}}</p>\n    <p style="margin: 0; font-size: 14px;"><strong>New expiry:</strong> {{new_expiry_date}}</p>\n</div>',
            "text_content": "Hi {{customer_name}},\n\nService renewed.\nService: {{service_name}}\nUsername: {{username}}\nNew expiry: {{new_expiry_date}}"
        },
        "ticket_reply": {
            "subject": "Reply on ticket #{{ticket_id}}",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">There is a new reply on your support ticket <strong>#{{ticket_id}}</strong>.</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6; padding: 12px; background: #f9fafb; border-radius: 4px; border-left: 3px solid #d1d5db;">{{reply_preview}}</p>\n<p style="margin: 24px 0; text-align: center;">\n    <a href="{{ticket_link}}" style="background-color: #1a56db; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 4px; display: inline-block; font-size: 15px; font-weight: 600;">View Ticket</a>\n</p>',
            "text_content": "Hi {{customer_name}},\n\nNew reply on ticket #{{ticket_id}}:\n\n{{reply_preview}}\n\nView ticket: {{ticket_link}}"
        },
        "reseller_activated": {
            "subject": "Your reseller panel is ready",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;">Your reseller panel has been set up with <strong>{{credits}} credits</strong>.</p>\n<div style="background-color: #f9fafb; padding: 16px; border-radius: 4px; border-left: 3px solid #1a56db; margin: 16px 0;">\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Panel URL:</strong> {{panel_url}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Username:</strong> {{username}}</p>\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Password:</strong> {{password}}</p>\n    <p style="margin: 0; font-size: 14px;"><strong>Credits:</strong> {{credits}}</p>\n</div>',
            "text_content": "Hi {{customer_name}},\n\nYour reseller panel is ready.\n\nPanel URL: {{panel_url}}\nUsername: {{username}}\nPassword: {{password}}\nCredits: {{credits}}"
        },
        "credits_added": {
            "subject": "Credits added to your panel",
            "html_content": '<p style="font-size: 15px; color: #374151; line-height: 1.6;">Hi {{customer_name}},</p>\n<p style="font-size: 15px; color: #374151; line-height: 1.6;"><strong>{{credits}} credits</strong> have been added to your reseller panel.</p>\n<div style="background-color: #f9fafb; padding: 16px; border-radius: 4px; border-left: 3px solid #1a56db; margin: 16px 0;">\n    <p style="margin: 0 0 8px; font-size: 14px;"><strong>Credits added:</strong> {{credits}}</p>\n    <p style="margin: 0; font-size: 14px;"><strong>Panel:</strong> {{panel_url}}</p>\n</div>',
            "text_content": "Hi {{customer_name}},\n\n{{credits}} credits have been added to your reseller panel.\n\nPanel: {{panel_url}}"
        }
    }
    
    updated = 0
    for template_type, data in clean_templates.items():
        result = await email_templates_collection.update_one(
            {"template_type": template_type},
            {"$set": {**data, "updated_at": datetime.utcnow()}}
        )
        if result.modified_count:
            updated += 1
    
    return {"message": f"Reset {updated} templates to spam-filter-friendly defaults"}

@app.get("/api/admin/email/templates/{template_id}")
async def get_email_template(template_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Get a single email template"""
    template = await email_templates_collection.find_one({"_id": str_to_objectid(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template["id"] = str(template["_id"])
    del template["_id"]
    return template

@app.put("/api/admin/email/templates/{template_id}")
async def update_email_template(
    template_id: str, 
    update_data: EmailTemplateUpdate, 
    current_user: dict = Depends(get_current_admin_user)
):
    """Update an email template"""
    template = await email_templates_collection.find_one({"_id": str_to_objectid(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Build update dict with only provided fields
    update_dict = {}
    if update_data.name is not None:
        update_dict["name"] = update_data.name
    if update_data.subject is not None:
        update_dict["subject"] = update_data.subject
    if update_data.html_content is not None:
        update_dict["html_content"] = update_data.html_content
    if update_data.text_content is not None:
        update_dict["text_content"] = update_data.text_content
    if update_data.is_active is not None:
        update_dict["is_active"] = update_data.is_active
    
    update_dict["updated_at"] = datetime.utcnow()
    
    await email_templates_collection.update_one(
        {"_id": str_to_objectid(template_id)},
        {"$set": update_dict}
    )
    
    return {"message": "Template updated successfully"}

@app.post("/api/admin/email/templates/{template_id}/preview")
async def preview_email_template(
    template_id: str,
    sample_data: dict,
    current_user: dict = Depends(get_current_admin_user)
):
    """Preview an email template with sample data"""
    template = await email_templates_collection.find_one({"_id": str_to_objectid(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Replace variables in template
    subject = template["subject"]
    html_content = template["html_content"]
    
    for key, value in sample_data.items():
        subject = subject.replace(f"{{{{{key}}}}}", str(value))
        html_content = html_content.replace(f"{{{{{key}}}}}", str(value))
    
    # Get email service to wrap content
    email_service = await get_configured_email_service()
    
    wrapped_html = email_service._wrap_email(html_content, template["name"])
    
    return {
        "subject": subject,
        "html_content": wrapped_html,
        "original_html": html_content
    }

@app.post("/api/admin/email/templates/{template_id}/test")
async def test_email_template(
    template_id: str,
    test_data: dict,
    current_user: dict = Depends(get_current_admin_user)
):
    """Send a test email using a template"""
    if "test_email" not in test_data:
        raise HTTPException(status_code=400, detail="test_email is required")
    
    template = await email_templates_collection.find_one({"_id": str_to_objectid(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Get email service
    email_service = await get_configured_email_service()
    
    if not email_service or not email_service.enabled:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    
    # Replace variables
    subject = template["subject"]
    html_content = template["html_content"]
    
    for key, value in test_data.items():
        if key != "test_email":
            subject = subject.replace(f"{{{{{key}}}}}", str(value))
            html_content = html_content.replace(f"{{{{{key}}}}}", str(value))
    
    wrapped_html = email_service._wrap_email(html_content, template["name"])
    text_content = template.get("text_content", "")
    for key, value in test_data.items():
        if key != "test_email":
            text_content = text_content.replace(f"{{{{{key}}}}}", str(value))
    if not text_content:
        text_content = email_service._html_to_text(html_content)
    
    # Send test email
    success = await email_service.send_email(
        to_email=test_data["test_email"],
        subject=f"[TEST] {subject}",
        html_content=wrapped_html,
        text_content=text_content,
        email_type="transactional"
    )
    
    if success:
        return {"message": f"Test email sent to {test_data['test_email']}"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send test email")

# ===== FILE UPLOAD ENDPOINTS =====

# Dynamic upload directory (works in any installation path)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads", "attachments")
HERO_IMAGES_DIR = os.path.join(BASE_DIR, "uploads", "hero")
LOGO_DIR = os.path.join(BASE_DIR, "uploads", "logos")
KB_MEDIA_DIR = os.path.join(BASE_DIR, "uploads", "kb")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(HERO_IMAGES_DIR, exist_ok=True)
os.makedirs(LOGO_DIR, exist_ok=True)
os.makedirs(KB_MEDIA_DIR, exist_ok=True)

@app.post("/api/admin/upload/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin_user)
):
    """Upload company logo for invoices"""
    MAX_FILE_SIZE = 2 * 1024 * 1024
    allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed")
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 2MB")
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"logo_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(LOGO_DIR, unique_filename)
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    return {
        "filename": file.filename,
        "url": f"{os.getenv('BACKEND_PUBLIC_URL', '')}/api/uploads/logos/{unique_filename}"
    }

app.mount("/api/uploads/logos", StaticFiles(directory=LOGO_DIR), name="logos")

@app.post("/api/admin/kb/upload")
async def upload_kb_media(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin_user)
):
    MAX_FILE_SIZE = 50 * 1024 * 1024
    allowed_image = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif']
    allowed_video = ['video/mp4', 'video/webm', 'video/ogg']
    allowed_types = allowed_image + allowed_video
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only images (JPG, PNG, WebP, GIF) and videos (MP4, WebM, OGG) are allowed")
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB")
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"kb_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(KB_MEDIA_DIR, unique_filename)
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    media_type = "image" if file.content_type in allowed_image else "video"
    return {
        "filename": file.filename,
        "url": f"/api/uploads/kb/{unique_filename}",
        "type": media_type,
        "size": len(contents)
    }

app.mount("/api/uploads/kb", StaticFiles(directory=KB_MEDIA_DIR), name="kb_media")

@app.post("/api/admin/upload/hero-image")
async def upload_hero_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin_user)
):
    """Upload hero background image"""
    # Validate file size (max 5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    
    # Validate file type
    allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, and WebP images are allowed")
    
    # Read file content
    contents = await file.read()
    file_size = len(contents)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB")
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"hero_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(HERO_IMAGES_DIR, unique_filename)
    
    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    
    # Return file info
    return {
        "filename": file.filename,
        "stored_filename": unique_filename,
        "size": file_size,
        "url": f"{os.getenv('BACKEND_PUBLIC_URL', '')}/api/uploads/hero/{unique_filename}"
    }

@app.post("/api/admin/upload/attachment")
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin_user)
):
    """Upload email attachment"""
    # Validate file size (max 10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    # Read file content
    contents = await file.read()
    file_size = len(contents)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB")
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    
    # Return file info
    return {
        "filename": file.filename,
        "stored_filename": unique_filename,
        "size": file_size,
        "path": f"/api/uploads/attachments/{unique_filename}",
        "url": f"{os.getenv('BACKEND_PUBLIC_URL', '')}/api/uploads/attachments/{unique_filename}"
    }

@app.delete("/api/admin/upload/attachment/{filename}")
async def delete_attachment(filename: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete an uploaded attachment"""
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(file_path)
        return {"message": "File deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

# Serve uploaded files (use dynamic path)
UPLOAD_BASE_DIR = os.path.dirname(os.path.abspath(__file__)) + "/uploads"
os.makedirs(UPLOAD_BASE_DIR, exist_ok=True)
os.makedirs(f"{UPLOAD_BASE_DIR}/attachments", exist_ok=True)
os.makedirs(f"{UPLOAD_BASE_DIR}/downloads", exist_ok=True)

app.mount("/api/uploads", StaticFiles(directory=UPLOAD_BASE_DIR), name="uploads")

# ===== EMAIL LOGS & HISTORY ENDPOINTS =====

@app.get("/api/admin/email/logs/all")
async def get_all_email_logs(
    limit: int = 50,
    skip: int = 0,
    status: Optional[str] = None,
    email_type: Optional[str] = None,
    current_user: dict = Depends(get_current_admin_user)
):
    """Get all email logs with filtering"""
    query = {}
    if status:
        query["status"] = status
    if email_type:
        query["email_type"] = email_type
    
    logs = []
    cursor = email_logs_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    
    async for log in cursor:
        log["id"] = str(log["_id"])
        del log["_id"]
        # Trim content for list view
        if "html_content" in log:
            log["content_preview"] = log["html_content"][:100] + "..."
            del log["html_content"]
        logs.append(log)
    
    total = await email_logs_collection.count_documents(query)
    
    return {"items": logs, "total": total, "limit": limit, "skip": skip}

@app.get("/api/admin/email/logs/{log_id}")
async def get_email_log_detail(log_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Get full details of a specific email log"""
    log = await email_logs_collection.find_one({"_id": str_to_objectid(log_id)})
    if not log:
        raise HTTPException(status_code=404, detail="Email log not found")
    
    log["id"] = str(log["_id"])
    del log["_id"]
    return log

@app.get("/api/customers/{customer_id}/email-history")
async def get_customer_email_history(
    customer_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get email history for a specific customer"""
    # Verify customer exists and user has permission
    customer = await users_collection.find_one({"_id": str_to_objectid(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Regular users can only see their own history
    if current_user["role"] != "admin" and current_user["sub"] != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    emails = await email_logger.get_customer_history(customer_id, limit)
    return emails

@app.post("/api/admin/email/logs/{log_id}/resend")
async def resend_email(log_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Resend a previously sent email"""
    log = await email_logs_collection.find_one({"_id": str_to_objectid(log_id)})
    if not log:
        raise HTTPException(status_code=404, detail="Email log not found")
    
    # Get email service
    email_service = await get_configured_email_service()
    
    if not email_service or not email_service.enabled:
        raise HTTPException(status_code=400, detail="SMTP is not configured")
    
    # Send email (will be automatically logged by email service)
    success = await email_service.send_email(
        to_email=log["recipient_email"],
        subject=f"[RESENT] {log['subject']}",
        html_content=log["html_content"],
        text_content=log.get("text_content", ""),
        email_type="transactional",
        customer_id=log.get("customer_id"),
        sent_by=current_user["sub"]
    )
    
    if success:
        return {"message": "Email resent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to resend email")

# ===== EMAIL STATISTICS ENDPOINTS =====

@app.get("/api/admin/email/statistics")
async def get_email_statistics(days: int = 30, current_user: dict = Depends(get_current_admin_user)):
    """Get email statistics for dashboard"""
    from datetime import timedelta
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Overall stats
    total = await email_logs_collection.count_documents({"created_at": {"$gte": start_date}})
    sent = await email_logs_collection.count_documents({"status": "sent", "created_at": {"$gte": start_date}})
    failed = await email_logs_collection.count_documents({"status": "failed", "created_at": {"$gte": start_date}})
    bounced = await email_logs_collection.count_documents({"status": "bounced", "created_at": {"$gte": start_date}})
    
    # By type
    transactional = await email_logs_collection.count_documents({"email_type": "transactional", "created_at": {"$gte": start_date}})
    marketing = await email_logs_collection.count_documents({"email_type": "marketing", "created_at": {"$gte": start_date}})
    
    # By template
    pipeline = [
        {"$match": {"created_at": {"$gte": start_date}, "template_type": {"$ne": None}}},
        {"$group": {"_id": "$template_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    
    template_stats = []
    async for stat in email_logs_collection.aggregate(pipeline):
        template_stats.append({"template": stat["_id"], "count": stat["count"]})
    
    # Unsubscribe count
    unsubscribes = await email_unsubscribes_collection.count_documents({"unsubscribed_at": {"$gte": start_date}})
    
    return {
        "period_days": days,
        "total": total,
        "sent": sent,
        "failed": failed,
        "bounced": bounced,
        "success_rate": round((sent / total * 100) if total > 0 else 0, 2),
        "by_type": {
            "transactional": transactional,
            "marketing": marketing
        },
        "top_templates": template_stats,
        "unsubscribes": unsubscribes
    }

# ===== UNSUBSCRIBE MANAGEMENT ENDPOINTS =====

@app.post("/api/unsubscribe")
async def unsubscribe_email(
    email: str,
    reason: Optional[str] = None,
    reason_text: Optional[str] = None,
    unsubscribe_type: str = "marketing"
):
    """Public endpoint for email unsubscribe (no auth required)"""
    await unsubscribe_manager.unsubscribe(
        email=email,
        unsubscribe_type=unsubscribe_type,
        reason=reason,
        reason_text=reason_text
    )
    
    return {"message": "You have been unsubscribed successfully"}

@app.post("/api/resubscribe")
async def resubscribe_email(email: str):
    """Public endpoint to resubscribe (no auth required)"""
    await unsubscribe_manager.resubscribe(email)
    return {"message": "You have been resubscribed successfully"}

@app.get("/api/admin/unsubscribes")
async def get_unsubscribes(
    limit: int = 50,
    skip: int = 0,
    current_user: dict = Depends(get_current_admin_user)
):
    """Get list of unsubscribed emails"""
    result = await unsubscribe_manager.get_all_unsubscribes(limit, skip)
    return result

@app.delete("/api/admin/unsubscribes/{email}")
async def remove_unsubscribe(email: str, current_user: dict = Depends(get_current_admin_user)):
    """Remove an email from unsubscribe list (admin resubscribes them)"""
    await unsubscribe_manager.resubscribe(email)
    return {"message": f"{email} has been resubscribed"}

# ===== SCHEDULED EMAILS ENDPOINTS =====

@app.post("/api/admin/email/schedule")
async def schedule_mass_email(
    subject: str,
    content: str,
    recipient_filter: str,
    scheduled_for: str,  # ISO datetime string
    current_user: dict = Depends(get_current_admin_user)
):
    """Schedule a mass email for later"""
    from datetime import datetime
    
    try:
        scheduled_datetime = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")
    
    if scheduled_datetime <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
    
    scheduled_email = {
        "subject": subject,
        "content": content,
        "recipient_filter": recipient_filter,
        "scheduled_for": scheduled_datetime,
        "sent": False,
        "created_by": current_user["sub"],
        "created_at": datetime.utcnow(),
        "cancelled": False
    }
    
    result = await scheduled_emails_collection.insert_one(scheduled_email)
    
    return {
        "message": "Email scheduled successfully",
        "scheduled_id": str(result.inserted_id),
        "scheduled_for": scheduled_datetime.isoformat()
    }

@app.get("/api/admin/email/scheduled")
async def get_scheduled_emails(current_user: dict = Depends(get_current_admin_user)):
    """Get all scheduled emails"""
    scheduled = []
    cursor = scheduled_emails_collection.find({"sent": False, "cancelled": False}).sort("scheduled_for", 1)
    
    async for email in cursor:
        email["id"] = str(email["_id"])
        del email["_id"]
        scheduled.append(email)
    
    return scheduled

@app.delete("/api/admin/email/scheduled/{scheduled_id}")
async def cancel_scheduled_email(scheduled_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Cancel a scheduled email"""
    result = await scheduled_emails_collection.update_one(
        {"_id": str_to_objectid(scheduled_id)},
        {"$set": {"cancelled": True}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    return {"message": "Scheduled email cancelled"}

@app.post("/api/admin/email/scheduled/{scheduled_id}/send-now")
async def send_scheduled_email_now(scheduled_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Send a scheduled email immediately"""
    email_doc = await scheduled_emails_collection.find_one({"_id": str_to_objectid(scheduled_id)})
    
    if not email_doc:
        raise HTTPException(status_code=404, detail="Scheduled email not found")
    
    if email_doc["sent"]:
        raise HTTPException(status_code=400, detail="Email already sent")
    
    # Send via mass email endpoint logic (reuse existing code)
    # Mark as sent
    await scheduled_emails_collection.update_one(
        {"_id": str_to_objectid(scheduled_id)},
        {"$set": {"sent": True, "sent_at": datetime.utcnow()}}
    )
    
    return {"message": "Scheduled email sent successfully"}

# ===== TEMPLATE VERSIONING ENDPOINTS =====

@app.get("/api/admin/email/templates/{template_id}/versions")
async def get_template_versions(template_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Get version history of a template"""
    versions = []
    cursor = template_versions_collection.find({"template_id": template_id}).sort("version_number", -1).limit(20)
    
    async for version in cursor:
        version["id"] = str(version["_id"])
        del version["_id"]
        # Don't return full content in list
        version["content_preview"] = version["html_content"][:100] + "..."
        del version["html_content"]
        versions.append(version)
    
    return versions

@app.post("/api/admin/email/templates/{template_id}/restore/{version_id}")
async def restore_template_version(
    template_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Restore a template to a previous version"""
    version = await template_versions_collection.find_one({"_id": str_to_objectid(version_id)})
    
    if not version or version["template_id"] != template_id:
        raise HTTPException(status_code=404, detail="Version not found")
    
    # Update template
    await email_templates_collection.update_one(
        {"_id": str_to_objectid(template_id)},
        {"$set": {
            "name": version["name"],
            "subject": version["subject"],
            "html_content": version["html_content"],
            "text_content": version.get("text_content", ""),
            "updated_at": datetime.utcnow()
        }}
    )
    
    return {"message": f"Template restored to version {version['version_number']}"}


_xtream_api_call = xtream_api_call


@app.get("/api/admin/bouquets/sync")
async def sync_bouquets_from_panel(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch bouquets from specific XtreamUI panel and sync to system"""
    settings = await get_settings()
    
    panels = settings.get("xtream", {}).get("panels", [])
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Panel not found")
    
    panel = panels[panel_index]
    
    try:
        # API-key panels: use JSON POST API
        if panel.get("api_key"):
            pkgs_data = await _xtream_api_call(panel, "get_packages")
            # Extract packages - handle nested {"status":"success","data":{"packages":[...]}}
            packages = []
            if isinstance(pkgs_data, list):
                packages = pkgs_data
            elif isinstance(pkgs_data, dict):
                nested = pkgs_data.get("data", pkgs_data)
                if isinstance(nested, dict):
                    for key in ("packages", "result", "items"):
                        if key in nested and isinstance(nested[key], list):
                            packages = nested[key]
                            break
                if not packages:
                    for key in ("packages", "data", "result"):
                        if key in pkgs_data and isinstance(pkgs_data[key], list):
                            packages = pkgs_data[key]
                            break
            
            all_bouquets = {}
            # Extract bouquet_ids directly from packages (most reliable)
            for pkg in packages:
                bouquet_ids = pkg.get("bouquet_ids") or pkg.get("bouquets") or []
                for bid in bouquet_ids:
                    if isinstance(bid, int):
                        all_bouquets[bid] = {"id": bid, "name": f"Bouquet {bid}"}
                    elif isinstance(bid, dict):
                        bq_id = bid.get("id") or bid.get("bouquet_id")
                        if bq_id:
                            all_bouquets[int(bq_id)] = {"id": int(bq_id), "name": bid.get("name", f"Bouquet {bq_id}")}
            
            # Try get_bouquets API for richer names
            for pkg in packages:
                pkg_id = pkg.get("id") or pkg.get("package_id")
                if not pkg_id:
                    continue
                try:
                    bq_data = await _xtream_api_call(panel, "get_bouquets", {"package_id": pkg_id})
                    bq_nested = bq_data.get("data", bq_data) if isinstance(bq_data, dict) else bq_data
                    bq_list = bq_nested if isinstance(bq_nested, list) else (bq_nested.get("bouquets", bq_nested.get("data", [])) if isinstance(bq_nested, dict) else [])
                    for bq in bq_list:
                        if isinstance(bq, dict):
                            bq_id = bq.get("id") or bq.get("bouquet_id")
                            bq_name = bq.get("name") or bq.get("bouquet_name", "")
                            if bq_id and bq_name:
                                all_bouquets[int(bq_id)] = {"id": int(bq_id), "name": bq_name}
                except Exception:
                    pass
            
            bouquets = sorted(all_bouquets.values(), key=lambda x: x["id"])
        else:
            # Standard session-based scraping
            client = XtreamUISessionClient(
                panel_url=panel["panel_url"],
                username=panel["admin_username"],
                password=panel["admin_password"],
                http_basic_user=panel.get("http_basic_user", ""),
                http_basic_pass=panel.get("http_basic_pass", ""),
                proxy_url=panel.get("proxy_url", "")
            )
            bouquets = client.fetch_bouquets_from_packages()
        
        if bouquets:
            await settings_collection.update_one(
                {},
                {"$set": {f"bouquets_panel_{panel_index}": bouquets, "updated_at": datetime.utcnow()}},
                upsert=True
            )
            return {
                "success": True,
                "message": f"Synced {len(bouquets)} bouquets from {panel['name']}",
                "bouquets": bouquets,
                "panel_name": panel['name']
            }
        else:
            raise HTTPException(status_code=500, detail="Could not fetch bouquets from panel")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bouquet sync error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/packages/sync")
async def sync_packages_from_panel(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch both regular AND trial packages from specific XtreamUI panel"""
    settings = await get_settings()
    xtream_settings = settings.get("xtream", {})
    
    panels = xtream_settings.get("panels", [])
    
    if not panels or len(panels) == 0:
        raise HTTPException(status_code=400, detail="No XtreamUI panels configured. Please add a panel in XtreamUI Panel tab.")
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found. Only {len(panels)} panel(s) configured.")
    
    # Use specified panel
    panel = panels[panel_index]
    
    try:
        # API-key panels: use JSON POST API
        if panel.get("api_key"):
            pkgs_data = await _xtream_api_call(panel, "get_packages")
            
            # Extract packages - handle nested {"status":"success","data":{"packages":[...]}}
            raw_packages = []
            if isinstance(pkgs_data, list):
                raw_packages = pkgs_data
            elif isinstance(pkgs_data, dict):
                nested = pkgs_data.get("data", pkgs_data)
                if isinstance(nested, dict):
                    for key in ("packages", "result", "items"):
                        if key in nested and isinstance(nested[key], list):
                            raw_packages = nested[key]
                            break
                if not raw_packages:
                    for key in ("packages", "data", "result"):
                        if key in pkgs_data and isinstance(pkgs_data[key], list):
                            raw_packages = pkgs_data[key]
                            break
            
            logger.info(f"Parsed {len(raw_packages)} packages from API response")
            
            regular_packages = []
            trial_packages = []
            for pkg in raw_packages:
                pkg_id = pkg.get("id") or pkg.get("package_id")
                
                # Parse duration - API may return "1 months" or "24 hours" as string
                raw_duration = pkg.get("duration", pkg.get("months", pkg.get("official_duration", "1")))
                if isinstance(raw_duration, str):
                    import re as re_mod
                    parts = raw_duration.strip().split()
                    duration = int(parts[0]) if parts and parts[0].isdigit() else 1
                    duration_unit = parts[1] if len(parts) > 1 else "months"
                else:
                    duration = int(raw_duration) if raw_duration else 1
                    duration_unit = pkg.get("duration_unit", pkg.get("official_duration_in", "months"))
                
                is_trial = pkg.get("is_trial", pkg.get("trial", False))
                if isinstance(is_trial, (int, str)):
                    is_trial = str(is_trial).lower() in ("1", "true", "yes")
                # Also detect trial from duration (0 hours = trial)
                if duration == 0 or (isinstance(raw_duration, str) and "0" in raw_duration.split()[0:1]):
                    is_trial = True
                
                max_conn = pkg.get("max_connections", pkg.get("connections", pkg.get("max_allowed_connections", 1)))
                credits_val = pkg.get("credits_cost", pkg.get("credits", pkg.get("cost", pkg.get("price", 0))))
                
                # Get bouquets - use bouquet_ids from package first, then try API
                bouquet_list = []
                raw_bids = pkg.get("bouquet_ids") or pkg.get("bouquets") or []
                for bid in raw_bids:
                    if isinstance(bid, int):
                        bouquet_list.append({"id": bid, "name": f"Bouquet {bid}"})
                    elif isinstance(bid, dict):
                        bouquet_list.append({"id": bid.get("id"), "name": bid.get("name", "")})
                
                # Try to get richer bouquet data with names
                try:
                    bq_data = await _xtream_api_call(panel, "get_bouquets", {"package_id": pkg_id})
                    bq_nested = bq_data.get("data", bq_data) if isinstance(bq_data, dict) else bq_data
                    bq_list = bq_nested if isinstance(bq_nested, list) else (bq_nested.get("bouquets", bq_nested.get("data", [])) if isinstance(bq_nested, dict) else [])
                    if bq_list:
                        bouquet_list = [{"id": b.get("id") or b.get("bouquet_id"), "name": b.get("name", b.get("bouquet_name", ""))} for b in bq_list if isinstance(b, dict)]
                except Exception:
                    pass  # Already have IDs from package
                
                formatted = {
                    "id": pkg_id,
                    "name": pkg.get("name", f"Package {pkg_id}"),
                    "duration": duration,
                    "duration_unit": duration_unit,
                    "max_connections": max_conn,
                    "credits": credits_val,
                    "is_trial": is_trial,
                    "bouquets": bouquet_list,
                }
                if is_trial:
                    trial_packages.append(formatted)
                else:
                    regular_packages.append(formatted)
            
            return {
                "success": True,
                "packages": regular_packages,
                "trial_packages": trial_packages,
                "count": len(regular_packages),
                "trial_count": len(trial_packages),
                "panel_name": panel.get("name", f"Panel {panel_index}"),
                "panel_index": panel_index
            }
        
        # Standard session-based scraping
        client = XtreamUISessionClient(
            panel_url=panel["panel_url"],
            username=panel["admin_username"],
            password=panel["admin_password"],
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", "")
        )
        
        # Fetch BOTH regular and trial packages
        regular_packages = client.fetch_packages()
        trial_packages = client.fetch_trial_packages()
        
        # Combine packages with type indicator
        all_packages = []
        
        # Add regular packages
        for pkg in regular_packages:
            pkg['package_type'] = 'regular'
            all_packages.append(pkg)
        
        # Add trial packages
        for pkg in trial_packages:
            pkg['package_type'] = 'trial'
            all_packages.append(pkg)
        
        return {
            "success": True,
            "packages": regular_packages,  # Keep backwards compatibility
            "trial_packages": trial_packages,
            "all_packages": all_packages,
            "count": len(regular_packages),
            "trial_count": len(trial_packages),
            "total_count": len(all_packages),
            "panel_name": panel.get("name", f"Panel {panel_index}"),
            "panel_index": panel_index
        }
        
    except Exception as e:
        logger.error(f"Package sync error for panel {panel_index}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/packages/sync-trial")
async def sync_trial_packages_from_panel(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Fetch trial packages from specific XtreamUI panel"""
    settings = await get_settings()
    xtream_settings = settings.get("xtream", {})
    
    panels = xtream_settings.get("panels", [])
    
    if not panels or len(panels) == 0:
        raise HTTPException(status_code=400, detail="No XtreamUI panels configured. Please add a panel in XtreamUI Panel tab.")
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found. Only {len(panels)} panel(s) configured.")
    
    # Use specified panel
    panel = panels[panel_index]
    
    try:
        # API-key panels: use JSON POST API (trial packages come from get_packages with is_trial flag)
        if panel.get("api_key"):
            pkgs_data = await _xtream_api_call(panel, "get_packages")
            raw_packages = pkgs_data if isinstance(pkgs_data, list) else pkgs_data.get("packages", pkgs_data.get("data", []))
            trial_packages = []
            for pkg in raw_packages:
                if pkg.get("is_trial", False):
                    trial_packages.append({
                        "id": pkg.get("id") or pkg.get("package_id"),
                        "name": pkg.get("name", "Trial"),
                        "duration": pkg.get("duration", 1),
                        "duration_unit": pkg.get("duration_unit", "days"),
                        "max_connections": pkg.get("max_connections", 1),
                        "credits": 0,
                        "is_trial": True,
                        "bouquets": [],
                    })
            return {
                "success": True,
                "packages": trial_packages,
                "count": len(trial_packages),
                "panel_name": panel.get("name", f"Panel {panel_index}")
            }
        
        # Standard session-based scraping
        client = XtreamUISessionClient(
            panel_url=panel["panel_url"],
            username=panel["admin_username"],
            password=panel["admin_password"],
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", "")
        )
        
        trial_packages = client.fetch_trial_packages()
        
        return {
            "success": True,
            "packages": trial_packages,
            "count": len(trial_packages),
            "panel_name": panel.get("name", f"Panel {panel_index}"),
            "panel_index": panel_index,
            "is_trial": True
        }
        
    except Exception as e:
        logger.error(f"Trial package sync error for panel {panel_index}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/bouquets")
async def get_bouquets(panel_id: int = 0, panel_type: str = 'xtream', current_user: dict = Depends(get_current_admin_user)):
    """Get available bouquets for a specific panel"""
    settings = await get_settings()
    
    # Get bouquets based on panel type
    if panel_type == 'xuione':
        # Get XuiOne panel bouquets
        xuione_panels = settings.get("xuione", {}).get("panels", [])
        if panel_id < len(xuione_panels):
            panel = xuione_panels[panel_id]
            bouquets = panel.get("bouquets", [])
            if bouquets:
                return bouquets
            # Try to fetch from XuiOne API
            try:
                from xuione_service import get_xuione_service
                svc = get_xuione_service(panel)
                if svc:
                    result = svc.get_bouquets()
                    if result.get("success"):
                        return result.get("bouquets", [])
            except Exception:
                pass
        return []  # Don't fall through to XtreamUI
    elif panel_type == 'onestream':
        # Get 1-Stream panel bouquets
        os_panels = settings.get("onestream", {}).get("panels", [])
        if panel_id < len(os_panels):
            panel = os_panels[panel_id]
            bouquets = panel.get("bouquets", [])
            if bouquets:
                return bouquets
            # No stored bouquets — extract from packages on the fly
            from onestream_service import get_onestream_service
            os_service = get_onestream_service(panel)
            if os_service:
                pkg_result = os_service.get_packages()
                if pkg_result.get("success"):
                    bouquet_ids = set()
                    for pkg in pkg_result.get("packages", []) + pkg_result.get("trial_packages", []):
                        for b_id in pkg.get("bouquets", []):
                            bouquet_ids.add(b_id)
                    return [{"id": b_id, "name": f"Bouquet {b_id}"} for b_id in sorted(bouquet_ids)]
        return []  # Don't fall through to XtreamUI fallback
    elif panel_type == 'aether':
        ae_panels = settings.get("aether", {}).get("panels", [])
        if panel_id < len(ae_panels):
            panel = ae_panels[panel_id]
            stored = panel.get("bouquets", [])
            if stored:
                return stored
            ae = get_aether_service(panel)
            if ae:
                res = await ae.get_all_bouquets()
                if res.get("success"):
                    bouquets = [{"id": b["id"], "name": b["name"]} for b in res["bouquets"]]
                    await db.settings.update_one({}, {"$set": {f"aether.panels.{panel_id}.bouquets": bouquets}})
                    return bouquets
        return []
    elif panel_type == 'nxtdash':
        # Get NXT Dash bouquets from stored panel settings (with custom names)
        nd_panels = settings.get("nxtdash", {}).get("panels", [])
        if panel_id < len(nd_panels):
            panel = nd_panels[panel_id]
            stored = panel.get("bouquets", [])
            if stored:
                return stored
            # Not synced yet — extract from lines
            nd_service = get_nxtdash_service(panel)
            if nd_service:
                import ast
                all_bouquet_ids = set()
                result = await nd_service.get_lines()
                if result.get("success"):
                    for line in result.get("lines", []):
                        bouquet_raw = line.get("bouquet", "[]")
                        if isinstance(bouquet_raw, str):
                            try: bouquet_ids = ast.literal_eval(bouquet_raw)
                            except (ValueError, SyntaxError): bouquet_ids = []
                        elif isinstance(bouquet_raw, list):
                            bouquet_ids = bouquet_raw
                        else:
                            bouquet_ids = []
                        for bid in bouquet_ids:
                            all_bouquet_ids.add(int(bid))
                return [{"id": bid, "name": f"Bouquet {bid}"} for bid in sorted(all_bouquet_ids)]
        return []
    else:
        # Get XtreamUI panel bouquets (existing logic)
        xtream_panels = settings.get("xtream", {}).get("panels", [])
        if panel_id < len(xtream_panels):
            panel = xtream_panels[panel_id]
            bouquets = panel.get("bouquets", [])
            if bouquets:
                return bouquets
    
    # Legacy fallback
    panel_bouquets = settings.get(f"bouquets_panel_{panel_id}", [])
    if panel_bouquets:
        return panel_bouquets
    
    legacy_bouquets = settings.get("bouquets", [])
    if legacy_bouquets:
        return legacy_bouquets
    
    # Default bouquets
    return [
        {"id": 1, "name": "All Channels"},
        {"id": 2, "name": "Movies"},
        {"id": 3, "name": "Sports"},
    ]

@app.post("/api/admin/imported-users/create-accounts")
async def create_accounts_for_imported_users(current_user: dict = Depends(get_current_admin_user)):
    """Create billing customer accounts for all imported users that don't have one yet."""
    cursor = imported_users_collection.find({"user_id": {"$exists": False}})
    imported_users = await cursor.to_list(length=10000)
    
    # Also include users with empty user_id
    cursor2 = imported_users_collection.find({"user_id": ""})
    imported_users += await cursor2.to_list(length=10000)
    
    created = 0
    linked = 0
    errors = 0
    
    for iu in imported_users:
        try:
            user_id = await create_customer_for_imported_user(iu)
            if user_id:
                # Check if this was a new creation or existing link
                existing = await users_collection.find_one({"_id": str_to_objectid(user_id), "created_via": "panel_sync"})
                if existing and (datetime.utcnow() - existing.get("created_at", datetime.utcnow())).total_seconds() < 5:
                    created += 1
                else:
                    linked += 1
        except Exception as e:
            logger.warning(f"Failed to create account for {iu.get('username')}: {e}")
            errors += 1
    
    return {"success": True, "created": created, "linked": linked, "errors": errors, "total_processed": len(imported_users)}


@app.post("/api/admin/imported-users/cleanup-orphans")
async def cleanup_orphaned_imported_users(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Remove imported users from panels that no longer exist. Optionally delete linked customer accounts."""
    delete_customers = data.get("delete_customers", False)
    
    settings = await get_settings()
    active_names = {
        "xtream": [p.get("name") for p in settings.get("xtream", {}).get("panels", [])],
        "xuione": [p.get("name") for p in settings.get("xuione", {}).get("panels", [])],
        "onestream": [p.get("name") for p in settings.get("onestream", {}).get("panels", [])],
        "nxtdash": [p.get("name") for p in settings.get("nxtdash", {}).get("panels", [])],
        "aether": [p.get("name") for p in settings.get("aether", {}).get("panels", [])],
    }
    all_active = sum(active_names.values(), [])

    removed_users = 0
    removed_customers = 0
    removed_services = 0

    for ptype, names in active_names.items():
        orphans = await imported_users_collection.find({"panel_type": ptype, "panel_name": {"$nin": names}}).to_list(length=50000)
        if not orphans:
            continue

        if delete_customers:
            for orphan in orphans:
                uid = orphan.get("user_id")
                if uid:
                    # Only delete customer accounts created via panel_sync (not manually registered)
                    del_result = await users_collection.delete_one({"_id": str_to_objectid(uid), "created_via": "panel_sync"})
                    removed_customers += del_result.deleted_count
                    # Remove their services too
                    svc_del = await services_collection.delete_many({"user_id": uid})
                    removed_services += svc_del.deleted_count

        del_result = await imported_users_collection.delete_many({"panel_type": ptype, "panel_name": {"$nin": names}})
        removed_users += del_result.deleted_count

    # Also clean null panel_type orphans
    null_orphans = await imported_users_collection.find({
        "$or": [
            {"panel_type": None, "panel_name": {"$nin": all_active}},
            {"panel_type": {"$exists": False}, "panel_name": {"$nin": all_active}}
        ]
    }).to_list(length=10000)
    
    if delete_customers:
        for orphan in null_orphans:
            uid = orphan.get("user_id")
            if uid:
                del_r = await users_collection.delete_one({"_id": str_to_objectid(uid), "created_via": "panel_sync"})
                removed_customers += del_r.deleted_count
                svc_del = await services_collection.delete_many({"user_id": uid})
                removed_services += svc_del.deleted_count

    null_del = await imported_users_collection.delete_many({
        "$or": [
            {"panel_type": None, "panel_name": {"$nin": all_active}},
            {"panel_type": {"$exists": False}, "panel_name": {"$nin": all_active}}
        ]
    })
    removed_users += null_del.deleted_count

    return {
        "success": True,
        "removed_imported_users": removed_users,
        "removed_customers": removed_customers,
        "removed_services": removed_services,
    }


@app.post("/api/admin/imported-users/deduplicate")
async def deduplicate_imported_users(current_user: dict = Depends(get_current_admin_user)):
    """Remove duplicate imported users, keeping the most recent"""
    # Group by username + panel_name + account_type (most reliable fields)
    pipeline = [
        {"$sort": {"last_synced": -1}},
        {"$group": {
            "_id": {"username": "$username", "panel_name": "$panel_name", "account_type": "$account_type"},
            "docs": {"$push": "$_id"},
            "count": {"$sum": 1},
            "keep": {"$first": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicates = await imported_users_collection.aggregate(pipeline).to_list(10000)
    removed = 0
    for dup in duplicates:
        ids_to_remove = [d for d in dup["docs"] if d != dup["keep"]]
        if ids_to_remove:
            result = await imported_users_collection.delete_many({"_id": {"$in": ids_to_remove}})
            removed += result.deleted_count
    
    # Also deduplicate by just username + panel_name (catches subscriber/reseller not set)
    pipeline2 = [
        {"$sort": {"last_synced": -1}},
        {"$group": {
            "_id": {"username": "$username", "panel_name": "$panel_name"},
            "docs": {"$push": "$_id"},
            "count": {"$sum": 1},
            "keep": {"$first": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicates2 = await imported_users_collection.aggregate(pipeline2).to_list(10000)
    for dup in duplicates2:
        ids_to_remove = [d for d in dup["docs"] if d != dup["keep"]]
        if ids_to_remove:
            result = await imported_users_collection.delete_many({"_id": {"$in": ids_to_remove}})
            removed += result.deleted_count
    
    # Normalize all panel_index to int
    await imported_users_collection.update_many(
        {"panel_index": {"$type": "string"}},
        [{"$set": {"panel_index": {"$toInt": "$panel_index"}}}]
    )
    
    # Recreate unique index
    try:
        await imported_users_collection.drop_index("unique_imported_user")
    except Exception:
        pass
    try:
        await imported_users_collection.create_index(
            [("username", 1), ("panel_name", 1), ("account_type", 1)],
            unique=True, name="unique_imported_user", background=True
        )
    except Exception as e:
        logger.warning(f"Could not create unique index: {e}")
    
    logger.info(f"Deduplication complete: removed {removed} duplicates")
    return {"message": f"Removed {removed} duplicates", "removed": removed}

@app.post("/api/admin/sync-all-users")
async def sync_all_users_from_all_panels(current_user: dict = Depends(get_current_admin_user)):
    """Sync users from ALL active XtreamUI and XuiOne panels"""
    settings = await get_settings()
    
    results = {
        "success": True,
        "panels_synced": [],
        "total_synced": 0,
        "total_updated": 0,
        "total_removed": 0,
        "errors": []
    }
    
    # Sync XtreamUI panels
    xtream_panels = settings.get("xtream", {}).get("panels", [])
    for panel_index, panel in enumerate(xtream_panels):
        panel_name = panel.get("name", f"XtreamUI Panel {panel_index + 1}")
        try:
            logger.info(f"Syncing users from XtreamUI panel: {panel_name}")
            
            # API-key panels: use lookup_line to refresh known users
            if panel.get("api_key"):
                logger.info(f"Syncing {panel_name} via API-key (lookup_line per known user)")
                api_synced = 0
                api_updated = 0
                
                # Get all known usernames for this panel from imported_users + services
                known_usernames = set()
                async for iu in imported_users_collection.find({"panel_type": "xtream", "panel_index": panel_index}, {"username": 1}):
                    if iu.get("username"):
                        known_usernames.add(iu["username"])
                async for svc in services_collection.find({"panel_type": "xtream", "panel_index": panel_index}, {"xtream_username": 1}):
                    if svc.get("xtream_username"):
                        known_usernames.add(svc["xtream_username"])
                
                logger.info(f"Found {len(known_usernames)} known users for {panel_name}")
                
                for uname in known_usernames:
                    try:
                        data = await _xtream_api_call(panel, "lookup_line", {"username": uname})
                        line = data.get("data", data) if isinstance(data, dict) else data
                        if isinstance(line, dict) and line.get("username"):
                            exp_date = None
                            exp_val = line.get("exp_date") or line.get("expiry", "")
                            if exp_val:
                                if isinstance(exp_val, (int, float)) and exp_val > 0:
                                    exp_date = datetime.utcfromtimestamp(exp_val)
                                elif isinstance(exp_val, str):
                                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                                        try:
                                            exp_date = datetime.strptime(exp_val.split(".")[0].replace("Z",""), fmt)
                                            break
                                        except ValueError:
                                            continue
                            
                            st = "active"
                            if line.get("status") == "disabled" or line.get("is_suspended"):
                                st = "suspended"
                            elif exp_date and exp_date < datetime.utcnow():
                                st = "expired"
                            
                            doc = {
                                "panel_index": panel_index, "panel_type": "xtream", "panel_name": panel_name,
                                "xtream_user_id": line.get("id") or line.get("user_id", 0),
                                "username": uname, "password": line.get("password", ""),
                                "expiry_date": exp_date, "status": st,
                                "max_connections": safe_int(line.get("max_connections", 1)),
                                "account_type": "subscriber", "last_synced": datetime.utcnow()
                            }
                            r = await safe_upsert_imported_user(
                                {"username": uname, "panel_type": "xtream", "panel_index": panel_index, "account_type": "subscriber"}, doc
                            )
                            if r.upserted_id:
                                api_synced += 1
                            elif r.modified_count:
                                api_updated += 1
                    except Exception as e:
                        logger.debug(f"lookup_line failed for {uname}: {e}")
                
                results["panels_synced"].append({"name": panel_name, "type": "xtream", "synced": api_synced, "updated": api_updated})
                results["total_synced"] += api_synced
                results["total_updated"] += api_updated
                continue
            
            xtream_service = get_xtream_service(panel)
            if not xtream_service:
                results["errors"].append(f"{panel_name}: Service not available")
                continue
            
            synced_count = 0
            updated_count = 0
            
            # Sync subscribers using get_reseller_users()
            users_result = xtream_service.get_reseller_users()
            if users_result.get("success"):
                users = users_result.get("users", [])
                for user_data in users:
                    username = user_data.get("username", "")
                    if not username:
                        continue
                    
                    filter_query = {
                        "panel_index": panel_index,
                        "panel_type": "xtream",
                        "username": username,
                        "account_type": "subscriber"
                    }
                    
                    # Parse expiry date
                    expiry_str = user_data.get("expiry", "")
                    expiry_date = None
                    if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                        expiry_str = str(expiry_str).strip()
                        # Try epoch timestamp first
                        try:
                            _epoch = int(expiry_str)
                            if _epoch > 0:
                                expiry_date = datetime.utcfromtimestamp(_epoch)
                        except (ValueError, TypeError, OSError):
                            pass
                        # Try date string formats
                        if not expiry_date:
                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                try:
                                    expiry_date = datetime.strptime(expiry_str, fmt)
                                    break
                                except ValueError:
                                    continue
                    
                    status = "active"
                    if expiry_date and expiry_date < datetime.utcnow():
                        status = "expired"
                    
                    user_doc = {
                        "panel_index": panel_index,
                        "panel_type": "xtream",
                        "panel_name": panel_name,
                        "xtream_user_id": user_data.get("user_id", 0),
                        "username": username,
                        "password": user_data.get("password", ""),
                        "expiry_date": expiry_date,
                        "status": status,
                        "max_connections": safe_int(user_data.get("max_connections", 1)),
                        "account_type": "subscriber",
                        "created_by_reseller": user_data.get("created_by", ""),
                        "last_synced": datetime.utcnow()
                    }
                    
                    result = await safe_upsert_imported_user(
                        filter_query,
                        user_doc,
                            )
                    if result.upserted_id:
                        synced_count += 1
                    elif result.modified_count:
                        updated_count += 1
            
            # Sync resellers using get_subresellers()
            resellers_result = xtream_service.get_subresellers()
            if resellers_result.get("success"):
                resellers = resellers_result.get("users", [])
                for reseller_data in resellers:
                    username = reseller_data.get("username", "")
                    if not username:
                        continue
                    
                    existing = await imported_users_collection.find_one({
                        "panel_index": panel_index,
                        "panel_type": "xtream",
                        "username": username,
                        "account_type": "reseller"
                    })
                    
                    reseller_doc = {
                        "panel_index": panel_index,
                        "panel_type": "xtream",
                        "panel_name": panel_name,
                        "xtream_user_id": reseller_data.get("user_id", 0),
                        "username": username,
                        "password": reseller_data.get("password", ""),
                        "credits": float(reseller_data.get("credits", 0) or 0),
                        "status": "active",
                        "account_type": "reseller",
                        "member_group": reseller_data.get("member_group", ""),
                        "last_synced": datetime.utcnow()
                    }
                    
                    result = await safe_upsert_imported_user(
                        {"username": reseller_doc.get("username", ""), "panel_type": reseller_doc.get("panel_type", "xtream"), "panel_index": reseller_doc.get("panel_index", 0), "account_type": reseller_doc.get("account_type", "subscriber")},

                        reseller_doc,

        
                    )

                    if result.upserted_id:

                        synced_count += 1

                    elif result.modified_count:

                        updated_count += 1
            
            results["panels_synced"].append({
                "name": panel_name,
                "type": "xtream",
                "synced": synced_count,
                "updated": updated_count
            })
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
            
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")
    
    # Sync XuiOne panels
    xuione_panels = settings.get("xuione", {}).get("panels", [])
    for panel_index, panel in enumerate(xuione_panels):
        panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
        try:
            logger.info(f"Syncing users from XuiOne panel: {panel_name}")
            
            xuione_service = get_xuione_service(panel)
            if not xuione_service:
                results["errors"].append(f"{panel_name}: Service not available")
                continue
            
            synced_count = 0
            updated_count = 0
            
            # Sync subscribers using get_users()
            users_result = xuione_service.get_users()
            if users_result.get("success"):
                users = users_result.get("users", [])
                for user_data in users:
                    username = user_data.get("username", "")
                    if not username:
                        continue
                    
                    existing = await imported_users_collection.find_one({
                        "panel_index": panel_index,
                        "panel_type": "xuione",
                        "username": username,
                        "account_type": "subscriber"
                    })
                    
                    # Parse expiry date
                    expiry_str = user_data.get("expiry", "")
                    expiry_date = None
                    if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                        # Try epoch timestamp first
                        try:
                            _epoch = int(str(expiry_str).strip())
                            if _epoch > 0:
                                expiry_date = datetime.utcfromtimestamp(_epoch)
                        except (ValueError, TypeError, OSError):
                            pass
                        if not expiry_date:
                            date_formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
                            for fmt in date_formats:
                                try:
                                    expiry_date = datetime.strptime(expiry_str.strip(), fmt)
                                    break
                                except ValueError:
                                    continue
                    
                    status = "active"
                    if expiry_date and expiry_date < datetime.utcnow():
                        status = "expired"
                    
                    user_doc = {
                        "panel_index": panel_index,
                        "panel_type": "xuione",
                        "panel_name": panel_name,
                        "xtream_user_id": user_data.get("user_id", 0),
                        "username": username,
                        "password": user_data.get("password", ""),
                        "expiry_date": expiry_date,
                        "status": status,
                        "max_connections": safe_int(user_data.get("max_connections", 1)),
                        "account_type": "subscriber",
                        "last_synced": datetime.utcnow()
                    }
                    
                    result = await safe_upsert_imported_user(
                        {"username": username, "panel_type": user_doc.get("panel_type", "xtream"), "panel_index": user_doc.get("panel_index", 0), "account_type": user_doc.get("account_type", "subscriber")},
                        user_doc,
                            )
                    if result.upserted_id:
                        synced_count += 1
                    elif result.modified_count:
                        updated_count += 1
            
            # Sync resellers using get_subresellers()
            resellers_result = xuione_service.get_subresellers()
            if resellers_result.get("success"):
                resellers = resellers_result.get("users", [])
                for reseller_data in resellers:
                    username = reseller_data.get("username", "")
                    if not username:
                        continue
                    
                    existing = await imported_users_collection.find_one({
                        "panel_index": panel_index,
                        "panel_type": "xuione",
                        "username": username,
                        "account_type": "reseller"
                    })
                    
                    reseller_doc = {
                        "panel_index": panel_index,
                        "panel_type": "xuione",
                        "panel_name": panel_name,
                        "xtream_user_id": reseller_data.get("user_id", 0),
                        "username": username,
                        "password": "",
                        "credits": float(reseller_data.get("credits", 0) or 0),
                        "status": "active",
                        "account_type": "reseller",
                        "member_group": reseller_data.get("member_group", ""),
                        "last_synced": datetime.utcnow()
                    }
                    
                    result = await safe_upsert_imported_user(
                        {"username": reseller_doc.get("username", ""), "panel_type": reseller_doc.get("panel_type", "xtream"), "panel_index": reseller_doc.get("panel_index", 0), "account_type": reseller_doc.get("account_type", "subscriber")},

                        reseller_doc,

        
                    )

                    if result.upserted_id:

                        synced_count += 1

                    elif result.modified_count:

                        updated_count += 1
            
            results["panels_synced"].append({
                "name": panel_name,
                "type": "xuione",
                "synced": synced_count,
                "updated": updated_count
            })
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
            
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")
    
    # Sync 1-Stream panels
    onestream_panels = settings.get("onestream", {}).get("panels", [])
    for panel_index, panel in enumerate(onestream_panels):
        panel_name = panel.get("name", f"1-Stream Panel {panel_index + 1}")
        try:
            logger.info(f"Syncing users from 1-Stream panel: {panel_name}")
            os_service = get_onestream_service(panel)
            if not os_service:
                results["errors"].append(f"{panel_name}: Service not available")
                continue
            synced_count = 0
            updated_count = 0

            # Get the reseller's username to filter direct lines only
            reseller_username = panel.get("admin_username", "").strip()

            # Sync lines (subscribers) — only direct lines owned by this reseller
            lines_result = os_service.get_lines()
            lines_list = lines_result.get('users', [])
            # Count lines with actual usernames vs empty
            lines_with_username = sum(1 for l in lines_list if l.get("username"))
            lines_without_username = len(lines_list) - lines_with_username
            logger.info(f"1-Stream lines sync: success={lines_result.get('success')}, total={len(lines_list)}, with_username={lines_with_username}, without_username={lines_without_username}")
            if lines_with_username == 0 and len(lines_list) > 0:
                # Log sample line to debug format
                sample = lines_list[0] if lines_list else {}
                logger.info(f"1-Stream sample line keys: {list(sample.keys())}, username='{sample.get('username','')}', mac='{sample.get('mac_addr','')}'")
            if not lines_result.get("success"):
                logger.warning(f"1-Stream lines sync failed: {lines_result.get('error', 'unknown')}")
            if lines_result.get("success"):
                saved_count = 0
                skipped_count = 0
                for line in lines_result.get("users", []):
                    username = line.get("username", "")
                    # For MAG/STB lines without username, use mac_addr or line_id as identifier
                    if not username:
                        mac = line.get("mac_addr", "")
                        if mac:
                            username = f"MAC:{mac}"
                        elif line.get("line_id"):
                            username = f"LINE:{line['line_id']}"
                        else:
                            skipped_count += 1
                            continue
                    # Filter: only import lines directly owned by this reseller
                    line_owner = line.get("owner", "").strip()
                    if reseller_username and line_owner and line_owner != reseller_username:
                        skipped_count += 1
                        continue
                    existing = await imported_users_collection.find_one({
                        "panel_index": panel_index, "panel_type": "onestream",
                        "username": username, "account_type": "subscriber"
                    })
                    user_doc = {
                        "panel_index": panel_index,
                        "panel_type": "onestream",
                        "panel_name": panel_name,
                        "onestream_line_id": line.get("line_id", ""),
                        "username": username,
                        "password": line.get("password", ""),
                        "expiry_date": line.get("expiry_date"),
                        "status": line.get("status", "active"),
                        "max_connections": line.get("max_connections", 1),
                        "account_type": "subscriber",
                        "owner": line.get("owner", ""),
                        "last_synced": datetime.utcnow()
                    }
                    if existing:
                        await imported_users_collection.update_one({"_id": existing["_id"]}, {"$set": user_doc})
                        updated_count += 1
                    else:
                        try:
                            result = await safe_upsert_imported_user(
                                {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                                user_doc,
                                            )
                            if result.upserted_id:
                                synced_count += 1
                            else:
                                updated_count += 1
                            saved_count += 1
                        except Exception as e:
                            logger.warning(f"1-Stream line upsert error for {username}: {e}")
                            await imported_users_collection.update_one(
                                {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                                {"$set": user_doc}
                            )
                            updated_count += 1
                logger.info(f"1-Stream subscriber sync done: saved={saved_count}, skipped={skipped_count}, synced={synced_count}, updated={updated_count}")
            # Sync sub-resellers
            resellers_result = os_service.get_subresellers()
            if resellers_result.get("success"):
                for reseller in resellers_result.get("users", []):
                    uname = reseller.get("username", "")
                    if not uname:
                        continue
                    existing = await imported_users_collection.find_one({
                        "panel_index": panel_index, "panel_type": "onestream",
                        "username": uname, "account_type": "reseller"
                    })
                    reseller_doc = {
                        "panel_index": panel_index,
                        "panel_type": "onestream",
                        "panel_name": panel_name,
                        "onestream_user_id": reseller.get("user_id", 0),
                        "username": uname,
                        "password": "",
                        "credits": float(reseller.get("credits", 0) or 0),
                        "status": "active",
                        "account_type": "reseller",
                        "last_synced": datetime.utcnow()
                    }
                    result = await safe_upsert_imported_user(
                        {"username": reseller_doc.get("username", username), "panel_type": reseller_doc.get("panel_type", "xtream"), "panel_index": reseller_doc.get("panel_index", 0), "account_type": reseller_doc.get("account_type", "reseller")},
                        reseller_doc,
                            )
                    if result.upserted_id:
                        synced_count += 1
                    elif result.modified_count:
                        updated_count += 1

            results["panels_synced"].append({"name": panel_name, "type": "onestream", "synced": synced_count, "updated": updated_count})
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")

    # Sync NXT Dash panels
    nxtdash_panels = settings.get("nxtdash", {}).get("panels", [])
    for panel_index, panel in enumerate(nxtdash_panels):
        panel_name = panel.get("name", f"NXT Dash Panel {panel_index + 1}")
        try:
            logger.info(f"Syncing users from NXT Dash panel: {panel_name}")
            nd_service = get_nxtdash_service(panel)
            if not nd_service:
                results["errors"].append(f"{panel_name}: Service not available")
                continue

            synced_count = 0
            updated_count = 0

            # Paginate through all lines
            page = 1
            while True:
                lines_result = await nd_service.get_lines(page=page)
                if not lines_result.get("success"):
                    break
                lines = lines_result.get("lines", [])
                if not lines:
                    break

                for line in lines:
                    username = line.get("username", "")
                    if not username:
                        continue

                    expire_ts = line.get("expire_date")
                    expiry_date = None
                    if expire_ts:
                        try:
                            expiry_date = datetime.utcfromtimestamp(int(expire_ts))
                        except Exception:
                            pass

                    status = "active" if line.get("enabled") == 1 and line.get("admin_enabled") == 1 else "disabled"
                    if expiry_date and expiry_date < datetime.utcnow():
                        status = "expired"

                    user_doc = {
                        "panel_index": panel_index,
                        "panel_type": "nxtdash",
                        "panel_name": panel_name,
                        "nxtdash_line_id": str(line.get("id", "")),
                        "username": username,
                        "password": line.get("password", ""),
                        "expiry_date": expiry_date,
                        "status": status,
                        "max_connections": line.get("user_connection", 1),
                        "account_type": "subscriber",
                        "is_trial": line.get("is_trial", 0),
                        "owner": line.get("owner", ""),
                        "last_synced": datetime.utcnow(),
                    }

                    result = await safe_upsert_imported_user(
                        {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                        user_doc,
                            )
                    if result.upserted_id:
                        synced_count += 1
                    elif result.modified_count:
                        updated_count += 1

                last_page = lines_result.get("last_page", 1)
                if page >= last_page:
                    break
                page += 1

            results["panels_synced"].append({"name": panel_name, "type": "nxtdash", "synced": synced_count, "updated": updated_count})
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")
    
    # Sync GhostSurf VPN panels
    ghostsurf_panels = settings.get("ghostsurf", {}).get("panels", [])
    for panel_index, panel in enumerate(ghostsurf_panels):
        panel_name = panel.get("name", f"GhostSurf VPN {panel_index + 1}")
        try:
            logger.info(f"Syncing users from GhostSurf panel: {panel_name}")
            from ghostsurf_service import get_ghostsurf_service
            gs = get_ghostsurf_service(settings, panel_index)
            if not gs:
                results["errors"].append(f"{panel_name}: Service not available")
                continue
            
            synced_count = 0
            updated_count = 0
            
            accounts = await gs.list_accounts()
            if not isinstance(accounts, list):
                accounts = accounts.get("accounts", accounts.get("data", []))
            
            for acct in accounts:
                acct_id = str(acct.get("id") or acct.get("account_id", ""))
                username = acct.get("username", "")
                if not acct_id:
                    continue
                
                # Fetch password via credentials endpoint
                password = acct.get("password", "")
                if not password:
                    try:
                        creds = await gs.get_credentials(acct_id)
                        password = creds.get("password", "")
                    except Exception:
                        pass
                
                # Parse expiry
                expiry_date = None
                expiry_str = acct.get("expires_at") or acct.get("expiry") or acct.get("expiry_date", "")
                if expiry_str:
                    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                        try:
                            expiry_date = datetime.strptime(str(expiry_str).split(".")[0].replace("Z",""), fmt)
                            break
                        except ValueError:
                            continue
                
                status = acct.get("status", "active")
                if expiry_date and expiry_date < datetime.utcnow():
                    status = "expired"
                
                plan_name = acct.get("plan", {}).get("name", "") if isinstance(acct.get("plan"), dict) else acct.get("plan_name", acct.get("plan", ""))
                
                user_doc = {
                    "panel_index": panel_index,
                    "panel_type": "ghostsurf",
                    "panel_name": panel_name,
                    "username": username or acct_id,
                    "password": password,
                    "expiry_date": expiry_date,
                    "status": status,
                    "max_connections": acct.get("max_devices", 5),
                    "account_type": "subscriber",
                    "ghostsurf_account_id": acct_id,
                    "ghostsurf_plan_id": acct.get("plan_id") or (acct.get("plan", {}).get("id") if isinstance(acct.get("plan"), dict) else ""),
                    "plan_name": plan_name,
                    "last_synced": datetime.utcnow()
                }
                
                result = await safe_upsert_imported_user(
                    {"panel_type": "ghostsurf", "panel_index": panel_index, "ghostsurf_account_id": acct_id},
                    user_doc,
                )
                if result.upserted_id:
                    synced_count += 1
                elif result.modified_count:
                    updated_count += 1
            
            # Remove GhostSurf users that no longer exist on the panel
            synced_acct_ids = [str(a.get("id") or a.get("account_id", "")) for a in accounts if a.get("id") or a.get("account_id")]
            if synced_acct_ids:
                removed = await imported_users_collection.delete_many({
                    "panel_type": "ghostsurf",
                    "panel_index": panel_index,
                    "ghostsurf_account_id": {"$nin": synced_acct_ids}
                })
                if removed.deleted_count:
                    results["total_removed"] = results.get("total_removed", 0) + removed.deleted_count
                    logger.info(f"Removed {removed.deleted_count} deleted GhostSurf accounts from {panel_name}")
            
            results["panels_synced"].append({
                "name": panel_name,
                "type": "ghostsurf",
                "synced": synced_count,
                "updated": updated_count
            })
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
            
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")
    
    # Sync Aether panels
    aether_panels = settings.get("aether", {}).get("panels", [])
    for panel_index, panel in enumerate(aether_panels):
        panel_name = panel.get("name", f"Aether Panel {panel_index + 1}")
        try:
            logger.info(f"Syncing users from Aether panel: {panel_name}")
            ae = get_aether_service(panel)
            if not ae:
                results["errors"].append(f"{panel_name}: Service not available")
                continue
            lines_result = await ae.get_all_lines()
            if not lines_result.get("success"):
                results["errors"].append(f"{panel_name}: {lines_result.get('error', 'Failed to fetch lines')}")
                continue
            synced_count = 0
            updated_count = 0
            for line in lines_result.get("lines", []):
                username = line.get("username", "")
                if not username:
                    continue
                r = await safe_upsert_imported_user(
                    {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                    _aether_line_to_doc(line, panel_index, panel_name),
                )
                if r.upserted_id:
                    synced_count += 1
                elif r.modified_count:
                    updated_count += 1
            await _aether_ensure_streaming_url(ae, panel, panel_index, lines_result.get("lines", []))
            results["panels_synced"].append({"name": panel_name, "type": "aether", "synced": synced_count, "updated": updated_count})
            results["total_synced"] += synced_count
            results["total_updated"] += updated_count
        except Exception as e:
            logger.error(f"Error syncing from {panel_name}: {e}")
            results["errors"].append(f"{panel_name}: {str(e)}")

    # Check for orphaned users from removed panels (don't auto-delete — let admin decide)
    active_xtream_panel_names = [p.get("name") for p in xtream_panels]
    active_xuione_panel_names = [p.get("name") for p in xuione_panels]
    active_onestream_panel_names = [p.get("name") for p in onestream_panels]
    active_nxtdash_panel_names = [p.get("name") for p in nxtdash_panels]
    active_ghostsurf_panel_names = [p.get("name") for p in ghostsurf_panels]
    active_aether_panel_names = [p.get("name") for p in aether_panels]
    all_active_panel_names = active_xtream_panel_names + active_xuione_panel_names + active_onestream_panel_names + active_nxtdash_panel_names + active_ghostsurf_panel_names + active_aether_panel_names

    orphaned_count = 0
    orphaned_panels = []
    for ptype, active_names in [("xtream", active_xtream_panel_names), ("xuione", active_xuione_panel_names), ("onestream", active_onestream_panel_names), ("nxtdash", active_nxtdash_panel_names), ("ghostsurf", active_ghostsurf_panel_names), ("aether", active_aether_panel_names)]:
        count = await imported_users_collection.count_documents({
            "panel_type": ptype,
            "panel_name": {"$nin": active_names}
        })
        if count > 0:
            # Get the orphaned panel names
            orphan_names = await imported_users_collection.distinct("panel_name", {
                "panel_type": ptype,
                "panel_name": {"$nin": active_names}
            })
            orphaned_count += count
            for name in orphan_names:
                orphaned_panels.append({"panel_name": name, "panel_type": ptype, "user_count": await imported_users_collection.count_documents({"panel_type": ptype, "panel_name": name})})

    # Also count null panel_type orphans
    orphan_null = await imported_users_collection.count_documents({
        "$or": [
            {"panel_type": None, "panel_name": {"$nin": all_active_panel_names}},
            {"panel_type": {"$exists": False}, "panel_name": {"$nin": all_active_panel_names}}
        ]
    })
    orphaned_count += orphan_null

    results["total_removed"] = 0
    results["orphaned_users"] = orphaned_count
    results["orphaned_panels"] = orphaned_panels
    
    logger.info(f"Sync all users complete: {results['total_synced']} new, {results['total_updated']} updated, {orphaned_count} orphaned from removed panels")
    
    # Auto-create customer accounts for newly synced users
    try:
        unlinked = imported_users_collection.find({"$or": [{"user_id": {"$exists": False}}, {"user_id": ""}]})
        unlinked_list = await unlinked.to_list(length=10000)
        accounts_created = 0
        for iu in unlinked_list:
            try:
                uid = await create_customer_for_imported_user(iu)
                if uid:
                    accounts_created += 1
            except Exception:
                pass
        if accounts_created > 0:
            logger.info(f"Auto-created {accounts_created} customer accounts from synced users")
        results["accounts_created"] = accounts_created
    except Exception as e:
        logger.warning(f"Account creation after sync failed: {e}")
        results["accounts_created"] = 0
    
    return results

@app.post("/api/admin/xtream/import-usernames")
async def import_xtream_usernames(request: Request, panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Import users by username via lookup_line API (for API-key panels). Accepts single username or CSV list."""
    settings = await get_settings()
    panels = settings.get("xtream", {}).get("panels", [])
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    panel = panels[panel_index]
    if not panel.get("api_key"):
        raise HTTPException(status_code=400, detail="This panel doesn't have an API key configured. Use Sync Users for standard panels.")
    
    panel_name = panel.get("name", f"Panel {panel_index + 1}")
    body = await request.json()
    usernames_raw = body.get("usernames", [])
    
    # Accept string (single or CSV) or list
    if isinstance(usernames_raw, str):
        # Split by comma, newline, semicolon, space, tab
        import re as re_mod
        usernames_raw = re_mod.split(r'[,;\n\r\t ]+', usernames_raw)
    
    # Clean and deduplicate
    usernames = list(set(u.strip() for u in usernames_raw if u.strip()))
    
    if not usernames:
        raise HTTPException(status_code=400, detail="No usernames provided")
    
    imported = 0
    updated = 0
    not_found = []
    errors = []
    
    for username in usernames:
        try:
            data = await _xtream_api_call(panel, "lookup_line", {"username": username})
            line = data.get("data", data) if isinstance(data, dict) else data
            
            if not isinstance(line, dict) or not line.get("username"):
                not_found.append(username)
                continue
            
            # Parse expiry
            expiry_date = None
            exp_val = line.get("exp_date") or line.get("expiry", "")
            if exp_val:
                if isinstance(exp_val, (int, float)) and exp_val > 0:
                    expiry_date = datetime.utcfromtimestamp(exp_val)
                elif isinstance(exp_val, str):
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                        try:
                            expiry_date = datetime.strptime(exp_val.split(".")[0].replace("Z", ""), fmt)
                            break
                        except ValueError:
                            continue
            
            status = "active"
            if line.get("status") == "disabled" or line.get("is_suspended"):
                status = "suspended"
            elif expiry_date and expiry_date < datetime.utcnow():
                status = "expired"
            
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "xtream",
                "panel_name": panel_name,
                "xtream_user_id": line.get("id") or line.get("user_id", 0),
                "username": line.get("username", username),
                "password": line.get("password", ""),
                "expiry_date": expiry_date,
                "status": status,
                "max_connections": safe_int(line.get("max_connections", 1)),
                "account_type": "subscriber",
                "last_synced": datetime.utcnow()
            }
            
            result = await safe_upsert_imported_user(
                {"username": username, "panel_type": "xtream", "panel_index": panel_index, "account_type": "subscriber"},
                user_doc,
            )
            if result.upserted_id:
                imported += 1
            elif result.modified_count:
                updated += 1
        except Exception as e:
            err_msg = str(e)
            if "not found" in err_msg.lower() or "not owned" in err_msg.lower():
                not_found.append(username)
            else:
                errors.append(f"{username}: {err_msg}")
    
    return {
        "message": f"Imported {imported} new, updated {updated}, not found {len(not_found)} from {panel_name}",
        "imported": imported,
        "updated": updated,
        "not_found": not_found,
        "errors": errors,
        "total_checked": len(usernames)
    }


@app.post("/api/admin/xtream/sync-users")
async def sync_users_from_panel(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Sync users and subresellers from XtreamUI panel to billing system (1:1 mirror)"""
    settings = await get_settings()
    panels = settings.get("xtream", {}).get("panels", [])
    
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail="Invalid panel index")
    
    panel = panels[panel_index]
    panel_name = panel.get("name", f"Panel {panel_index + 1}")
    
    # API-key panels: use lookup_line per known user
    if panel.get("api_key"):
        synced_count = 0
        updated_count = 0
        
        # Get all known usernames for this panel
        known_usernames = set()
        async for iu in imported_users_collection.find({"panel_type": "xtream", "panel_index": panel_index}, {"username": 1}):
            if iu.get("username"):
                known_usernames.add(iu["username"])
        async for svc in services_collection.find({"panel_type": "xtream", "panel_index": panel_index}, {"xtream_username": 1}):
            if svc.get("xtream_username"):
                known_usernames.add(svc["xtream_username"])
        
        if not known_usernames:
            return {
                "message": f"No known users for {panel_name}. This API doesn't support listing all users. Users are tracked automatically when provisioned through this billing system, or you can import users via CSV.",
                "synced": 0, "updated": 0, "removed": 0, "total": 0,
                "panel_name": panel_name
            }
        
        logger.info(f"Refreshing {len(known_usernames)} known users for {panel_name} via lookup_line")
        
        for username in known_usernames:
            try:
                data = await _xtream_api_call(panel, "lookup_line", {"username": username})
                line = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(line, dict) and line.get("username"):
                    expiry_date = None
                    exp_val = line.get("exp_date") or line.get("expiry", "")
                    if exp_val:
                        if isinstance(exp_val, (int, float)) and exp_val > 0:
                            expiry_date = datetime.utcfromtimestamp(exp_val)
                        elif isinstance(exp_val, str):
                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                                try:
                                    expiry_date = datetime.strptime(exp_val.split(".")[0].replace("Z",""), fmt)
                                    break
                                except ValueError:
                                    continue
                    
                    status = "active"
                    if line.get("status") == "disabled" or line.get("is_suspended"):
                        status = "suspended"
                    elif expiry_date and expiry_date < datetime.utcnow():
                        status = "expired"
                    
                    user_doc = {
                        "panel_index": panel_index, "panel_type": "xtream", "panel_name": panel_name,
                        "xtream_user_id": line.get("id") or line.get("user_id", 0),
                        "username": username, "password": line.get("password", ""),
                        "expiry_date": expiry_date, "status": status,
                        "max_connections": safe_int(line.get("max_connections", 1)),
                        "account_type": "subscriber", "last_synced": datetime.utcnow()
                    }
                    result = await safe_upsert_imported_user(
                        {"username": username, "panel_type": "xtream", "panel_index": panel_index, "account_type": "subscriber"},
                        user_doc,
                    )
                    if result.upserted_id:
                        synced_count += 1
                    elif result.modified_count:
                        updated_count += 1
            except Exception:
                pass
        
        return {
            "message": f"Refreshed {updated_count} users, added {synced_count} new from {panel_name} ({len(known_usernames)} checked via lookup_line)",
            "synced": synced_count, "updated": updated_count, "removed": 0, "total": len(known_usernames),
            "panel_name": panel_name
        }
    
    # Initialize XtreamUI service
    xtream_service = get_xtream_service(panel)
    
    if not xtream_service:
        raise HTTPException(status_code=500, detail="XtreamUI service not available")
    
    synced_count = 0
    updated_count = 0
    removed_count = 0
    total_users = 0
    
    # Track all usernames found in XtreamUI for cleanup
    xtream_subscriber_usernames = set()
    xtream_reseller_usernames = set()
    
    # === SYNC SUBSCRIBERS (users table) ===
    result = xtream_service.get_reseller_users()
    
    if result.get("success"):
        users_data = result.get("users", [])
        total_users += len(users_data)
        
        for user_data in users_data:
            username = user_data.get("username", "")
            if not username:
                continue
            
            xtream_subscriber_usernames.add(username)
            
            # Parse expiry date - handle multiple formats
            expiry_str = user_data.get("expiry", "")
            expiry_date = None
            if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                expiry_str = str(expiry_str).strip()
                # Try epoch timestamp first (integer or string of digits)
                try:
                    epoch = int(expiry_str)
                    if epoch > 0:
                        expiry_date = datetime.utcfromtimestamp(epoch)
                except (ValueError, TypeError, OSError):
                    pass
                
                # Try date string formats
                if not expiry_date:
                    date_formats = [
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M",
                        "%Y-%m-%d",
                    ]
                    for fmt in date_formats:
                        try:
                            expiry_date = datetime.strptime(expiry_str, fmt)
                            break
                        except ValueError:
                            continue
            
            # Determine status
            status = "active"
            if expiry_date and expiry_date < datetime.utcnow():
                status = "expired"
            elif "suspend" in user_data.get("status", "").lower():
                status = "suspended"
            
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "xtream",
                "panel_name": panel_name,
                "username": username,
                "password": user_data.get("password", ""),
                "expiry_date": expiry_date,
                "status": status,
                "max_connections": safe_int(user_data.get("max_connections", 1)),
                "account_type": "subscriber",
                "xtream_user_id": user_data.get("user_id", 0),
                "last_synced": datetime.utcnow()
            }
            
            result_up = await safe_upsert_imported_user(
                {"username": username, "panel_name": panel_name, "account_type": "subscriber"},
                user_doc,
            )
            if result_up.upserted_id:
                synced_count += 1
            elif result_up.modified_count:
                updated_count += 1
    # === SYNC SUBRESELLERS (reg_users table) ===
    reseller_result = xtream_service.get_subresellers()
    reseller_synced = 0
    reseller_updated = 0
    
    if reseller_result.get("success"):
        resellers_data = reseller_result.get("users", [])
        total_users += len(resellers_data)
        
        for reseller_data in resellers_data:
            username = reseller_data.get("username", "")
            if not username:
                continue
            
            xtream_reseller_usernames.add(username)
            
            # Parse expiry - resellers usually have "NEVER"
            expiry_str = reseller_data.get("expiry", "NEVER")
            expiry_date = None
            if expiry_str and str(expiry_str).strip() not in ["Unlimited", "NEVER", "", "None", "null", "0"]:
                # Try multiple date formats
                date_formats = [
                    "%Y-%m-%d %H:%M:%S",  # Full datetime
                    "%Y-%m-%d",            # Date only
                ]
                for fmt in date_formats:
                    try:
                        expiry_date = datetime.strptime(expiry_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
            
            reseller_doc = {
                "panel_index": panel_index,
                "panel_type": "xtream",
                "panel_name": panel_name,
                "username": username,
                "password": "",
                "expiry_date": expiry_date,
                "status": "active",
                "credits": float(reseller_data.get("credits", 0) or 0),
                "member_group": reseller_data.get("member_group", ""),
                "owner": reseller_data.get("owner", ""),
                "account_type": "reseller",
                "xtream_user_id": reseller_data.get("user_id", 0),
                "last_synced": datetime.utcnow()
            }
            
            result_up = await safe_upsert_imported_user(
                {"username": username, "panel_name": panel_name, "account_type": "reseller"},
                reseller_doc,
            )
            if result_up.upserted_id:
                reseller_synced += 1
                synced_count += 1
            elif result_up.modified_count:
                reseller_updated += 1
                updated_count += 1
    
    # === CLEANUP: Remove users that no longer exist in XtreamUI ===
    # This ensures the billing panel is a 1:1 mirror of XtreamUI
    
    # Remove subscribers that no longer exist
    if xtream_subscriber_usernames:  # Only cleanup if we got valid data
        stale_subscribers = await imported_users_collection.find({
            "panel_index": panel_index,
            "account_type": "subscriber",
            "username": {"$nin": list(xtream_subscriber_usernames)}
        }).to_list(None)
        
        if stale_subscribers:
            stale_ids = [s["_id"] for s in stale_subscribers]
            await imported_users_collection.delete_many({"_id": {"$in": stale_ids}})
            removed_count += len(stale_subscribers)
    
    # Remove resellers that no longer exist (only if we got valid reseller data)
    # Note: Empty reseller list is valid (e.g., no direct subresellers)
    stale_resellers = await imported_users_collection.find({
        "panel_index": panel_index,
        "account_type": "reseller",
        "username": {"$nin": list(xtream_reseller_usernames)}
    }).to_list(None)
    
    if stale_resellers:
        stale_ids = [s["_id"] for s in stale_resellers]
        await imported_users_collection.delete_many({"_id": {"$in": stale_ids}})
        removed_count += len(stale_resellers)
    
    # Auto-create customer accounts for newly synced users
    accounts_created = 0
    try:
        unlinked = imported_users_collection.find({
            "panel_name": panel_name,
            "$or": [{"user_id": {"$exists": False}}, {"user_id": ""}, {"user_id": None}]
        })
        unlinked_list = await unlinked.to_list(length=10000)
        for iu in unlinked_list:
            try:
                uid = await create_customer_for_imported_user(iu)
                if uid:
                    accounts_created += 1
            except Exception:
                pass
        if accounts_created > 0:
            logger.info(f"Auto-created {accounts_created} customer accounts from {panel_name} sync")
    except Exception as e:
        logger.warning(f"Account creation after panel sync failed: {e}")
    
    return {
        "success": True,
        "synced": synced_count,
        "updated": updated_count,
        "removed": removed_count,
        "total": total_users,
        "accounts_created": accounts_created,
        "panel_name": panel_name,
        "details": {
            "subscribers": {"synced": synced_count - reseller_synced, "updated": updated_count - reseller_updated},
            "resellers": {"synced": reseller_synced, "updated": reseller_updated},
            "removed": removed_count
        }
    }

@app.get("/api/admin/imported-users")
async def get_imported_users(panel_index: Optional[int] = None, current_user: dict = Depends(get_current_admin_user)):
    """Get all imported XtreamUI users"""
    query = {}
    if panel_index is not None:
        query["panel_index"] = panel_index
    
    users = []
    async for user in imported_users_collection.find(query).sort([("panel_index", 1), ("username", 1)]):
        user["id"] = str(user["_id"])
        del user["_id"]
        users.append(user)
    
    return users

@app.post("/api/admin/imported-users/{user_id}/suspend")
async def suspend_imported_user(user_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Suspend an imported user on XtreamUI or XuiOne panel"""
    user = await imported_users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get panel settings
    settings = await get_settings()
    panel_type = user.get("panel_type", "xtream")
    panel_index = user.get("panel_index", 0)
    
    if panel_type == "xtream":
        # XtreamUI suspension
        panels = settings.get("xtream", {}).get("panels", [])
        
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        
        panel = panels[panel_index]
        xtream_service = XtreamUIService(
            panel_url=panel["panel_url"],
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", ""),
            api_key=panel.get("api_key", "")
        )
        
        # Use stored user_id if available
        xtream_user_id = user.get("xtream_user_id")
        
        result = xtream_service.suspend_account(
            username=user["username"],
            password=user.get("password", ""),
            user_id=str(xtream_user_id) if xtream_user_id else None
        )
        
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User suspended successfully on XtreamUI panel"}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to suspend"))
    
    elif panel_type == "xuione":
        # XuiOne suspension
        panels = settings.get("xuione", {}).get("panels", [])
        
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        
        panel = panels[panel_index]
        xuione_service = XuiOneService(
            panel_url=panel["panel_url"],
            api_access_code=panel.get("api_access_code", ""),
            api_key=panel.get("api_key", ""),
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"]
        )
        
        # Login and disable line
        if xuione_service.login():
            line_id = user.get("xtream_user_id")  # XuiOne line ID
            if line_id:
                api_url = xuione_service.get_api_url()
                response = xuione_service.session.post(
                    api_url,
                    params={'api_key': xuione_service.api_key, 'action': 'edit_line'},
                    data={'id': str(line_id), 'enabled': '0'},
                    timeout=30
                )
                
                if response.status_code == 200:
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(user_id)},
                        {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
                    )
                    return {"message": "User suspended successfully on XuiOne panel"}
                else:
                    raise HTTPException(status_code=500, detail=f"XuiOne API error: {response.status_code}")
            else:
                raise HTTPException(status_code=400, detail="User ID not found for XuiOne line")
        else:
            raise HTTPException(status_code=500, detail="XuiOne login failed")
    
    elif panel_type == "onestream":
        panels = settings.get("onestream", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        os_service = get_onestream_service(panels[panel_index])
        if not os_service:
            raise HTTPException(status_code=500, detail="1-Stream service not available")
        line_id = user.get("onestream_line_id", "")
        if not line_id:
            find_r = os_service.find_line(user["username"], user.get("password", ""))
            line_id = find_r.get("line_id", "") if find_r.get("success") else ""
        if not line_id:
            raise HTTPException(status_code=400, detail="Could not find line_id on 1-Stream")
        result = os_service.disable_line(line_id)
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User suspended successfully on 1-Stream panel"}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to suspend"))

    elif panel_type == "nxtdash":
        # NXT Dash reseller API cannot disable lines - only panel admins can
        # Update local status for tracking, but warn the admin
        await imported_users_collection.update_one(
            {"_id": str_to_objectid(user_id)},
            {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
        )
        return {"message": "User marked as suspended locally. Note: NXT Dash reseller API cannot disable lines — please disable the line directly in the NXT Dash admin panel."}

    elif panel_type == "aether":
        panels = settings.get("aether", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        ae = get_aether_service(panels[panel_index])
        if not ae:
            raise HTTPException(status_code=500, detail="Aether service not available")
        result = await ae.suspend_line(user["username"])
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User suspended successfully on Aether panel"}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to suspend"))

    else:
        raise HTTPException(status_code=400, detail=f"Unknown panel type: {panel_type}")

@app.post("/api/admin/imported-users/{user_id}/activate")
async def activate_imported_user(user_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Activate/enable an imported user on XtreamUI or XuiOne panel"""
    user = await imported_users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get panel settings
    settings = await get_settings()
    panel_type = user.get("panel_type", "xtream")
    panel_index = user.get("panel_index", 0)
    
    if panel_type == "xtream":
        # XtreamUI activation
        panels = settings.get("xtream", {}).get("panels", [])
        
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        
        panel = panels[panel_index]
        xtream_service = XtreamUIService(
            panel_url=panel["panel_url"],
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", ""),
            api_key=panel.get("api_key", "")
        )
        
        # Use stored user_id if available
        xtream_user_id = user.get("xtream_user_id")
        
        result = xtream_service.unsuspend_account(
            username=user["username"],
            password=user.get("password", ""),
            user_id=str(xtream_user_id) if xtream_user_id else None
        )
        
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User activated successfully on XtreamUI panel"}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to activate"))
    
    elif panel_type == "xuione":
        # XuiOne activation
        panels = settings.get("xuione", {}).get("panels", [])
        
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        
        panel = panels[panel_index]
        xuione_service = XuiOneService(
            panel_url=panel["panel_url"],
            api_access_code=panel.get("api_access_code", ""),
            api_key=panel.get("api_key", ""),
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"]
        )
        
        # Login and enable line
        if xuione_service.login():
            line_id = user.get("xtream_user_id")  # XuiOne line ID
            if line_id:
                api_url = xuione_service.get_api_url()
                response = xuione_service.session.post(
                    api_url,
                    params={'api_key': xuione_service.api_key, 'action': 'edit_line'},
                    data={'id': str(line_id), 'enabled': '1'},  # Enable with enabled=1
                    timeout=30
                )
                
                if response.status_code == 200:
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(user_id)},
                        {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
                    )
                    return {"message": "User activated successfully on XuiOne panel"}
                else:
                    raise HTTPException(status_code=500, detail=f"XuiOne API error: {response.status_code}")
            else:
                raise HTTPException(status_code=400, detail="User ID not found for XuiOne line")
        else:
            raise HTTPException(status_code=500, detail="XuiOne login failed")
    
    elif panel_type == "onestream":
        panels = settings.get("onestream", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        os_service = get_onestream_service(panels[panel_index])
        if not os_service:
            raise HTTPException(status_code=500, detail="1-Stream service not available")
        line_id = user.get("onestream_line_id", "")
        if not line_id:
            find_r = os_service.find_line(user["username"], user.get("password", ""))
            line_id = find_r.get("line_id", "") if find_r.get("success") else ""
        if not line_id:
            raise HTTPException(status_code=400, detail="Could not find line_id on 1-Stream")
        result = os_service.enable_line(line_id)
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User activated successfully on 1-Stream panel"}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to activate"))

    elif panel_type == "nxtdash":
        # NXT Dash reseller API cannot enable lines - only panel admins can
        # Update local status for tracking, but warn the admin
        await imported_users_collection.update_one(
            {"_id": str_to_objectid(user_id)},
            {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
        )
        return {"message": "User marked as active locally. Note: NXT Dash reseller API cannot enable lines — please enable the line directly in the NXT Dash admin panel."}

    elif panel_type == "aether":
        panels = settings.get("aether", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        ae = get_aether_service(panels[panel_index])
        if not ae:
            raise HTTPException(status_code=500, detail="Aether service not available")
        result = await ae.unsuspend_line(user["username"])
        if result.get("success"):
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
            )
            return {"message": "User activated successfully on Aether panel"}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to activate"))

    else:
        raise HTTPException(status_code=400, detail=f"Unknown panel type: {panel_type}")

class AddCreditsRequest(BaseModel):
    credits: float

@app.post("/api/admin/imported-users/{user_id}/add-credits")
async def add_credits_to_imported_user(user_id: str, data: AddCreditsRequest, current_user: dict = Depends(get_current_admin_user)):
    """Add credits to a reseller on the panel"""
    user = await imported_users_collection.find_one({"_id": str_to_objectid(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.get("account_type") != "reseller":
        raise HTTPException(status_code=400, detail="Credits can only be added to resellers")

    settings = await get_settings()
    panel_type = user.get("panel_type", "xtream")
    panel_index = user.get("panel_index", 0)
    username = user.get("username", "")
    credits = data.credits

    if panel_type == "xtream":
        panels = settings.get("xtream", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        panel = panels[panel_index]
        from xtreamui_session_client import XtreamUISessionClient
        client = XtreamUISessionClient(
            panel_url=panel["panel_url"],
            username=panel["admin_username"],
            password=panel["admin_password"],
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", "")
        )
        result = client.add_credits(username=username, email="", credits=credits)
        if result.get("success"):
            new_credits = float(user.get("credits", 0) or 0) + credits
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"credits": new_credits, "last_synced": datetime.utcnow()}}
            )
            return {"message": f"Added {credits} credits to {username}", "new_credits": new_credits}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to add credits"))

    elif panel_type == "onestream":
        panels = settings.get("onestream", {}).get("panels", [])
        if panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid panel")
        os_service = get_onestream_service(panels[panel_index])
        if not os_service:
            raise HTTPException(status_code=500, detail="1-Stream service not available")
        # Find the 1-Stream user_id
        os_user_id = user.get("onestream_user_id")
        if not os_user_id:
            resellers = os_service.get_subresellers()
            if resellers.get("success"):
                for r in resellers.get("users", []):
                    if r.get("username") == username:
                        os_user_id = r.get("user_id")
                        break
        if not os_user_id:
            raise HTTPException(status_code=400, detail="Could not find reseller on 1-Stream panel")
        result = os_service.update_subreseller_credits(os_user_id, credits)
        if result.get("success"):
            new_credits = float(user.get("credits", 0) or 0) + credits
            await imported_users_collection.update_one(
                {"_id": str_to_objectid(user_id)},
                {"$set": {"credits": new_credits, "onestream_user_id": os_user_id, "last_synced": datetime.utcnow()}}
            )
            return {"message": f"Added {credits} credits to {username}", "new_credits": new_credits}
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to add credits"))

    else:
        raise HTTPException(status_code=400, detail=f"Credits not supported for {panel_type} panels")

# ===== UPDATE SYSTEM ENDPOINTS =====

from update_manager import update_manager

@app.get("/api/admin/updates/check")
async def check_for_updates(current_user: dict = Depends(get_current_admin_user)):
    """Check if updates are available from GitHub"""
    result = update_manager.check_for_updates()
    return result

@app.post("/api/admin/updates/apply")
async def apply_update(current_user: dict = Depends(get_current_admin_user)):
    """Apply available updates with backup"""
    try:
        # Create backup first
        backup_path = update_manager.create_backup()
        
        # Apply update
        result = update_manager.apply_update(backup_path)
        
        if result.get("success"):
            # Return success response first
            response_data = {
                "message": "Update applied successfully! Services will restart in 5 seconds.",
                "version": result.get("version"),
                "success": True
            }
            
            # Schedule restart after response is sent (increased delay for production)
            import threading
            def restart_delayed():
                import time
                time.sleep(5)  # Increased from 3 to 5 seconds for production
                logger.info("Restarting services after update...")
                try:
                    update_manager.restart_services()
                except Exception as e:
                    logger.error(f"Failed to restart services: {e}")
            
            thread = threading.Thread(target=restart_delayed)
            thread.daemon = True
            thread.start()
            
            logger.info("Update response sent, restart scheduled")
            return response_data
        else:
            return {
                "message": f"Update failed: {result.get('error')}",
                "error": result.get("error"),
                "success": False
            }
            
    except Exception as e:
        logger.error(f"Update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/updates/backups/{backup_name}")
async def delete_backup(backup_name: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete a backup"""
    backup_path = f"{update_manager.backup_dir}/{backup_name}"
    
    logger.info(f"Attempting to delete backup: {backup_path}")
    logger.info(f"Backup dir: {update_manager.backup_dir}")
    logger.info(f"Backup exists: {os.path.exists(backup_path)}")
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    try:
        import shutil
        shutil.rmtree(backup_path)
        logger.info(f"✓ Deleted backup: {backup_name}")
        return {"message": f"Backup {backup_name} deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete backup {backup_name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to delete backup: {e}")

@app.get("/api/admin/updates/backups")
async def list_backups(current_user: dict = Depends(get_current_admin_user)):
    """List available backups"""
    backups = update_manager.list_backups()
    return {"backups": backups}

@app.post("/api/admin/updates/rollback/{backup_name}")
async def rollback_to_backup(backup_name: str, current_user: dict = Depends(get_current_admin_user)):
    """Rollback to a specific backup"""
    backup_path = f"/app/backups/{backup_name}"
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    success = update_manager.rollback(backup_path)
    
    if success:
        # Restart services
        import threading
        def restart_delayed():
            import time
            time.sleep(2)
            update_manager.restart_services()
        
        thread = threading.Thread(target=restart_delayed)
        thread.start()
        
        return {"message": "Rollback successful. Services will restart in 2 seconds."}
    else:
        raise HTTPException(status_code=500, detail="Rollback failed")

# ===== BACKUP MANAGEMENT ENDPOINTS =====
from backup_manager import backup_manager

@app.post("/api/admin/backups/create")
async def create_manual_backup(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Create a manual backup"""
    description = data.get("description", "")
    result = backup_manager.create_manual_backup(description)
    
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Backup creation failed"))

@app.get("/api/admin/backups/list")
async def list_all_backups(current_user: dict = Depends(get_current_admin_user)):
    """List all backups (manual and auto)"""
    backups = backup_manager.list_backups()
    return {"backups": backups}

@app.post("/api/admin/backups/restore/{backup_name}")
async def restore_from_backup(backup_name: str, current_user: dict = Depends(get_current_admin_user)):
    """Restore from a backup"""
    success = backup_manager.restore_backup(backup_name)
    
    if success:
        # Restart services
        import threading
        def restart_delayed():
            import time
            time.sleep(2)
            update_manager.restart_services()
        
        thread = threading.Thread(target=restart_delayed)
        thread.start()
        
        return {"message": "Backup restored successfully. Services will restart in 2 seconds."}
    else:
        raise HTTPException(status_code=500, detail="Restore failed")

@app.delete("/api/admin/backups/{backup_name}")
async def delete_backup_endpoint(backup_name: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete a backup"""
    success = backup_manager.delete_backup(backup_name)
    
    if success:
        return {"message": "Backup deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete backup")

@app.get("/api/admin/backups/settings")
async def get_backup_settings(current_user: dict = Depends(get_current_admin_user)):
    """Get backup settings"""
    settings = backup_manager.load_settings()
    
    # Don't send sensitive credentials to frontend
    safe_settings = {
        "cloud_backup_enabled": settings.get("cloud_backup_enabled", False),
        "cloud_provider": settings.get("cloud_provider", ""),
        "auto_backup_enabled": settings.get("auto_backup_enabled", False),
        "backup_retention_days": settings.get("backup_retention_days", 30)
    }
    
    return safe_settings

@app.post("/api/admin/backups/settings")
async def update_backup_settings(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Update backup settings"""
    settings = backup_manager.load_settings()
    
    # Update settings
    if "cloud_backup_enabled" in data:
        settings["cloud_backup_enabled"] = data["cloud_backup_enabled"]
    if "cloud_provider" in data:
        settings["cloud_provider"] = data["cloud_provider"]
    if "auto_backup_enabled" in data:
        settings["auto_backup_enabled"] = data["auto_backup_enabled"]
    if "backup_retention_days" in data:
        settings["backup_retention_days"] = data["backup_retention_days"]
    
    # Store cloud credentials securely
    if "dropbox_access_token" in data:
        settings["dropbox_access_token"] = data["dropbox_access_token"]
    if "google_drive_credentials" in data:
        settings["google_drive_credentials"] = data["google_drive_credentials"]
    if "google_drive_service_account" in data:
        settings["google_drive_service_account"] = data["google_drive_service_account"]
    if "google_drive_auth_type" in data:
        settings["google_drive_auth_type"] = data["google_drive_auth_type"]
    if "proton_drive" in data:
        settings["proton_drive"] = data["proton_drive"]
    
    success = backup_manager.save_settings(settings)
    
    if success:
        return {"message": "Settings saved successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save settings")

@app.post("/api/admin/backups/test-cloud")
async def test_cloud_connection_endpoint(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Test cloud storage connection"""
    provider = data.get("provider")
    credentials = data.get("credentials", {})
    
    if not provider:
        raise HTTPException(status_code=400, detail="Provider required")
    
    result = backup_manager.test_cloud_connection(provider, credentials)
    
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Connection test failed"))

@app.get("/api/admin/backups/{backup_name}/download")
async def download_backup(backup_name: str, current_user: dict = Depends(get_current_admin_user)):
    """Download a backup as ZIP archive"""
    import tempfile
    import zipfile
    from fastapi.responses import FileResponse
    
    # Detect app directory
    if os.path.exists("/opt/backend"):
        app_dir = "/opt"
    else:
        app_dir = "/app"
    
    backup_path = f"{app_dir}/backups/{backup_name}"
    
    if not os.path.exists(backup_path):
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Create temporary ZIP file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    temp_zip_path = temp_zip.name
    temp_zip.close()
    
    try:
        # Create ZIP archive
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_path)
                    zipf.write(file_path, arcname)
        
        # Return as downloadable file
        return FileResponse(
            temp_zip_path,
            media_type='application/zip',
            filename=f"{backup_name}.zip"
        )
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        raise HTTPException(status_code=500, detail=f"Failed to create download: {str(e)}")

@app.delete("/api/admin/imported-users/{user_id}")
async def delete_imported_user(user_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete an imported user from the billing panel only (does NOT delete from XtreamUI)"""
    user = await imported_users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Delete from billing panel database only
    await imported_users_collection.delete_one({"_id": str_to_objectid(user_id)})
    
    return {"message": f"User '{user.get('username')}' removed from billing panel"}


@app.post("/api/admin/imported-users/bulk-action")
async def bulk_action_imported_users(data: dict, current_user: dict = Depends(get_current_admin_user)):
    """Perform bulk actions on imported users: suspend, activate, delete"""
    action = data.get("action")  # "suspend", "activate", "delete"
    user_ids = data.get("user_ids", [])

    if not action or not user_ids:
        raise HTTPException(status_code=400, detail="action and user_ids required")
    if action not in ("suspend", "activate", "delete"):
        raise HTTPException(status_code=400, detail="action must be suspend, activate, or delete")

    success = 0
    failed = 0
    settings = await get_settings()

    for uid in user_ids:
        try:
            user = await imported_users_collection.find_one({"_id": str_to_objectid(uid)})
            if not user:
                failed += 1
                continue

            panel_type = user.get("panel_type", "")

            if action == "delete":
                await imported_users_collection.delete_one({"_id": str_to_objectid(uid)})
                success += 1

            elif action == "suspend":
                if panel_type == "nxtdash":
                    # NXT Dash can't suspend via API — local only
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(uid)},
                        {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
                    )
                elif panel_type == "aether":
                    ae_panels = settings.get("aether", {}).get("panels", [])
                    pi = safe_panel_index(user.get("panel_index"))
                    ae = get_aether_service(ae_panels[pi]) if pi < len(ae_panels) else None
                    if not ae or not (await ae.suspend_line(user["username"])).get("success"):
                        failed += 1
                        continue
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(uid)},
                        {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
                    )
                elif panel_type == "xtream":
                    try:
                        panels = settings.get("xtream", {}).get("panels", [])
                        pi = user.get("panel_index", 0)
                        if pi < len(panels):
                            svc = XtreamUIService(
                                panel_url=panels[pi]["panel_url"],
                                admin_username=panels[pi]["admin_username"],
                                admin_password=panels[pi]["admin_password"],
                                http_basic_user=panels[pi].get("http_basic_user", ""),
                                http_basic_pass=panels[pi].get("http_basic_pass", ""),
                                proxy_url=panels[pi].get("proxy_url", ""),
                            )
                            svc.suspend_account(user["username"], user.get("password", ""))
                    except Exception:
                        pass
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(uid)},
                        {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
                    )
                else:
                    await imported_users_collection.update_one(
                        {"_id": str_to_objectid(uid)},
                        {"$set": {"status": "suspended", "last_synced": datetime.utcnow()}}
                    )
                success += 1

            elif action == "activate":
                if panel_type == "aether":
                    ae_panels = settings.get("aether", {}).get("panels", [])
                    pi = safe_panel_index(user.get("panel_index"))
                    ae = get_aether_service(ae_panels[pi]) if pi < len(ae_panels) else None
                    if not ae or not (await ae.unsuspend_line(user["username"])).get("success"):
                        failed += 1
                        continue
                elif panel_type == "xtream":
                    try:
                        panels = settings.get("xtream", {}).get("panels", [])
                        pi = user.get("panel_index", 0)
                        if pi < len(panels):
                            svc = XtreamUIService(
                                panel_url=panels[pi]["panel_url"],
                                admin_username=panels[pi]["admin_username"],
                                admin_password=panels[pi]["admin_password"],
                                http_basic_user=panels[pi].get("http_basic_user", ""),
                                http_basic_pass=panels[pi].get("http_basic_pass", ""),
                                proxy_url=panels[pi].get("proxy_url", ""),
                            )
                            svc.unsuspend_account(user["username"], user.get("password", ""))
                    except Exception:
                        pass
                await imported_users_collection.update_one(
                    {"_id": str_to_objectid(uid)},
                    {"$set": {"status": "active", "last_synced": datetime.utcnow()}}
                )
                success += 1

        except Exception as e:
            logger.warning(f"Bulk {action} failed for {uid}: {e}")
            failed += 1

    return {"success": True, "action": action, "processed": success, "failed": failed, "total": len(user_ids)}


# Pydantic model for extending imported users
class ExtendImportedUserRequest(BaseModel):
    package_id: int  # Required - the package to extend by

@app.post("/api/admin/imported-users/{user_id}/extend")
async def extend_imported_user(user_id: str, data: ExtendImportedUserRequest, current_user: dict = Depends(get_current_admin_user)):
    """Extend an imported user's subscription on both billing system and panel"""
    
    user = await imported_users_collection.find_one({"_id": str_to_objectid(user_id)})
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user details
    username = user.get("username")
    password = user.get("password")
    panel_type = user.get("panel_type", "xtream")
    panel_index = user.get("panel_index", 0)
    
    # Get current expiry date for response
    current_expiry = user.get("expiry_date")
    
    # Get settings and panel info
    settings = await get_settings()
    days_to_add = 0
    panel_extend_result = None
    
    try:
        if panel_type == "xtream":
            xtream_settings = settings.get("xtream", {})
            panels = xtream_settings.get("panels", [])
            
            if not panels or panel_index >= len(panels):
                raise HTTPException(status_code=400, detail="Panel configuration not found")
            
            panel = panels[panel_index]
            
            # Use XtreamUISessionClient to get packages (same as sync endpoint)
            from xtreamui_session_client import XtreamUISessionClient as ExtendSessionClient
            session_client = ExtendSessionClient(
                panel_url=panel["panel_url"],
                username=panel["admin_username"],
                password=panel["admin_password"],
                http_basic_user=panel.get("http_basic_user", ""),
                http_basic_pass=panel.get("http_basic_pass", ""),
                proxy_url=panel.get("proxy_url", "")
            )
            
            # Fetch packages using the same method as sync endpoint
            packages_list = session_client.fetch_packages()
            
            selected_package = None
            bouquets = []
            max_connections = 1
            
            logger.info(f"Looking for package ID {data.package_id} in {len(packages_list)} packages")
            
            for pkg in packages_list:
                logger.info(f"  Package: id={pkg.get('id')}, name={pkg.get('name')}")
                if str(pkg.get("id")) == str(data.package_id):
                    selected_package = pkg
                    duration_val = pkg.get("duration", "1")
                    duration_unit = pkg.get("duration_unit", "months")
                    
                    try:
                        duration = int(duration_val)
                        if duration_unit == "days":
                            days_to_add = duration
                        elif duration_unit == "years":
                            days_to_add = duration * 365
                        else:  # months
                            days_to_add = duration * 30
                    except (ValueError, TypeError):
                        days_to_add = 30
                    
                    max_connections = int(pkg.get("max_connections", 1))
                    bouquets = pkg.get("bouquets", [])
                    break
            
            if not selected_package:
                logger.error(f"Package {data.package_id} not found in packages: {[p.get('id') for p in packages_list]}")
                raise HTTPException(status_code=400, detail=f"Package not found. Available packages: {[p.get('id') for p in packages_list]}")
            
            logger.info(f"Found package: {selected_package.get('name')}, duration={days_to_add} days")
            
            # Call the panel's extend subscriber method
            logger.info(f"Extending subscriber {username} on XtreamUI panel with package {data.package_id}")
            
            panel_extend_result = session_client.extend_subscriber(
                username=username,
                password=password,
                package_id=data.package_id,
                bouquets=bouquets,  # Package bouquets from panel API
                max_connections=max_connections,
                reseller_notes=f"Extended by Admin - {current_user.get('email', 'Unknown')}"
            )
            
            if not panel_extend_result.get("success"):
                logger.error(f"Panel extend failed: {panel_extend_result.get('error')}")
                raise HTTPException(status_code=500, detail=f"Failed to extend on panel: {panel_extend_result.get('error', 'Unknown error')}")
            
            logger.info(f"✓ Panel extension successful: {panel_extend_result}")
            
        elif panel_type == "xuione":
            xuione_settings = settings.get("xuione", {})
            panels = xuione_settings.get("panels", [])
            
            if not panels or panel_index >= len(panels):
                raise HTTPException(status_code=400, detail="Panel configuration not found")
            
            panel = panels[panel_index]
            
            # Initialize XuiOne service
            xuione_service = XuiOneService(
                panel_url=panel["panel_url"],
                api_access_code=panel.get("api_access_code", ""),
                api_key=panel.get("api_key", ""),
                admin_username=panel["admin_username"],
                admin_password=panel["admin_password"],
                ssl_verify=panel.get("ssl_verify", False)
            )
            
            # Get package details
            packages_result = xuione_service.get_packages()
            selected_package = None
            
            if packages_result.get("success"):
                for pkg in packages_result.get("packages", []):
                    if str(pkg.get("id")) == str(data.package_id):
                        selected_package = pkg
                        duration_val = pkg.get("duration", "1")
                        duration_unit = pkg.get("duration_unit", "months")
                        
                        try:
                            duration = int(duration_val)
                            if duration_unit == "days":
                                days_to_add = duration
                            elif duration_unit == "years":
                                days_to_add = duration * 365
                            else:  # months
                                days_to_add = duration * 30
                        except (ValueError, TypeError):
                            days_to_add = 30
                        break
            
            if not selected_package:
                raise HTTPException(status_code=400, detail="Package not found")
            
            # XuiOne extension via service method
            logger.info(f"Extending XuiOne line {username} with package {data.package_id}")
            
            panel_extend_result = xuione_service.extend_line(username, data.package_id)
            
            if not panel_extend_result.get("success"):
                error_msg = panel_extend_result.get("error", "Unknown error")
                logger.error(f"XuiOne extend failed: {error_msg}")
                raise HTTPException(status_code=500, detail=f"Failed to extend on panel: {error_msg}")
            
            logger.info(f"✓ XuiOne extension successful")
        
        elif panel_type == "onestream":
            onestream_settings = settings.get("onestream", {})
            panels = onestream_settings.get("panels", [])
            if not panels or panel_index >= len(panels):
                raise HTTPException(status_code=400, detail="Panel configuration not found")
            panel = panels[panel_index]
            os_service = get_onestream_service(panel)
            if not os_service:
                raise HTTPException(status_code=500, detail="1-Stream service not available")

            # Get packages to find the selected one
            pkg_result = os_service.get_packages()
            selected_package = None
            if pkg_result.get("success"):
                for pkg in pkg_result.get("packages", []) + pkg_result.get("trial_packages", []):
                    if str(pkg.get("id")) == str(data.package_id):
                        selected_package = pkg
                        duration_hours = pkg.get("duration_hours", 0)
                        if duration_hours >= 24:
                            days_to_add = duration_hours // 24
                        else:
                            days_to_add = max(1, duration_hours // 24)
                        break
            if not selected_package:
                raise HTTPException(status_code=400, detail="Package not found")

            # Find line_id for this user
            line_id = user.get("onestream_line_id", "")
            if not line_id:
                find_result = os_service.find_line(username, password)
                if find_result.get("success"):
                    line_id = find_result.get("line_id", "")
            if not line_id:
                raise HTTPException(status_code=400, detail="Could not find line_id for this user on 1-Stream panel")

            panel_extend_result = os_service.renew_line(line_id, data.package_id)
            if not panel_extend_result.get("success"):
                raise HTTPException(status_code=500, detail=f"Failed to extend on panel: {panel_extend_result.get('error')}")
            logger.info(f"✓ 1-Stream extension successful")

        elif panel_type == "nxtdash":
            nd_panels = settings.get("nxtdash", {}).get("panels", [])
            if not nd_panels or panel_index >= len(nd_panels):
                raise HTTPException(status_code=400, detail="Panel configuration not found")
            panel = nd_panels[panel_index]
            nd_service = get_nxtdash_service(panel)
            if not nd_service:
                raise HTTPException(status_code=500, detail="NXT Dash service not available")

            line_id = user.get("nxtdash_line_id", "")
            if not line_id:
                line_id = await nd_service.get_line_id(username, password)
            if not line_id:
                raise HTTPException(status_code=400, detail="Could not find line_id for this user on NXT Dash panel")

            panel_extend_result = await nd_service.extend_line(str(line_id), int(data.package_id))
            if not panel_extend_result.get("success"):
                raise HTTPException(status_code=500, detail=f"Failed to extend on panel: {panel_extend_result.get('error')}")
            logger.info(f"✓ NXT Dash extension successful")

        elif panel_type == "aether":
            ae_panels = settings.get("aether", {}).get("panels", [])
            if not ae_panels or panel_index >= len(ae_panels):
                raise HTTPException(status_code=400, detail="Panel configuration not found")
            ae = get_aether_service(ae_panels[panel_index])
            if not ae:
                raise HTTPException(status_code=500, detail="Aether service not available")

            pkg_kind = "official"
            pkgs = await ae.get_packages()
            for p in pkgs.get("all_packages", []):
                if str(p["id"]) == str(data.package_id):
                    pkg_kind = p["kind"]
                    if p["duration_unit"] == "months":
                        days_to_add = int(p["duration"]) * 30
                    elif p["duration_unit"] == "years":
                        days_to_add = int(p["duration"]) * 365
                    elif p["duration_unit"] == "hours":
                        days_to_add = max(1, int(p["duration"]) // 24)
                    else:
                        days_to_add = int(p["duration"])
                    break
            if pkg_kind == "trial":
                raise HTTPException(status_code=400, detail="A trial package cannot be used to renew a line")

            panel_extend_result = await ae.renew_line(
                username, int(data.package_id), kind=pkg_kind,
                idem_key=f"billing-admin-extend-{user_id}-{data.package_id}-{int(datetime.utcnow().timestamp())}",
            )
            if not panel_extend_result.get("success"):
                status_code = 429 if panel_extend_result.get("code") == "rate_limited" else 500
                raise HTTPException(status_code=status_code, detail=f"Failed to extend on panel: {panel_extend_result.get('error')}")
            logger.info("✓ Aether renewal successful")

        else:
            raise HTTPException(status_code=400, detail="Invalid panel type")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extending user on panel: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to extend on panel: {str(e)}")
    
    # Get actual expiry from panel after extension
    new_expiry = None
    
    # First try to use expiry returned directly from the extend result
    if panel_extend_result and panel_extend_result.get("new_expiry"):
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                new_expiry = datetime.strptime(str(panel_extend_result["new_expiry"]).strip(), fmt)
                logger.info(f"Using expiry from extend result: {new_expiry}")
                break
            except (ValueError, TypeError):
                continue
    
    # Fallback: fetch from panel
    if not new_expiry:
        try:
            if panel_type == "xtream":
                from xtreamui_session_client import XtreamUISessionClient
                fetch_client = XtreamUISessionClient(
                    panel_url=panel["panel_url"],
                    username=panel["admin_username"],
                    password=panel["admin_password"],
                    http_basic_user=panel.get("http_basic_user", ""),
                    http_basic_pass=panel.get("http_basic_pass", ""),
                    proxy_url=panel.get("proxy_url", "")
                )
                user_info = fetch_client.get_user_info(username)
                if user_info and user_info.get("exp_date"):
                    exp_str = user_info["exp_date"]
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                        try:
                            new_expiry = datetime.strptime(str(exp_str).strip(), fmt)
                            break
                        except ValueError:
                            continue
            elif panel_type == "onestream" and panel_extend_result.get("expire_at"):
                exp_at = panel_extend_result["expire_at"]
                new_expiry = datetime.fromisoformat(exp_at.replace("Z", "+00:00"))
                if new_expiry.tzinfo:
                    new_expiry = new_expiry.replace(tzinfo=None)
            elif panel_type == "xuione":
                lines_result = xuione_service.get_users()
                if lines_result.get("success"):
                    for u in lines_result.get("users", []):
                        if u.get("username") == username:
                            exp_str = u.get("expiry", "")
                            if exp_str and exp_str not in ["Unlimited", "NEVER"]:
                                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                                    try:
                                        new_expiry = datetime.strptime(str(exp_str).strip(), fmt)
                                        break
                                    except ValueError:
                                        continue
                            break
            elif panel_type == "nxtdash" and panel_extend_result and panel_extend_result.get("expire_date"):
                try:
                    from datetime import timezone
                    new_expiry = datetime.fromtimestamp(int(panel_extend_result["expire_date"]), tz=timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass
            elif panel_type == "aether" and panel_extend_result and panel_extend_result.get("new_expiry"):
                new_expiry = panel_extend_result["new_expiry"]
        except Exception as e:
            logger.warning(f"Could not fetch panel expiry after extend: {e}")
    
    # Fallback: calculate if panel didn't return expiry
    if not new_expiry:
        if current_expiry is None:
            current_expiry = datetime.utcnow()
        elif isinstance(current_expiry, str):
            current_expiry = datetime.fromisoformat(current_expiry.replace('Z', '+00:00'))
        if current_expiry < datetime.utcnow():
            current_expiry = datetime.utcnow()
        new_expiry = current_expiry + timedelta(days=days_to_add)
    
    # Update the user in billing database
    await imported_users_collection.update_one(
        {"_id": str_to_objectid(user_id)},
        {
            "$set": {
                "expiry_date": new_expiry,
                "status": "active",  # Reactivate if was expired
                "last_synced": datetime.utcnow()
            }
        }
    )
    
    logger.info(f"Admin {current_user.get('email')} extended user {username} by {days_to_add} days")
    
    return {
        "success": True,
        "message": f"Subscription extended by {days_to_add} days on both billing system and panel",
        "previous_expiry": user.get("expiry_date").isoformat() if user.get("expiry_date") else None,
        "new_expiry": new_expiry.isoformat(),
        "days_added": days_to_add,
        "panel_extended": True
    }

# Pydantic model for creating imported users
class CreateImportedUserRequest(BaseModel):
    panel_type: str = "xtream"  # 'xtream', 'xuione', 'onestream', or 'nxtdash'
    panel_index: int = 0
    account_type: str = "subscriber"  # 'subscriber' or 'reseller'
    username: Optional[str] = None  # Auto-generate if not provided
    password: Optional[str] = None  # Auto-generate if not provided
    # For subscribers
    package_id: Optional[int] = None
    duration_months: Optional[int] = 1
    max_connections: Optional[int] = 1
    # For resellers
    credits: Optional[float] = 0.0
    member_group_id: Optional[int] = 2

@app.post("/api/admin/imported-users/create")
async def create_imported_user(data: CreateImportedUserRequest, current_user: dict = Depends(get_current_admin_user)):
    """Create a new user directly on the panel and add to imported_users collection"""
    
    settings = await get_settings()
    
    # Generate credentials if not provided
    username = data.username or generate_username()
    password = data.password or generate_password()
    
    panel_type = data.panel_type
    panel_index = data.panel_index
    
    if panel_type == "xtream":
        # XtreamUI panel
        xtream_settings = settings.get("xtream", {})
        panels = xtream_settings.get("panels", [])
        
        if not panels or panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid XtreamUI panel index")
        
        panel = panels[panel_index]
        panel_name = panel.get("name", f"XtreamUI Panel {panel_index + 1}")
        
        # Initialize XtreamUI service
        xtream_service = XtreamUIService(
            panel_url=panel["panel_url"],
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            ssl_verify=panel.get("ssl_verify", False),
            http_basic_user=panel.get("http_basic_user", ""),
            http_basic_pass=panel.get("http_basic_pass", ""),
            proxy_url=panel.get("proxy_url", ""),
            api_key=panel.get("api_key", "")
        )
        
        if data.account_type == "subscriber":
            if not data.package_id:
                raise HTTPException(status_code=400, detail="package_id is required for subscriber creation")
            
            # Fetch package details to get duration and max_connections
            package_duration = 1  # Default 1 month
            package_max_connections = 1  # Default 1 connection
            
            try:
                # Get packages from panel to find the selected one
                packages_result = xtream_service.get_packages()
                if packages_result.get("success"):
                    for pkg in packages_result.get("packages", []):
                        if str(pkg.get("id")) == str(data.package_id):
                            # Parse duration from package
                            duration_val = pkg.get("duration", "1")
                            duration_unit = pkg.get("duration_unit", "months")
                            try:
                                package_duration = int(duration_val)
                                # Convert to months if needed
                                if duration_unit == "days":
                                    package_duration = max(1, package_duration // 30)
                                elif duration_unit == "years":
                                    package_duration = package_duration * 12
                            except (ValueError, TypeError):
                                package_duration = 1
                            
                            # Get max connections
                            try:
                                package_max_connections = int(pkg.get("max_connections", "1"))
                            except (ValueError, TypeError):
                                package_max_connections = 1
                            break
            except Exception as e:
                logger.warning(f"Could not fetch package details: {e}")
            
            # Get bouquets from a product or use all
            bouquets = [1]  # Default bouquet
            
            # Create subscriber using form method
            result = xtream_service.create_subscriber_via_form(
                username=username,
                password=password,
                package_id=data.package_id,
                bouquets=bouquets,
                customer_name=f"Manual - {current_user.get('email', 'Admin')}"
            )
            
            if not result.get("success"):
                raise HTTPException(status_code=500, detail=result.get("error", "Failed to create subscriber on panel"))
            
            # Calculate expiry date using package duration
            expiry_date = datetime.utcnow() + timedelta(days=package_duration * 30)
            
            # Insert into imported_users collection
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "xtream",
                "panel_name": panel_name,
                "xtream_user_id": int(result.get("user_id", 0)),
                "username": username,
                "password": password,
                "expiry_date": expiry_date,
                "status": "active",
                "max_connections": package_max_connections,
                "account_type": "subscriber",
                "created_by_reseller": None,
                "last_synced": datetime.utcnow(),
                "created_at": datetime.utcnow()
            }
            
            await imported_users_collection.insert_one(user_doc)
            
            return {
                "success": True,
                "message": f"Subscriber '{username}' created successfully on {panel_name}",
                "user": {
                    "username": username,
                    "password": password,
                    "panel_name": panel_name,
                    "expiry_date": expiry_date.isoformat(),
                    "account_type": "subscriber",
                    "max_connections": package_max_connections,
                    "duration_months": package_duration
                }
            }
        
        else:  # reseller
            # Create reseller
            result = xtream_service.create_reseller(
                username=username,
                password=password,
                credits=data.credits or 0.0,
                email="",
                member_group_id=data.member_group_id or 2
            )
            
            if not result.get("success"):
                raise HTTPException(status_code=500, detail=result.get("error", "Failed to create reseller on panel"))
            
            # Insert into imported_users collection
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "xtream",
                "panel_name": panel_name,
                "xtream_user_id": int(result.get("user_id", 0)),
                "username": username,
                "password": password,
                "expiry_date": None,  # Resellers don't expire
                "status": "active",
                "credits": data.credits,
                "account_type": "reseller",
                "member_group": f"Group {data.member_group_id}",
                "last_synced": datetime.utcnow(),
                "created_at": datetime.utcnow()
            }
            
            await imported_users_collection.insert_one(user_doc)
            
            return {
                "success": True,
                "message": f"Reseller '{username}' created successfully on {panel_name}",
                "user": {
                    "username": username,
                    "password": password,
                    "panel_name": panel_name,
                    "credits": data.credits,
                    "account_type": "reseller"
                }
            }
    
    elif panel_type == "xuione":
        # XuiOne panel
        xuione_settings = settings.get("xuione", {})
        panels = xuione_settings.get("panels", [])
        
        if not panels or panel_index >= len(panels):
            raise HTTPException(status_code=400, detail="Invalid XuiOne panel index")
        
        panel = panels[panel_index]
        panel_name = panel.get("name", f"XuiOne Panel {panel_index + 1}")
        
        # Initialize XuiOne service
        xuione_service = XuiOneService(
            panel_url=panel["panel_url"],
            api_access_code=panel.get("api_access_code", ""),
            api_key=panel.get("api_key", ""),
            admin_username=panel["admin_username"],
            admin_password=panel["admin_password"],
            ssl_verify=panel.get("ssl_verify", False)
        )
        
        if data.account_type == "subscriber":
            if not data.package_id:
                raise HTTPException(status_code=400, detail="package_id is required for subscriber creation")
            
            if not xuione_service.api_key:
                raise HTTPException(status_code=400, detail="XuiOne API key is required for creating subscribers")
            
            # Login first
            if not xuione_service.logged_in:
                if not xuione_service.login():
                    raise HTTPException(status_code=500, detail="Failed to login to XuiOne panel")
            
            # Fetch package details to get duration and max_connections
            package_duration = 1  # Default 1 month
            package_max_connections = 1  # Default 1 connection
            
            try:
                # Get packages from panel to find the selected one
                packages_result = xuione_service.get_packages()
                if packages_result.get("success"):
                    for pkg in packages_result.get("packages", []):
                        if str(pkg.get("id")) == str(data.package_id):
                            # Parse duration from package
                            duration_val = pkg.get("duration", "1")
                            duration_unit = pkg.get("duration_unit", "months")
                            try:
                                package_duration = int(duration_val)
                                # Convert to months if needed
                                if duration_unit == "days":
                                    package_duration = max(1, package_duration // 30)
                                elif duration_unit == "years":
                                    package_duration = package_duration * 12
                            except (ValueError, TypeError):
                                package_duration = 1
                            
                            # Get max connections
                            try:
                                package_max_connections = int(pkg.get("max_connections", "1"))
                            except (ValueError, TypeError):
                                package_max_connections = 1
                            break
            except Exception as e:
                logger.warning(f"Could not fetch XuiOne package details: {e}")
            
            # Calculate expiry date using package duration
            expiry_date = datetime.utcnow() + timedelta(days=package_duration * 30)
            
            # Use XuiOne API to create line
            api_url = xuione_service.get_api_url()
            
            request_data = {
                'username': username,
                'password': password,
                'package': str(data.package_id),
                'trial': '0',
                'reseller_notes': f'Manual Creation - {current_user.get("email", "Admin")}',
                'is_isplock': '0'
            }
            
            response = xuione_service.session.post(
                api_url,
                params={
                    'api_key': xuione_service.api_key,
                    'action': 'create_line'
                },
                data=request_data,
                timeout=30
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail=f"XuiOne API error: HTTP {response.status_code}")
            
            try:
                result = response.json()
                if result.get('status') != 'STATUS_SUCCESS':
                    raise HTTPException(status_code=500, detail=result.get("message", "Failed to create line"))
            except ValueError:
                raise HTTPException(status_code=500, detail="Invalid response from XuiOne API")
            
            # Insert into imported_users collection
            user_doc = {
                "panel_index": panel_index,
                "panel_type": "xuione",
                "panel_name": panel_name,
                "xtream_user_id": result.get("data", {}).get("id", 0),
                "username": username,
                "password": password,
                "expiry_date": expiry_date,
                "status": "active",
                "max_connections": package_max_connections,
                "account_type": "subscriber",
                "last_synced": datetime.utcnow(),
                "created_at": datetime.utcnow()
            }
            
            await imported_users_collection.insert_one(user_doc)
            
            return {
                "success": True,
                "message": f"Subscriber '{username}' created successfully on {panel_name}",
                "user": {
                    "username": username,
                    "password": password,
                    "panel_name": panel_name,
                    "expiry_date": expiry_date.isoformat(),
                    "account_type": "subscriber",
                    "max_connections": package_max_connections,
                    "duration_months": package_duration
                }
            }
        
        else:  # reseller for XuiOne - might not be supported via API
            raise HTTPException(status_code=400, detail="Reseller creation is not currently supported for XuiOne panels via API")
    
    elif panel_type == "onestream":
        os_panels = settings.get("onestream", {}).get("panels", [])
        if not os_panels or panel_index >= len(os_panels):
            raise HTTPException(status_code=400, detail="Invalid 1-Stream panel index")
        panel = os_panels[panel_index]
        panel_name = panel.get("name", f"1-Stream Panel {panel_index + 1}")
        os_service = get_onestream_service(panel)
        if not os_service:
            raise HTTPException(status_code=500, detail="1-Stream service not available")

        if data.account_type == "subscriber":
            if not data.package_id:
                raise HTTPException(status_code=400, detail="package_id is required for subscriber creation")

            # Get package details
            pkg_result = os_service.get_packages()
            package_duration_hours = 720  # default 30 days
            package_max_connections = 1
            if pkg_result.get("success"):
                for pkg in pkg_result.get("packages", []) + pkg_result.get("trial_packages", []):
                    if str(pkg.get("id")) == str(data.package_id):
                        package_duration_hours = pkg.get("duration_hours", 720)
                        package_max_connections = pkg.get("max_connections", 1)
                        break

            result = os_service.create_line(
                username=username, password=password,
                package_id=data.package_id,
                reseller_notes=f"Manual - {current_user.get('email', 'Admin')}",
                max_connections=data.max_connections or package_max_connections
            )
            if not result.get("success"):
                raise HTTPException(status_code=500, detail=result.get("error", "Failed to create line on 1-Stream"))

            expiry_date = datetime.utcnow() + timedelta(hours=package_duration_hours)
            if result.get("expire_at"):
                try:
                    expiry_date = datetime.fromisoformat(result["expire_at"].replace("Z", "+00:00"))
                except Exception:
                    pass

            user_doc = {
                "panel_index": panel_index, "panel_type": "onestream", "panel_name": panel_name,
                "onestream_line_id": result.get("line_id", ""),
                "username": username, "password": password,
                "expiry_date": expiry_date, "status": "active",
                "max_connections": package_max_connections, "account_type": "subscriber",
                "last_synced": datetime.utcnow(), "created_at": datetime.utcnow()
            }
            await imported_users_collection.insert_one(user_doc)
            return {
                "success": True,
                "message": f"Subscriber '{username}' created on {panel_name}",
                "user": {"username": username, "password": password, "panel_name": panel_name,
                         "expiry_date": expiry_date.isoformat(), "account_type": "subscriber",
                         "max_connections": package_max_connections}
            }

        else:  # reseller
            result = os_service.create_subreseller(
                name=username, email=f"{username}@billing.local",
                password=password, credits=data.credits or 0,
                notes=f"Manual - {current_user.get('email', 'Admin')}"
            )
            if not result.get("success"):
                raise HTTPException(status_code=500, detail=result.get("error", "Failed to create reseller on 1-Stream"))

            user_doc = {
                "panel_index": panel_index, "panel_type": "onestream", "panel_name": panel_name,
                "onestream_user_id": result.get("user_id", 0),
                "username": username, "password": password,
                "expiry_date": None, "status": "active", "credits": data.credits,
                "account_type": "reseller", "last_synced": datetime.utcnow(), "created_at": datetime.utcnow()
            }
            await imported_users_collection.insert_one(user_doc)
            return {
                "success": True,
                "message": f"Reseller '{username}' created on {panel_name}",
                "user": {"username": username, "password": password, "panel_name": panel_name,
                         "credits": data.credits, "account_type": "reseller"}
            }

    elif panel_type == "nxtdash":
        nd_panels = settings.get("nxtdash", {}).get("panels", [])
        if not nd_panels or panel_index >= len(nd_panels):
            raise HTTPException(status_code=400, detail="Invalid NXT Dash panel index")
        panel = nd_panels[panel_index]
        panel_name = panel.get("name", f"NXT Dash Panel {panel_index + 1}")
        nd_service = get_nxtdash_service(panel)
        if not nd_service:
            raise HTTPException(status_code=500, detail="NXT Dash service not available")

        if data.account_type != "subscriber":
            raise HTTPException(status_code=400, detail="NXT Dash only supports subscriber creation via API")

        if not data.package_id:
            raise HTTPException(status_code=400, detail="package_id is required for subscriber creation")

        is_trial = False
        # Check if this is a trial package
        trial_result = await nd_service.get_packages(trial=True)
        if trial_result.get("success"):
            for pkg in trial_result.get("packages", []):
                if str(pkg.get("id")) == str(data.package_id):
                    is_trial = True
                    break

        result = await nd_service.create_line(
            username=username, password=password,
            package_id=int(data.package_id),
            description=f"Manual - {current_user.get('email', 'Admin')}",
            is_trial=is_trial,
        )
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create line on NXT Dash"))

        expire_ts = result.get("expire_date")
        expiry_str = ""
        if expire_ts:
            try:
                from datetime import timezone
                expiry_str = datetime.fromtimestamp(int(expire_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                expiry_str = ""

        user_doc = {
            "panel_index": panel_index, "panel_type": "nxtdash", "panel_name": panel_name,
            "nxtdash_line_id": result.get("line_id", ""),
            "username": result.get("username", username),
            "password": result.get("password", password),
            "expiry_date": expiry_str, "status": "active",
            "max_connections": data.max_connections or 1, "account_type": "subscriber",
            "last_synced": datetime.utcnow(), "created_at": datetime.utcnow()
        }
        await imported_users_collection.insert_one(user_doc)
        return {
            "success": True,
            "message": f"Subscriber '{result.get('username', username)}' created on {panel_name}",
            "user": {"username": result.get("username", username), "password": result.get("password", password),
                     "panel_name": panel_name, "expiry_date": expiry_str, "account_type": "subscriber",
                     "max_connections": data.max_connections or 1}
        }

    elif panel_type == "aether":
        ae_panels = settings.get("aether", {}).get("panels", [])
        if not ae_panels or panel_index >= len(ae_panels):
            raise HTTPException(status_code=400, detail="Invalid Aether panel index")
        panel = ae_panels[panel_index]
        panel_name = panel.get("name", f"Aether Panel {panel_index + 1}")
        ae = get_aether_service(panel)
        if not ae:
            raise HTTPException(status_code=500, detail="Aether service not available")

        if data.account_type != "subscriber":
            raise HTTPException(status_code=400, detail="Aether only supports subscriber (line) creation via API")
        if not data.package_id:
            raise HTTPException(status_code=400, detail="package_id is required for subscriber creation")

        result = await ae.create_line(
            package_id=int(data.package_id),
            username=data.username or username, password=data.password or password,
            notes=f"Manual - {current_user.get('email', 'Admin')}",
            idem_key=f"billing-admin-create-{uuid.uuid4().hex}",
        )
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create line on Aether"))

        api_user = result.get("username") or username
        api_pass = result.get("password") or password
        expiry_dt = AetherService.parse_exp(result.get("exp_date"))
        max_conn = data.max_connections or 1
        for p in (await ae.get_packages()).get("all_packages", []):
            if str(p["id"]) == str(data.package_id):
                max_conn = p.get("max_connections", max_conn)
                break

        user_doc = {
            "panel_index": panel_index, "panel_type": "aether", "panel_name": panel_name,
            "aether_line_id": result.get("line_id", ""), "aether_package_id": int(data.package_id),
            "username": api_user, "password": api_pass,
            "expiry_date": expiry_dt, "status": "active",
            "max_connections": max_conn, "account_type": "subscriber",
            "last_synced": datetime.utcnow(), "created_at": datetime.utcnow()
        }
        await imported_users_collection.insert_one(user_doc)
        return {
            "success": True,
            "message": f"Subscriber '{api_user}' created on {panel_name}",
            "user": {"username": api_user, "password": api_pass, "panel_name": panel_name,
                     "expiry_date": expiry_dt.strftime("%Y-%m-%d %H:%M:%S") if expiry_dt else "",
                     "account_type": "subscriber", "max_connections": max_conn}
        }

    else:
        raise HTTPException(status_code=400, detail="Invalid panel_type. Must be 'xtream', 'xuione', 'onestream', 'nxtdash', or 'aether'")

@app.get("/api/products/{product_id}/channels")
async def get_product_channels(product_id: str):
    """Get LIVE channel list for a product (public endpoint) - excludes VOD and Series"""
    product = await products_collection.find_one({"_id": str_to_objectid(product_id)})
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Get bouquet IDs from product
    bouquet_ids = product.get("bouquets", [])
    panel_index = product.get("panel_index", 0)
    panel_type = product.get("panel_type", "xtream")
    
    # Get settings
    settings = await get_settings()
    
    # Get bouquets based on panel type
    panel_bouquets = []
    if panel_type == "onestream":
        os_panels = settings.get("onestream", {}).get("panels", [])
        if panel_index < len(os_panels):
            panel_bouquets = os_panels[panel_index].get("bouquets", [])
    elif panel_type == "xuione":
        xuione_panels = settings.get("xuione", {}).get("panels", [])
        if panel_index < len(xuione_panels):
            panel_bouquets = xuione_panels[panel_index].get("bouquets", [])
            if not panel_bouquets:
                # Try fetching from XuiOne API
                try:
                    from xuione_service import get_xuione_service
                    svc = get_xuione_service(xuione_panels[panel_index])
                    if svc:
                        result = svc.get_bouquets()
                        if result.get("success"):
                            panel_bouquets = result.get("bouquets", [])
                except Exception:
                    pass
    elif panel_type == "nxtdash":
        nd_panels = settings.get("nxtdash", {}).get("panels", [])
        if panel_index < len(nd_panels):
            panel_bouquets = nd_panels[panel_index].get("bouquets", [])
    elif panel_type == "aether":
        ae_panels = settings.get("aether", {}).get("panels", [])
        if panel_index < len(ae_panels):
            panel_bouquets = ae_panels[panel_index].get("bouquets", [])
    else:
        # XtreamUI - check panel-specific then legacy
        panel_bouquets_key = f"bouquets_panel_{panel_index}"
        panel_bouquets = settings.get(panel_bouquets_key, [])
        if not panel_bouquets:
            panel_bouquets = settings.get("bouquets", [])
    
    # Get LIVE channel bouquets only (exclude VOD and Series)
    live_channels = []
    for bouquet_id in bouquet_ids:
        bouquet = next((b for b in panel_bouquets if int(b.get("id", 0)) == int(bouquet_id)), None)
        if bouquet:
            bouquet_name = bouquet.get("name", "")
            is_vod_or_series = (
                'movie' in bouquet_name.lower() or
                'series' in bouquet_name.lower() or
                'vod' in bouquet_name.lower() or
                '24/7' in bouquet_name.lower()
            )
            if not is_vod_or_series:
                live_channels.append({
                    "id": bouquet_id,
                    "name": bouquet_name or f"Channel Package {bouquet_id}",
                    "category": bouquet.get("category", "General")
                })
        else:
            # Bouquet not found in stored data - show with ID
            live_channels.append({
                "id": bouquet_id,
                "name": f"Channel Package {bouquet_id}",
                "category": "General"
            })
    
    return {
        "product_name": product.get("name"),
        "channels": live_channels,
        "total_packages": len(live_channels),
        "note": "Live TV channels only (excludes movies and series)"
    }

@app.get("/api/bouquets/{bouquet_id}/channels")
async def get_bouquet_channels(bouquet_id: int, panel_index: int = 0):
    """Get individual channels within a bouquet (public endpoint)"""
    # Note: Individual channel listing requires direct database access or XtreamUI API subscription
    # For now, return a helpful message
    
    # Get bouquet name from settings
    settings = await get_settings()
    panel_bouquets_key = f"bouquets_panel_{panel_index}"
    panel_bouquets = settings.get(panel_bouquets_key, [])
    
    bouquet = next((b for b in panel_bouquets if int(b.get("id")) == int(bouquet_id)), None)
    bouquet_name = bouquet.get("name", f"Package {bouquet_id}") if bouquet else f"Package {bouquet_id}"
    
    return {
        "bouquet_id": bouquet_id,
        "bouquet_name": bouquet_name,
        "channels": [],
        "total": 0,
        "message": f"The {bouquet_name} package includes hundreds of live channels. Channel list available after subscription."
    }

@app.get("/api/admin/packages")
async def get_packages(current_user: dict = Depends(get_current_admin_user)):
    """Get available packages from XtreamUI panel"""
    settings = await get_settings()
    xtream_settings = settings.get("xtream", {})
    
    if not xtream_settings.get("panel_url"):
        raise HTTPException(status_code=400, detail="XtreamUI not configured")
    
    # Fetch from XtreamUI panel
    xtream_service = get_xtream_service(xtream_settings)
    result = xtream_service.get_packages()
    
    if result['success']:
        packages_data = result.get('packages', [])
        return {"packages": packages_data, "source": "xtreamui"}
    else:
        return {"packages": [], "source": "none", "error": result.get('error')}

@app.put("/api/admin/bouquets")
async def update_bouquets(bouquets: List[dict], current_user: dict = Depends(get_current_admin_user)):
    """Update bouquet configuration"""
    existing = await settings_collection.find_one()
    if existing:
        await settings_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {"bouquets": bouquets, "updated_at": datetime.utcnow()}}
        )
    else:
        await settings_collection.insert_one({
            "bouquets": bouquets,
            "updated_at": datetime.utcnow()
        })
    
    return {"message": "Bouquets updated successfully"}

@app.post("/api/admin/xtreamui/test")
async def test_xtreamui_connection(panel_index: int = 0, current_user: dict = Depends(get_current_admin_user)):
    """Test XtreamUI connection"""
    settings = await get_settings()
    xtream_settings = settings.get("xtream", {})
    panels = xtream_settings.get("panels", [])
    
    if not panels or len(panels) == 0:
        raise HTTPException(status_code=400, detail="No XtreamUI panels configured. Please add a panel first.")
    if panel_index >= len(panels):
        raise HTTPException(status_code=400, detail=f"Panel index {panel_index} not found")
    
    panel = panels[panel_index]
    
    # API-key panels: test with get_credits
    if panel.get("api_key"):
        try:
            result = await _xtream_api_call(panel, "get_credits")
            credits = result.get("credits", result.get("balance", "N/A"))
            return {"message": f"Connected to {panel.get('name', 'XtreamUI')} via API! Credits: {credits}"}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"API connection failed: {str(e)}")
    
    # Standard session-based test
    xtream_service = get_xtream_service(panel)
    if not xtream_service:
        raise HTTPException(status_code=400, detail="Failed to initialize XtreamUI service")
    result = xtream_service.test_connection()
    if result.get("success"):
        return {"message": f"Connected to {panel.get('name', 'XtreamUI')} successfully!"}
    raise HTTPException(status_code=400, detail=result.get("error", "Connection failed"))

# ===== REFERRAL SYSTEM ENDPOINTS =====

@app.get("/api/referral/my-code")
async def get_my_referral_code(current_user: dict = Depends(get_current_user)):
    """Get or create user's referral code"""
    user_id = current_user["sub"]
    code = await referral_service.create_referral_code_for_user(user_id)
    
    # Get referral stats
    referrals = await referral_service.get_user_referrals(user_id)
    completed = len([r for r in referrals if r["status"] == "completed"])
    total_earned = sum(r.get("reward_amount", 0) for r in referrals if r.get("rewarded"))
    
    # Get settings for display
    settings = await get_settings()
    referral_settings = settings.get("referral", {})
    credit_settings = settings.get("credit", {})
    
    return {
        "referral_code": code,
        "referral_link": f"{os.getenv('SITE_URL', os.getenv('BACKEND_PUBLIC_URL', ''))}/register?ref={code}",
        "total_referrals": len(referrals),
        "completed_referrals": completed,
        "total_earned": total_earned,
        "referrals": referrals,
        "settings": {
            "referrer_reward": referral_settings.get("referrer_reward", 10.0),
            "referred_reward": referral_settings.get("referred_reward", 5.0),
            "enabled": referral_settings.get("enabled", True),
            "credit_enabled": credit_settings.get("enabled", True)
        }
    }

@app.get("/api/referral/leaderboard")
async def get_referral_leaderboard():
    """Public leaderboard of top referrers"""
    leaderboard = await referral_service.get_leaderboard(limit=10)
    return leaderboard

@app.post("/api/admin/referral/award/{referral_id}")
async def manually_award_referral(referral_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Manually award referral credits (admin)"""
    await referral_service.award_referral_credits(referral_id)
    return {"message": "Referral credits awarded"}

@app.post("/api/admin/referral/fix-stuck")
async def fix_stuck_referrals(current_user: dict = Depends(get_current_admin_user)):
    """Find pending referrals where the referred user already made a purchase, complete them and award credits"""
    fixed = 0
    skipped = 0
    errors = []
    
    async for ref in referrals_collection.find({"status": "pending"}):
        try:
            user = await users_collection.find_one({"email": ref["referred_email"]})
            if not user:
                skipped += 1
                continue
            
            paid = await orders_collection.count_documents({"user_id": str(user["_id"]), "status": "paid"})
            if paid == 0:
                skipped += 1
                continue
            
            # Mark as completed
            await referrals_collection.update_one({"_id": ref["_id"]}, {"$set": {
                "status": "completed",
                "referred_id": str(user["_id"]),
                "completed_at": datetime.utcnow()
            }})
            
            # Award credits if not already rewarded
            if not ref.get("rewarded"):
                await referral_service.award_referral_credits(str(ref["_id"]))
                fixed += 1
            else:
                fixed += 1
        except Exception as e:
            errors.append(f"{ref.get('referred_email')}: {str(e)}")
    
    return {
        "fixed": fixed,
        "skipped": skipped,
        "errors": errors,
        "message": f"Fixed {fixed} stuck referrals, skipped {skipped}"
    }


# ===== COUPON SYSTEM ENDPOINTS =====

class CouponCreate(BaseModel):
    code: str
    coupon_type: str  # percentage or fixed
    value: float
    min_purchase: float = 0.0
    max_uses: Optional[int] = None
    valid_until: Optional[datetime] = None
    applies_to: str = "all"
    product_ids: List[str] = []

@app.post("/api/admin/coupons")
async def create_coupon(coupon_data: CouponCreate, current_user: dict = Depends(get_current_admin_user)):
    """Create a new coupon"""
    # Check if code already exists
    existing = await coupons_collection.find_one({"code": coupon_data.code.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Coupon code already exists")
    
    coupon = {
        "code": coupon_data.code.upper(),
        "coupon_type": coupon_data.coupon_type,
        "value": coupon_data.value,
        "min_purchase": coupon_data.min_purchase,
        "max_uses": coupon_data.max_uses,
        "used_count": 0,
        "valid_from": datetime.utcnow(),
        "valid_until": coupon_data.valid_until,
        "active": True,
        "applies_to": coupon_data.applies_to,
        "product_ids": coupon_data.product_ids,
        "created_by": current_user["sub"],
        "created_at": datetime.utcnow()
    }
    
    result = await coupons_collection.insert_one(coupon)
    return {"message": "Coupon created", "id": str(result.inserted_id), "code": coupon["code"]}

@app.get("/api/admin/coupons")
async def get_all_coupons(current_user: dict = Depends(get_current_admin_user)):
    """Get all coupons"""
    coupons = []
    async for coupon in coupons_collection.find().sort("created_at", -1):
        coupon["id"] = str(coupon["_id"])
        del coupon["_id"]
        
        # Get stats
        stats = await coupon_service.get_coupon_stats(coupon["id"])
        coupon.update(stats)
        
        coupons.append(coupon)
    
    return coupons

@app.post("/api/coupon/validate")
async def validate_coupon_code(data: dict):
    """Validate coupon code (public endpoint for checkout)"""
    code = data.get("code", "")
    order_total = float(data.get("order_total", 0))
    product_ids = data.get("product_ids", [])
    result = await coupon_service.validate_coupon(code, order_total, product_ids)
    return result

@app.delete("/api/admin/coupons/{coupon_id}")
async def delete_coupon(coupon_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete/deactivate a coupon"""
    await coupons_collection.update_one(
        {"_id": str_to_objectid(coupon_id)},
        {"$set": {"active": False}}
    )
    return {"message": "Coupon deactivated"}

# ===== CREDIT SYSTEM ENDPOINTS =====

@app.get("/api/credits/balance")
async def get_credit_balance(current_user: dict = Depends(get_current_user)):
    """Get user's credit balance"""
    balance = await credit_service.get_balance(current_user["sub"])
    return {"balance": balance}

@app.get("/api/credits/history")
async def get_credit_history(limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Get user's credit transaction history"""
    history = await credit_service.get_transaction_history(current_user["sub"], limit)
    return history

@app.post("/api/admin/credits/add")
async def admin_add_credits(
    user_id: str,
    amount: float,
    description: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Admin manually add credits to user"""
    new_balance = await credit_service.add_credits(
        user_id=user_id,
        amount=amount,
        transaction_type="admin_adjustment",
        description=description,
        created_by=current_user["sub"]
    )
    return {"message": f"${amount} credits added", "new_balance": new_balance}

@app.post("/api/admin/credits/deduct")
async def admin_deduct_credits(
    user_id: str,
    amount: float,
    description: str,
    current_user: dict = Depends(get_current_admin_user)
):
    """Admin manually deduct credits from user"""
    new_balance = await credit_service.deduct_credits(
        user_id=user_id,
        amount=amount,
        transaction_type="admin_adjustment",
        description=description
    )
    return {"message": f"${amount} credits deducted", "new_balance": new_balance}

# ===== DOWNLOADS SYSTEM ENDPOINTS =====

class DownloadCreate(BaseModel):
    name: str
    description: str = ""
    category: str
    file_path: str
    file_url: str
    file_size: int
    file_type: str = ""
    version: str = ""
    platform: str = "all"
    requires_active_service: bool = True
    linked_service_types: List[str] = []

@app.post("/api/admin/downloads")
async def create_download(download_data: DownloadCreate, current_user: dict = Depends(get_current_admin_user)):
    """Create a new download"""
    download = {
        "name": download_data.name,
        "description": download_data.description,
        "category": download_data.category,
        "file_path": download_data.file_path,
        "file_url": download_data.file_url,
        "file_size": download_data.file_size,
        "file_type": download_data.file_type,
        "version": download_data.version,
        "platform": download_data.platform,
        "requires_active_service": download_data.requires_active_service,
        "linked_service_types": download_data.linked_service_types,
        "download_count": 0,
        "active": True,
        "created_by": current_user["sub"],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    result = await downloads_collection.insert_one(download)
    return {"message": "Download created", "id": str(result.inserted_id)}

@app.get("/api/admin/downloads")
async def get_all_downloads_admin(current_user: dict = Depends(get_current_admin_user)):
    """Get all downloads (admin)"""
    downloads = []
    async for download in downloads_collection.find().sort("created_at", -1):
        download["id"] = str(download["_id"])
        del download["_id"]
        downloads.append(download)
    return downloads

@app.put("/api/admin/downloads/{download_id}")
async def update_download(
    download_id: str,
    update_data: dict,
    current_user: dict = Depends(get_current_admin_user)
):
    """Update a download"""
    update_data["updated_at"] = datetime.utcnow()
    
    await downloads_collection.update_one(
        {"_id": str_to_objectid(download_id)},
        {"$set": update_data}
    )
    return {"message": "Download updated"}

@app.delete("/api/admin/downloads/{download_id}")
async def delete_download(download_id: str, current_user: dict = Depends(get_current_admin_user)):
    """Delete a download"""
    await downloads_collection.delete_one({"_id": str_to_objectid(download_id)})
    return {"message": "Download deleted"}

@app.get("/api/downloads")
async def get_available_downloads(current_user: dict = Depends(get_current_user)):
    """Get downloads available to user based on products they own"""
    user_id = current_user["sub"]
    
    # Get user's active services and their product IDs
    active_services = []
    user_product_ids = []
    async for service in services_collection.find({"user_id": user_id, "status": "active"}):
        active_services.append(service)
        if service.get("product_id"):
            user_product_ids.append(service["product_id"])
    
    has_active_service = len(active_services) > 0
    
    # Get available downloads
    downloads = []
    async for download in downloads_collection.find({"active": True}).sort("category", 1):
        # Check if user can access this download
        can_access = True
        
        # Check if active service is required
        if download.get("requires_active_service", True) and not has_active_service:
            can_access = False
        
        # Check linked products
        linked_products = download.get("linked_service_types", [])  # Will rename to linked_product_ids
        if linked_products and len(linked_products) > 0:
            # Check if user has any of the required products
            user_has_matching = any(
                product_id in linked_products 
                for product_id in user_product_ids
            )
            if not user_has_matching:
                can_access = False
        
        if can_access:
            download["id"] = str(download["_id"])
            del download["_id"]
            downloads.append(download)
    
    return {
        "downloads": downloads,
        "has_active_service": has_active_service
    }

@app.post("/api/downloads/{download_id}/download")
async def track_download(
    download_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Track download and increment counter"""
    # Log download
    await download_logs_collection.insert_one({
        "download_id": download_id,
        "user_id": current_user["sub"],
        "ip_address": request.client.host,
        "downloaded_at": datetime.utcnow()
    })
    
    # Increment counter
    await downloads_collection.update_one(
        {"_id": str_to_objectid(download_id)},
        {"$inc": {"download_count": 1}}
    )
    
    # Get download info
    download = await downloads_collection.find_one({"_id": str_to_objectid(download_id)})
    
    return {"file_url": download.get("file_url"), "file_name": download.get("name")}

# Note: License generation is done on the separate license server (license.synapse.watch)
# This billing panel only has license STATUS checking and ACTIVATION
# Customers cannot generate their own licenses

# License status endpoint (keep this - needed for activation)
@app.get("/api/license/status")
async def get_license_status():
    """Get current license status (public endpoint for status check)"""
    # Preview/development environments are always licensed
    backend_url = os.getenv("BACKEND_PUBLIC_URL", "")
    if "preview.emergentagent.com" in backend_url or "localhost" in backend_url:
        return {
            "licensed": True,
            "mode": "LICENSED",
            "message": "Development environment"
        }
    
    # Check env var first
    license_key = os.getenv("LICENSE_KEY")
    
    # If not in env, check settings
    if not license_key:
        settings = await get_settings()
        license_key = settings.get("license_key", "")
    
    current_domain = license_manager.get_current_domain()
    
    if not license_key:
        return {
            "licensed": False,
            "mode": "DEMO",
            "message": "No license key configured. Add LICENSE_KEY to environment or Settings → License tab."
        }
    
    validation = await license_manager.validate_license(license_key, current_domain)
    
    return {
        "licensed": validation["valid"],
        "mode": "LICENSED" if validation["valid"] else "DEMO",
        "message": validation.get("reason", "License valid"),
        "expiry_date": validation.get("expiry_date"),
        "customer": validation.get("customer_name")
    }

@app.post("/api/admin/activate-license")
async def save_license_key_endpoint(request: dict):
    """Activate license by saving to settings (public endpoint for initial activation)"""
    license_key = request.get("license_key", "").strip()
    
    if not license_key:
        raise HTTPException(status_code=400, detail="License key is required")
    
    # Validate the license key format
    if not re.match(r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', license_key):
        return {
            "valid": False,
            "reason": "Invalid license key format. Expected: XXXX-XXXX-XXXX-XXXX"
        }
    
    # Validate license with license server
    current_domain = license_manager.get_current_domain()
    validation = await license_manager.validate_license(license_key, current_domain)
    
    if not validation["valid"]:
        return {
            "valid": False,
            "reason": validation.get("reason", "License validation failed")
        }
    
    # Save to settings
    existing = await settings_collection.find_one()
    if existing:
        await settings_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": {"license_key": license_key}}
        )
    else:
        await settings_collection.insert_one({"license_key": license_key})
    
    logger.info(f"License activated successfully for domain: {current_domain}")
    
    return {
        "valid": True,
        "message": "License activated successfully",
        "customer": validation.get("customer_name"),
        "expiry_date": validation.get("expiry_date")
    }

@app.post("/api/admin/upload/download")
async def upload_download_file(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin_user)
):
    """Upload file for downloads section"""
    # Validate file size (max 100MB for client apps)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    
    contents = await file.read()
    file_size = len(contents)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 100MB")
    
    # Create downloads directory dynamically
    DOWNLOADS_DIR = os.path.join(BASE_DIR, "uploads", "downloads")
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(DOWNLOADS_DIR, unique_filename)
    
    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    
    return {
        "filename": file.filename,
        "stored_filename": unique_filename,
        "size": file_size,
        "path": file_path,
        "url": f"{os.getenv('BACKEND_PUBLIC_URL', '')}/api/uploads/downloads/{unique_filename}"
    }

# ===== REFUND SYSTEM ENDPOINTS =====

class RefundRequest(BaseModel):
    order_id: str
    amount: float
    reason: str
    refund_type: str = "full"
    method: str = "credit"

@app.post("/api/refund/request")
async def request_refund_endpoint(
    request: RefundRequest,
    current_user: dict = Depends(get_current_user)
):
    """Customer requests a refund"""
    refund_id = await refund_service.request_refund(
        order_id=request.order_id,
        user_id=current_user["sub"],
        amount=request.amount,
        refund_type=request.refund_type,
        method=request.method,
        reason=request.reason
    )
    return {"message": "Refund request submitted", "refund_id": refund_id}

@app.get("/api/admin/refunds/pending")
async def get_pending_refunds_endpoint(current_user: dict = Depends(get_current_admin_user)):
    """Get all pending refund requests"""
    refunds = await refund_service.get_pending_refunds()
    return refunds

@app.post("/api/admin/refunds/{refund_id}/approve")
async def approve_refund_endpoint(
    refund_id: str,
    notes: str = "",
    current_user: dict = Depends(get_current_admin_user)
):
    """Approve a refund request and cancel associated service"""
    # Get refund details
    refund = await refunds_collection.find_one({"_id": str_to_objectid(refund_id)})
    
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    
    # Approve the refund
    await refund_service.approve_refund(refund_id, current_user["sub"], notes)
    
    # Find and cancel all services associated with this order
    order_id = refund.get("order_id")
    if order_id:
        settings = await get_settings()
        services = await services_collection.find({"order_id": order_id}).to_list(None)
        
        for service in services:
            # Mark service as refunded and suspend on panel
            if service.get("status") in ["active", "suspended"]:
                # Suspend on the actual panel (XtreamUI or XuiOne)
                panel_type = service.get("panel_type", "xtream")
                panel_index = service.get("panel_index", 0)
                
                if panel_type == "xtream":
                    # Suspend on XtreamUI panel
                    xtream_panels = settings.get("xtream", {}).get("panels", [])
                    if panel_index < len(xtream_panels):
                        panel = xtream_panels[panel_index]
                        xtream_service = XtreamUIService(
                            panel_url=panel["panel_url"],
                            admin_username=panel["admin_username"],
                            admin_password=panel["admin_password"],
                            http_basic_user=panel.get("http_basic_user", ""),
                            http_basic_pass=panel.get("http_basic_pass", ""),
                            proxy_url=panel.get("proxy_url", "")
                        )
                        result = xtream_service.suspend_account(
                            username=service["xtream_username"],
                            password=service["xtream_password"],
                            user_id=service.get("dedicatedip")  # Pass the stored XtreamUI user ID
                        )
                        if result.get("success"):
                            logger.info(f"Suspended XtreamUI line {service['xtream_username']}")
                        else:
                            logger.warning(f"Failed to suspend XtreamUI line: {result.get('error')}")
                
                elif panel_type == "xuione":
                    # Suspend on XuiOne panel using edit_line with enabled=0
                    xuione_panels = settings.get("xuione", {}).get("panels", [])
                    if panel_index < len(xuione_panels):
                        panel = xuione_panels[panel_index]
                        xuione_service = XuiOneService(
                            panel_url=panel["panel_url"],
                            api_access_code=panel.get("api_access_code", ""),
                            api_key=panel.get("api_key", ""),
                            admin_username=panel["admin_username"],
                            admin_password=panel["admin_password"]
                        )
                        
                        # Login and suspend line
                        if xuione_service.login():
                            line_id = service.get("dedicatedip") or service.get("xuione_line_id")
                            if line_id:
                                api_url = xuione_service.get_api_url()
                                response = xuione_service.session.post(
                                    api_url,
                                    params={'api_key': xuione_service.api_key, 'action': 'edit_line'},
                                    data={'id': line_id, 'enabled': '0'},  # Disable the line
                                    timeout=30
                                )
                                if response.status_code == 200:
                                    logger.info(f"Suspended XuiOne line {service['xtream_username']}")
                                else:
                                    logger.warning(f"Failed to suspend XuiOne line")
                
                # Mark service as refunded in database
                await services_collection.update_one(
                    {"_id": service["_id"]},
                    {"$set": {
                        "status": "refunded",
                        "refunded_at": datetime.utcnow(),
                        "refund_reason": notes or "Customer request"
                    }}
                )
                logger.info(f"Marked service {service.get('xtream_username')} as refunded")
    
    return {"message": "Refund approved, service(s) suspended on panel"}

@app.post("/api/admin/refunds/{refund_id}/reject")
async def reject_refund_endpoint(
    refund_id: str,
    notes: str = "",
    current_user: dict = Depends(get_current_admin_user)
):
    """Reject a refund request"""
    await refund_service.reject_refund(refund_id, current_user["sub"], notes)
    return {"message": "Refund rejected"}

# ============ USER GUIDE PDF ============
@app.get("/api/admin/user-guide")
async def download_user_guide(current_user=Depends(get_current_admin_user)):
    """Download the admin user guide PDF"""
    import os
    pdf_path = os.path.join(os.path.dirname(__file__), "static", "IPTV_Billing_Admin_User_Guide.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="User guide not found")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="IPTV_Billing_Admin_User_Guide.pdf"
    )

# ============ KNOWLEDGE BASE ============
@app.post("/api/admin/kb")
async def create_kb_article(data: dict, current_user=Depends(get_current_admin_user)):
    article = {
        "id": str(uuid.uuid4()),
        "title": data.get("title", ""),
        "content": data.get("content", ""),
        "category": data.get("category", "General"),
        "is_published": data.get("is_published", True),
        "display_order": data.get("display_order", 0),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    if not article["title"] or not article["content"]:
        raise HTTPException(status_code=400, detail="Title and content are required")
    await db.kb_articles.insert_one(article)
    del article["_id"]
    return article

@app.get("/api/admin/kb")
async def get_admin_kb_articles(current_user=Depends(get_current_admin_user)):
    articles = await db.kb_articles.find({}, {"_id": 0}).sort("display_order", 1).to_list(500)
    return articles

@app.put("/api/admin/kb/{article_id}")
async def update_kb_article(article_id: str, data: dict, current_user=Depends(get_current_admin_user)):
    existing = await db.kb_articles.find_one({"id": article_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    update_data = {
        "title": data.get("title", existing["title"]),
        "content": data.get("content", existing["content"]),
        "category": data.get("category", existing["category"]),
        "is_published": data.get("is_published", existing["is_published"]),
        "display_order": data.get("display_order", existing["display_order"]),
        "updated_at": datetime.utcnow().isoformat(),
    }
    await db.kb_articles.update_one({"id": article_id}, {"$set": update_data})
    return {**update_data, "id": article_id, "created_at": existing["created_at"]}

@app.delete("/api/admin/kb/{article_id}")
async def delete_kb_article(article_id: str, current_user=Depends(get_current_admin_user)):
    result = await db.kb_articles.delete_one({"id": article_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"message": "Article deleted"}

@app.get("/api/kb")
async def get_public_kb_articles():
    articles = await db.kb_articles.find({"is_published": True}, {"_id": 0}).sort("display_order", 1).to_list(500)
    return articles

@app.get("/api/kb/{article_id}")
async def get_public_kb_article(article_id: str):
    article = await db.kb_articles.find_one({"id": article_id, "is_published": True}, {"_id": 0})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


# ============ ANALYTICS ============
@app.get("/api/admin/analytics")
async def get_admin_analytics(period: str = "30d", current_user: dict = Depends(get_current_admin_user)):
    """Get comprehensive revenue analytics"""
    days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    start_date = datetime.utcnow() - timedelta(days=days)
    prev_start = start_date - timedelta(days=days)

    cur_pipeline = [{"$match": {"status": "paid", "paid_at": {"$gte": start_date}}}, {"$group": {"_id": None, "total": {"$sum": "$total"}, "count": {"$sum": 1}}}]
    cur = await orders_collection.aggregate(cur_pipeline).to_list(1)
    cur_revenue = cur[0]["total"] if cur else 0
    cur_orders = cur[0]["count"] if cur else 0

    prev_pipeline = [{"$match": {"status": "paid", "paid_at": {"$gte": prev_start, "$lt": start_date}}}, {"$group": {"_id": None, "total": {"$sum": "$total"}, "count": {"$sum": 1}}}]
    prev = await orders_collection.aggregate(prev_pipeline).to_list(1)
    prev_revenue = prev[0]["total"] if prev else 0
    prev_orders = prev[0]["count"] if prev else 0

    rev_change = ((cur_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0
    order_change = ((cur_orders - prev_orders) / prev_orders * 100) if prev_orders > 0 else 0

    cur_customers = await users_collection.count_documents({"created_at": {"$gte": start_date}, "role": "user"})
    prev_customers = await users_collection.count_documents({"created_at": {"$gte": prev_start, "$lt": start_date}, "role": "user"})
    cust_change = ((cur_customers - prev_customers) / prev_customers * 100) if prev_customers > 0 else 0

    chart_data = []
    for i in range(min(days, 90)):
        d_start = start_date + timedelta(days=i)
        d_end = d_start + timedelta(days=1)
        d_pipe = [{"$match": {"status": "paid", "paid_at": {"$gte": d_start, "$lt": d_end}}}, {"$group": {"_id": None, "total": {"$sum": "$total"}, "count": {"$sum": 1}}}]
        d_res = await orders_collection.aggregate(d_pipe).to_list(1)
        chart_data.append({"date": d_start.strftime("%b %d"), "revenue": round(d_res[0]["total"], 2) if d_res else 0, "orders": d_res[0]["count"] if d_res else 0})

    method_pipeline = [
        {"$match": {"status": "paid", "paid_at": {"$gte": start_date}}},
        {"$group": {"_id": "$payment_method", "total": {"$sum": "$total"}, "count": {"$sum": 1}}}
    ]
    methods = await orders_collection.aggregate(method_pipeline).to_list(20)
    by_method = [{"method": m["_id"] or "unknown", "revenue": round(m["total"], 2), "orders": m["count"]} for m in methods]

    product_pipeline = [
        {"$match": {"status": "paid", "paid_at": {"$gte": start_date}}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.product_name", "revenue": {"$sum": "$items.price"}, "count": {"$sum": 1}}},
        {"$sort": {"revenue": -1}}, {"$limit": 10}
    ]
    top_products = await orders_collection.aggregate(product_pipeline).to_list(10)
    by_product = [{"name": p["_id"] or "Unknown", "revenue": round(p["revenue"], 2), "orders": p["count"]} for p in top_products]

    active_services = await services_collection.count_documents({"status": "active"})
    expired_services = await services_collection.count_documents({"status": {"$in": ["expired", "suspended"]}})
    total_services = active_services + expired_services
    total_customers = await users_collection.count_documents({"role": "user"})
    
    avg_order_value = round(cur_revenue / cur_orders, 2) if cur_orders > 0 else 0
    mrr = round(cur_revenue / max(days / 30, 1), 2)
    churn_rate = round((expired_services / total_services * 100), 1) if total_services > 0 else 0

    return {
        "revenue": {"current": round(cur_revenue, 2), "previous": round(prev_revenue, 2), "change": round(rev_change, 1)},
        "orders": {"current": cur_orders, "previous": prev_orders, "change": round(order_change, 1)},
        "customers": {"current": cur_customers, "previous": prev_customers, "change": round(cust_change, 1), "total": total_customers},
        "active_services": active_services,
        "expired_services": expired_services,
        "avg_order_value": avg_order_value,
        "mrr": mrr,
        "churn_rate": churn_rate,
        "chart": chart_data,
        "by_method": by_method,
        "by_product": by_product,
    }


# ============ SEO ============
@app.get("/api/seo")
async def get_seo_settings():
    settings = await get_settings()
    seo = settings.get("seo", {})
    branding = settings.get("branding", {})
    return {
        "meta_title": seo.get("meta_title") or branding.get("site_name", "IPTV Billing"),
        "meta_description": seo.get("meta_description") or branding.get("hero_description", ""),
        "meta_keywords": seo.get("meta_keywords", ""),
        "og_title": seo.get("og_title") or seo.get("meta_title") or branding.get("site_name", ""),
        "og_description": seo.get("og_description") or seo.get("meta_description") or branding.get("hero_description", ""),
        "og_image": seo.get("og_image") or branding.get("logo_url", ""),
        "twitter_card": seo.get("twitter_card", "summary_large_image"),
        "favicon_url": seo.get("favicon_url", ""),
        "google_analytics_id": seo.get("google_analytics_id", ""),
        "google_tag_manager_id": seo.get("google_tag_manager_id", ""),
        "schema_type": seo.get("schema_type", "Organization"),
        "schema_name": seo.get("schema_name") or branding.get("site_name", ""),
        "schema_description": seo.get("schema_description") or seo.get("meta_description", ""),
        "schema_url": seo.get("schema_url", ""),
        "schema_logo": seo.get("schema_logo") or branding.get("logo_url", ""),
        "schema_phone": seo.get("schema_phone", ""),
        "schema_email": seo.get("schema_email", ""),
        "custom_head_code": seo.get("custom_head_code", ""),
    }

@app.get("/api/robots.txt")
async def robots_txt():
    settings = await get_settings()
    content = settings.get("seo", {}).get("robots_txt", "User-agent: *\nAllow: /\nSitemap: /api/sitemap.xml")
    return Response(content=content, media_type="text/plain")

@app.get("/api/sitemap.xml")
async def sitemap_xml(request: Request):
    settings = await get_settings()
    base_url = settings.get("seo", {}).get("schema_url", "").rstrip("/")
    if not base_url:
        base_url = str(request.base_url).rstrip("/")
    urls = [
        {"loc": f"{base_url}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{base_url}/login", "priority": "0.6", "changefreq": "monthly"},
        {"loc": f"{base_url}/register", "priority": "0.6", "changefreq": "monthly"},
    ]
    async for product in products_collection.find({"is_active": {"$ne": False}}, {"_id": 1}):
        urls.append({"loc": f"{base_url}/order/{str(product['_id'])}", "priority": "0.8", "changefreq": "weekly"})
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in urls:
        xml += f'  <url>\n    <loc>{u["loc"]}</loc>\n    <priority>{u["priority"]}</priority>\n    <changefreq>{u["changefreq"]}</changefreq>\n  </url>\n'
    xml += '</urlset>'
    return Response(content=xml, media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
