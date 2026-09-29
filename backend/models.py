from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"

class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ServiceStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    PENDING = "pending"


# Imported XtreamUI User Models
class ImportedUser(BaseModel):
    id: Optional[str] = None
    panel_index: int = 0
    panel_name: str = ""
    xtream_user_id: int  # User ID in XtreamUI
    username: str
    password: str
    expiry_date: Optional[datetime] = None
    status: str = "active"  # active, suspended, expired
    credits: Optional[float] = None  # For resellers
    max_connections: Optional[int] = None  # For subscribers
    account_type: str = "subscriber"  # subscriber or reseller
    created_by_reseller: Optional[str] = None  # Reseller username who created this user
    last_synced: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class AccountType(str, Enum):
    SUBSCRIBER = "subscriber"
    RESELLER = "reseller"
    MANUAL = "manual"

# User Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    referral_code: Optional[str] = None
    recaptcha_token: Optional[str] = None

class UserLogin(BaseModel):
    email: str  # Can be email OR username
    password: str
    recaptcha_token: Optional[str] = None
    totp_code: Optional[str] = None  # For 2FA verification

class User(BaseModel):
    id: Optional[str] = None
    email: EmailStr
    name: str
    role: UserRole = UserRole.USER
    email_verified: bool = False
    verification_token: Optional[str] = None
    credit_balance: float = 0.0
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Product Models
class ProductCreate(BaseModel):
    name: str
    description: str
    account_type: AccountType
    bouquets: List[int] = [1]
    max_connections: int = 2
    reseller_credits: float = 0.0
    reseller_max_lines: int = 0
    trial_days: int = 0
    prices: dict  # {1: 15.00, 3: 40.00, 6: 75.00, 12: 140.00}
    active: bool = True
    xtream_package_id: Optional[Any] = None  # XtreamUI package ID for provisioning
    panel_index: Optional[int] = 0  # Which panel this product uses
    panel_type: Optional[str] = 'xtream'  # Panel type: 'xtream', 'xuione', 'ghostsurf', etc.
    is_trial: Optional[bool] = False  # Whether this is a trial package
    display_order: Optional[int] = 0  # Order for display (lower = appears first)
    group_id: Optional[str] = ""  # Product group ID
    subgroup_id: Optional[str] = ""  # Product sub-group ID
    trial_duration: Optional[int] = 0  # Trial duration (e.g., 1, 7, 30)
    trial_duration_unit: Optional[str] = 'days'  # Trial duration unit (hours, days, months)
    setup_instructions: Optional[str] = ""  # Custom setup instructions for this product
    custom_panel_url: Optional[str] = ""  # Custom panel URL for customers (reseller only)
    is_bundle: Optional[bool] = False  # Whether this is a bundle product
    bundle_product_ids: Optional[List[str]] = []  # IDs of products included in bundle
    duration: Optional[int] = None  # Package duration (e.g., 1, 3, 6, 12)
    duration_unit: Optional[str] = 'months'  # Duration unit: months, days, years
    show_channels: Optional[bool] = True  # Show "View Channels" button on storefront
    ghostsurf_plan_id: Optional[str] = None  # GhostSurf VPN plan ID
    cockpit_module: Optional[str] = None  # CMTV local change 2026-09-24: manual product auto-creates a Cockpit account: 'nuvio' (Stremio) / 'vpn' (CMTVpn)

class Product(ProductCreate):
    id: Optional[str] = None
    xtream_package_id: Optional[Any] = None
    panel_index: Optional[int] = 0
    is_trial: Optional[bool] = False
    display_order: Optional[int] = 0
    trial_duration: Optional[int] = 0
    trial_duration_unit: Optional[str] = 'days'
    setup_instructions: Optional[str] = ""
    custom_panel_url: Optional[str] = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Order Models
class OrderItemCreate(BaseModel):
    product_id: str
    product_name: str
    term_months: int
    price: float
    account_type: AccountType
    renewal_service_id: Optional[str] = None  # Service ID to extend (if action_type='extend')
    action_type: Optional[str] = None  # 'extend' or 'create_new'
    credits: Optional[int] = None  # CMTV local change 2026-09-28: chosen reseller credit amount (cmtv_reseller_credits.py)
    lineup: Optional[str] = None  # CMTV local change 2026-09-29: Imperium channel line-up (cmtv_lineups.py)

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    total: float
    coupon_code: Optional[str] = None
    use_credits: float = 0.0
    reseller_credentials: Optional[dict] = None  # For custom reseller username/password
    payment_method: Optional[str] = None  # CMTV local change 2026-09-25: the option chosen at checkout

class Order(BaseModel):
    id: Optional[str] = None
    user_id: str
    items: List[OrderItemCreate]
    subtotal: float = 0.0
    discount_amount: float = 0.0
    coupon_code: Optional[str] = None
    credits_used: float = 0.0
    total: float
    reseller_credentials: Optional[dict] = None  # Store custom credentials
    status: OrderStatus = OrderStatus.PENDING
    payment_method: str = "manual"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = None

# Invoice Models
class Invoice(BaseModel):
    id: Optional[str] = None
    order_id: str
    user_id: str
    invoice_number: str
    total: float
    status: str = "unpaid"
    due_date: datetime
    paid_date: Optional[datetime] = None
    pdf_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Service Models
class Service(BaseModel):
    id: Optional[str] = None
    user_id: str
    order_id: str
    product_id: str
    product_name: str
    account_type: AccountType
    term_months: int
    xtream_username: Optional[str] = None
    xtream_password: Optional[str] = None
    xtream_user_id: Optional[str] = None
    bouquets: List[int] = []
    max_connections: int = 2
    reseller_credits: float = 0.0
    reseller_max_lines: int = 0
    status: ServiceStatus = ServiceStatus.PENDING
    start_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    next_due_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Ticket Models
class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"

class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class TicketMessage(BaseModel):
    message: str
    is_admin: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TicketCreate(BaseModel):
    subject: str
    message: str
    priority: TicketPriority = TicketPriority.MEDIUM
    service_id: Optional[str] = None  # Which service this ticket is about

class Ticket(BaseModel):
    id: Optional[str] = None
    user_id: str
    subject: str
    status: TicketStatus = TicketStatus.OPEN
    priority: TicketPriority = TicketPriority.MEDIUM
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    messages: List[TicketMessage] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Settings Models
class XtreamPanel(BaseModel):
    id: Optional[str] = None
    name: str  # Friendly name like "Main Panel", "Backup Panel"
    panel_url: str
    streaming_url: str = ""  # URL customers use for streaming (can be different from panel_url)
    admin_username: str
    admin_password: str
    ssl_verify: bool = False
    active: bool = True
    http_basic_user: str = ""  # Separate nginx basic auth user (if different from panel login)
    http_basic_pass: str = ""  # Separate nginx basic auth password
    proxy_url: str = ""  # Residential proxy URL to bypass Cloudflare WAF
    api_key: str = ""  # Optional reseller API key for JSON API panels



class PayPalSettings(BaseModel):
    client_id: str = ""
    secret: str = ""
    mode: str = "sandbox"
    enabled: bool = False

class StripeSettings(BaseModel):
    api_key: str = ""  # Deprecated - use test_secret_key or live_secret_key
    enabled: bool = False
    mode: str = "test"  # test or live
    test_publishable_key: str = "pk_test_"  # Test publishable key
    test_secret_key: str = "sk_test_"  # Test secret key
    live_publishable_key: str = ""  # Live publishable key
    live_secret_key: str = ""  # Live secret key

class SquareSettings(BaseModel):
    access_token: str = ""
    application_id: str = ""
    location_id: str = ""
    environment: str = "sandbox"
    enabled: bool = False

class BlockonomicsSettings(BaseModel):
    api_key: str = ""
    enabled: bool = False
    confirmations_required: int = 1  # Number of confirmations before marking as paid
    webhook_secret: str = ""  # Optional webhook secret for verification

class XtreamSettings(BaseModel):
    panels: List[XtreamPanel] = []  # Array of panels

class XuiOnePanel(BaseModel):
    id: Optional[str] = None
    name: str  # Friendly name like "Main XuiOne Panel"
    panel_url: str  # Web interface URL (e.g., http://domain.com/Resellers12)
    streaming_url: str = ""  # Streaming DNS (e.g., http://stream.domain.com:8080)
    api_access_code: str = ""  # API access code (e.g., UfPJlfai) - different from web access
    api_key: str = ""  # Optional API key for XuiOne authentication
    admin_username: str
    admin_password: str
    ssl_verify: bool = False
    active: bool = True

class XuiOneSettings(BaseModel):
    panels: List[XuiOnePanel] = []  # Array of XuiOne panels

class NxtDashPanel(BaseModel):
    id: Optional[str] = None
    name: str = ""
    panel_url: str = ""      # DNS / API base URL
    token: str = ""           # Bearer token
    username: str = ""        # Reseller username
    password: str = ""        # Reseller password
    portal_url: str = ""      # Customer portal URL (legacy, use streaming_url)
    streaming_url: str = ""  # Streaming DNS for customers
    active: bool = True

class NxtDashSettings(BaseModel):
    panels: List[NxtDashPanel] = []

class OneStreamPanel(BaseModel):
    id: Optional[str] = None
    name: str = ""
    panel_url: str = ""
    api_key: str = ""  # X-Api-Key header
    auth_user_token: str = ""  # X-Auth-User header
    admin_username: str = ""
    admin_password: str = ""
    ssl_verify: bool = False
    streaming_url: str = ""  # Streaming DNS for customers
    active: bool = True

class OneStreamSettings(BaseModel):
    panels: List[OneStreamPanel] = []

class SMTPSettings(BaseModel):
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "IPTV Billing"

class BrandingSettings(BaseModel):
    site_name: str = "IPTV Billing"
    logo_url: str = ""
    theme: str = "light"  # light or dark
    primary_color: str = "#2563eb"  # blue-600
    secondary_color: str = "#7c3aed"  # purple-600
    accent_color: str = "#059669"  # green-600
    product_card_color: str = "#2563eb"  # Product card gradient color
    # Homepage content
    hero_title: str = "Premium IPTV Subscriptions"
    hero_description: str = "Access thousands of channels with our reliable IPTV service. Flexible plans, instant activation, 24/7 support."
    hero_background_image: str = ""  # Hero section background image URL
    homepage_bg_color: str = ""  # Homepage background color (used when no image)
    footer_text: str = "Premium IPTV Services"
    # Feature sections
    feature_1_title: str = "Instant Activation"
    feature_1_description: str = "Get your credentials immediately after payment. Start watching within minutes."
    feature_2_title: str = "Multiple Connections"
    feature_2_description: str = "Watch on multiple devices simultaneously. Perfect for families."
    feature_3_title: str = "Flexible Plans"
    feature_3_description: str = "Choose from 1, 3, 6, or 12-month plans. Save more with longer subscriptions."
    # Background (deprecated - use hero_background_image instead)
    background_image_url: str = ""
    provision_notes_template: str = "{{customer_name}} | {{email}} | Order: {{order_id}}"


# Credit and Referral Settings (must be before Settings class)
class ReferralSettings(BaseModel):
    enabled: bool = True
    referrer_reward: float = 10.0
    referred_reward: float = 5.0
    minimum_purchase: float = 0.0
    reward_type: str = "credit"
    expiry_days: int = 90

class CreditSettings(BaseModel):
    enabled: bool = True
    allow_negative_balance: bool = False
    minimum_balance: float = 0.0
    maximum_balance: float = 10000.0

class RecaptchaSettings(BaseModel):
    enabled: bool = False
    site_key: str = ""
    secret_key: str = ""
    customer_score_threshold: float = 0.5
    admin_score_threshold: float = 0.7

class EMTSettings(BaseModel):
    enabled: bool = False
    instructions: str = ""

class ZelleSettings(BaseModel):
    enabled: bool = False
    instructions: str = ""

class CashAppSettings(BaseModel):
    enabled: bool = False
    instructions: str = ""

class VenmoSettings(BaseModel):
    enabled: bool = False
    instructions: str = ""

class HelcimSettings(BaseModel):
    enabled: bool = False
    api_token: str = ""
    terminal_id: str = ""

class WiseSettings(BaseModel):
    enabled: bool = False
    api_token: str = ""
    profile_id: str = ""
    instructions: str = ""


class TermsSettings(BaseModel):
    enabled: bool = False
    title: str = "Terms and Conditions"
    content: str = ""  # HTML content for the terms


class InvoiceSettings(BaseModel):
    company_name: str = ""
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_website: str = ""
    logo_url: str = ""
    invoice_prefix: str = "INV"
    next_number: int = 1001
    number_padding: int = 4
    notes: str = ""
    terms: str = ""
    payment_instructions: str = ""
    primary_color: str = "#2563eb"
    accent_color: str = "#f3f4f6"

class SEOSettings(BaseModel):
    meta_title: str = ""
    meta_description: str = ""
    meta_keywords: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    twitter_card: str = "summary_large_image"
    favicon_url: str = ""
    google_analytics_id: str = ""
    google_tag_manager_id: str = ""
    robots_txt: str = "User-agent: *\nAllow: /\nSitemap: /sitemap.xml"
    schema_type: str = "Organization"
    schema_name: str = ""
    schema_description: str = ""
    schema_url: str = ""
    schema_logo: str = ""
    schema_phone: str = ""
    schema_email: str = ""
    custom_head_code: str = ""


class GhostSurfPanel(BaseModel):
    id: Optional[str] = None
    name: str = ""
    panel_url: str = "https://ghostsurf.io/api/v1/reseller/api"
    api_key: str = ""
    active: bool = True

class GhostSurfSettings(BaseModel):
    panels: List[GhostSurfPanel] = []


class AetherPanel(BaseModel):
    id: Optional[str] = None
    name: str = ""
    panel_url: str = ""       # https://bestpanel.xyz
    api_token: str = ""       # pmk_... Bearer token (reseller or admin kind)
    streaming_url: str = ""   # Optional override; otherwise read from line credentials
    ssl_verify: bool = True
    active: bool = True

class AetherSettings(BaseModel):
    panels: List[AetherPanel] = []



class Settings(BaseModel):
    id: Optional[str] = None
    xtream: XtreamSettings = Field(default_factory=XtreamSettings)
    xuione: XuiOneSettings = Field(default_factory=XuiOneSettings)
    onestream: OneStreamSettings = Field(default_factory=OneStreamSettings)
    nxtdash: NxtDashSettings = Field(default_factory=NxtDashSettings)
    ghostsurf: GhostSurfSettings = Field(default_factory=GhostSurfSettings)
    aether: AetherSettings = Field(default_factory=AetherSettings)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)
    paypal: PayPalSettings = Field(default_factory=PayPalSettings)
    stripe: StripeSettings = Field(default_factory=StripeSettings)
    square: SquareSettings = Field(default_factory=SquareSettings)
    blockonomics: BlockonomicsSettings = Field(default_factory=BlockonomicsSettings)
    branding: BrandingSettings = Field(default_factory=BrandingSettings)
    referral: ReferralSettings = Field(default_factory=ReferralSettings)
    credit: CreditSettings = Field(default_factory=CreditSettings)
    recaptcha: RecaptchaSettings = Field(default_factory=RecaptchaSettings)
    emt: EMTSettings = Field(default_factory=EMTSettings)
    zelle: ZelleSettings = Field(default_factory=ZelleSettings)
    cashapp: CashAppSettings = Field(default_factory=CashAppSettings)
    venmo: VenmoSettings = Field(default_factory=VenmoSettings)
    wise: WiseSettings = Field(default_factory=WiseSettings)
    helcim: HelcimSettings = Field(default_factory=HelcimSettings)
    invoice: InvoiceSettings = Field(default_factory=InvoiceSettings)
    seo: SEOSettings = Field(default_factory=SEOSettings)
    terms: TermsSettings = Field(default_factory=TermsSettings)
    currency: str = "USD"
    refunds_enabled: bool = True  # Enable/disable refund feature
    company_name: str = "IPTV Billing"
    company_email: str = ""
    support_email: str = ""
    license_key: str = ""
    payment_method_order: List[str] = Field(default_factory=lambda: ["manual", "emt", "zelle", "cashapp", "venmo", "wise", "helcim", "stripe", "paypal", "square", "blockonomics"])
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        extra = "allow"  # Preserve extra fields like notifications, bouquets_panel_X, etc.


# Email Template Models
class EmailTemplateType(str, Enum):
    ORDER_CONFIRMATION = "order_confirmation"
    SERVICE_ACTIVATED = "service_activated"
    RESELLER_ACTIVATED = "reseller_activated"  # New template for resellers
    SERVICE_EXPIRY_WARNING = "service_expiry_warning"
    SERVICE_EXPIRED = "service_expired"
    TICKET_REPLY = "ticket_reply"
    WELCOME = "welcome"
    PASSWORD_RESET = "password_reset"
    INVOICE_CREATED = "invoice_created"
    PAYMENT_RECEIVED = "payment_received"
    SERVICE_SUSPENDED = "service_suspended"
    SERVICE_CANCELLED = "service_cancelled"

class EmailTemplate(BaseModel):
    id: Optional[str] = None
    template_type: EmailTemplateType
    name: str
    subject: str
    html_content: str
    text_content: Optional[str] = ""
    available_variables: List[str] = Field(default_factory=list)
    description: Optional[str] = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    is_active: Optional[bool] = None



# Email Log Models
class EmailStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"
    DELIVERED = "delivered"

class EmailType(str, Enum):
    TRANSACTIONAL = "transactional"
    MARKETING = "marketing"
    MASS = "mass"

class EmailLog(BaseModel):
    id: Optional[str] = None
    recipient_email: str
    recipient_name: str = ""
    subject: str
    html_content: str
    text_content: Optional[str] = ""
    email_type: EmailType = EmailType.TRANSACTIONAL
    template_type: Optional[str] = None  # e.g., "order_confirmation"
    status: EmailStatus = EmailStatus.PENDING
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    bounced_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None  # Future: track opens
    clicked_at: Optional[datetime] = None  # Future: track clicks
    sent_by: Optional[str] = None  # Admin user ID for mass emails
    customer_id: Optional[str] = None  # Link to customer
    order_id: Optional[str] = None  # Link to order if applicable
    attachments: List[str] = Field(default_factory=list)  # File paths/URLs
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Email Unsubscribe Models
class UnsubscribeReason(str, Enum):
    TOO_FREQUENT = "too_frequent"
    NOT_RELEVANT = "not_relevant"
    NEVER_SUBSCRIBED = "never_subscribed"
    OTHER = "other"

class EmailUnsubscribe(BaseModel):
    id: Optional[str] = None
    email: str
    customer_id: Optional[str] = None
    unsubscribed_from: str = "all"  # "all", "marketing", "promotions"
    reason: Optional[UnsubscribeReason] = None
    reason_text: Optional[str] = None
    unsubscribed_at: datetime = Field(default_factory=datetime.utcnow)
    ip_address: Optional[str] = None
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Scheduled Email Models
class ScheduledEmail(BaseModel):
    id: Optional[str] = None
    subject: str
    content: str
    recipient_filter: str = "all"  # all, active, inactive
    scheduled_for: datetime
    sent: bool = False
    sent_at: Optional[datetime] = None
    created_by: str  # Admin user ID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    cancelled: bool = False
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Template Version Models
class TemplateVersion(BaseModel):
    id: Optional[str] = None
    template_id: str
    version_number: int
    name: str
    subject: str
    html_content: str
    text_content: Optional[str] = ""
    modified_by: str  # Admin user ID
    modified_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}



# Referral System Models
class ReferralStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"

class Referral(BaseModel):
    id: Optional[str] = None
    referrer_id: str  # User who referred
    referred_email: str
    referred_id: Optional[str] = None  # User who was referred (after signup)
    referral_code: str  # Unique code
    status: ReferralStatus = ReferralStatus.PENDING
    reward_amount: float = 0.0  # Credits earned
    reward_type: str = "credit"  # credit or discount
    rewarded: bool = False
    order_id: Optional[str] = None  # First order from referred user
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Coupon System Models
class CouponType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"

class Coupon(BaseModel):
    id: Optional[str] = None
    code: str  # e.g., "SAVE20", "WELCOME50"
    coupon_type: CouponType
    value: float  # 20 for 20% or 20.00 for $20
    min_purchase: float = 0.0
    max_uses: Optional[int] = None  # None = unlimited
    used_count: int = 0
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None
    active: bool = True
    applies_to: str = "all"  # all, specific_products
    product_ids: List[str] = Field(default_factory=list)
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class CouponUsage(BaseModel):
    id: Optional[str] = None
    coupon_id: str
    coupon_code: str
    user_id: str
    order_id: str
    discount_amount: float
    used_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Credit System Models
class CreditTransaction(BaseModel):
    id: Optional[str] = None
    user_id: str
    amount: float  # Positive for add, negative for deduct
    transaction_type: str  # "purchase", "referral", "refund", "admin_adjustment", "order_payment"
    description: str
    order_id: Optional[str] = None
    referral_id: Optional[str] = None
    balance_after: float
    created_by: Optional[str] = None  # Admin ID if manual
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Refund Models
class RefundStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"

class Refund(BaseModel):
    id: Optional[str] = None
    order_id: str
    user_id: str
    amount: float
    refund_type: str = "full"  # full or partial
    method: str = "original"  # original payment method or credit
    reason: str = ""
    status: RefundStatus = RefundStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    processed_by: Optional[str] = None  # Admin ID
    notes: str = ""
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Automated Renewal Models
class RenewalStatus(str, Enum):
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AutoRenewal(BaseModel):
    id: Optional[str] = None
    user_id: str
    service_id: str
    product_id: str
    enabled: bool = True
    payment_method_id: Optional[str] = None  # Saved payment method
    next_renewal_date: datetime
    last_attempt_date: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    status: RenewalStatus = RenewalStatus.SCHEDULED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Payment Retry Models
class PaymentRetry(BaseModel):
    id: Optional[str] = None
    order_id: str
    user_id: str
    payment_method_id: str
    amount: float
    attempt_number: int = 1
    max_attempts: int = 3
    next_retry_at: datetime
    last_error: Optional[str] = None
    status: str = "pending"  # pending, success, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

# Lifecycle Automation Models
class LifecycleAction(str, Enum):
    PROVISION = "provision"
    SUSPEND = "suspend"
    CANCEL = "cancel"
    DELETE = "delete"
    RENEW = "renew"

class LifecycleLog(BaseModel):
    id: Optional[str] = None
    service_id: str
    user_id: str
    action: LifecycleAction
    reason: str
    triggered_by: str = "system"  # system or admin_id
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# Downloads System Models
class DownloadCategory(str, Enum):
    IPTV_PLAYER = "iptv_player"
    MOBILE_APP = "mobile_app"
    GUIDE = "guide"
    SETUP = "setup"
    OTHER = "other"

class Download(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    category: DownloadCategory
    file_path: str  # Path to uploaded file
    file_url: str   # Public URL to download
    file_size: int = 0  # In bytes
    file_type: str = ""  # e.g., "application/pdf", "application/apk"
    version: str = ""
    platform: str = "all"  # all, windows, mac, linux, android, ios
    requires_active_service: bool = True
    linked_service_types: List[str] = Field(default_factory=list)  # Empty = all services
    download_count: int = 0
    active: bool = True
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class DownloadLog(BaseModel):
    id: Optional[str] = None
    download_id: str
    user_id: str
    ip_address: Optional[str] = None
    downloaded_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# License System Models
class LicenseStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"

class License(BaseModel):
    id: Optional[str] = None
    license_key: str  # Unique license key
    customer_name: str = ""
    customer_email: str = ""
    status: LicenseStatus = LicenseStatus.ACTIVE
    allowed_domains: List[str] = Field(default_factory=list)  # Whitelisted domains
    max_domains: int = 1  # How many domains can use this license
    issued_date: datetime = Field(default_factory=datetime.utcnow)
    expiry_date: Optional[datetime] = None  # None = lifetime
    last_validated: Optional[datetime] = None
    validation_count: int = 0
    features: dict = Field(default_factory=dict)  # Feature flags
    notes: str = ""
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}

class LicenseValidation(BaseModel):
    id: Optional[str] = None
    license_key: str
    domain: str
    ip_address: Optional[str] = None
    validated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str  # success or failed
    failure_reason: Optional[str] = None
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}



