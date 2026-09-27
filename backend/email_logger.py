from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def _oid(log_id):
    """CMTV local change 2026-09-26: log_email returns the id as text, but the documents' _id is an ObjectId, so
    mark_sent / mark_failed never matched and every email stayed "pending". Look it up as an ObjectId."""
    from bson import ObjectId
    return ObjectId(log_id) if isinstance(log_id, str) and ObjectId.is_valid(log_id) else log_id

class EmailLogger:
    """Service for logging all email activity"""
    
    def __init__(self, db):
        self.db = db
        self.email_logs = db.email_logs
    
    async def log_email(
        self,
        recipient_email: str,
        subject: str,
        html_content: str,
        email_type: str = "transactional",
        template_type: Optional[str] = None,
        customer_id: Optional[str] = None,
        order_id: Optional[str] = None,
        sent_by: Optional[str] = None,
        recipient_name: str = "",
        text_content: str = ""
    ) -> str:
        """Log an email that's about to be sent"""
        log_entry = {
            "recipient_email": recipient_email,
            "recipient_name": recipient_name,
            "subject": subject,
            "html_content": html_content,
            "text_content": text_content,
            "email_type": email_type,
            "template_type": template_type,
            "status": "pending",
            "customer_id": customer_id,
            "order_id": order_id,
            "sent_by": sent_by,
            "attachments": [],
            "created_at": datetime.utcnow()
        }
        
        result = await self.email_logs.insert_one(log_entry)
        return str(result.inserted_id)
    
    async def mark_sent(self, log_id: str):
        """Mark email as successfully sent"""
        await self.email_logs.update_one(
            {"_id": _oid(log_id)},
            {"$set": {
                "status": "sent",
                "sent_at": datetime.utcnow()
            }}
        )
    
    async def mark_failed(self, log_id: str, error_message: str):
        """Mark email as failed"""
        await self.email_logs.update_one(
            {"_id": _oid(log_id)},
            {"$set": {
                "status": "failed",
                "error_message": error_message
            }}
        )
    
    async def mark_bounced(self, log_id: str, bounce_reason: str):
        """Mark email as bounced"""
        await self.email_logs.update_one(
            {"_id": _oid(log_id)},
            {"$set": {
                "status": "bounced",
                "error_message": bounce_reason,
                "bounced_at": datetime.utcnow()
            }}
        )
    
    async def get_customer_history(self, customer_id: str, limit: int = 50):
        """Get email history for a specific customer"""
        emails = []
        cursor = self.email_logs.find(
            {"customer_id": customer_id}
        ).sort("created_at", -1).limit(limit)
        
        async for email in cursor:
            email["id"] = str(email["_id"])
            del email["_id"]
            # Don't return full content in history list
            email["content_preview"] = email.get("html_content", "")[:100]
            del email["html_content"]
            emails.append(email)
        
        return emails
    
    async def get_statistics(self, days: int = 30):
        """Get email statistics for the past N days"""
        from datetime import timedelta
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        pipeline = [
            {"$match": {"created_at": {"$gte": start_date}}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        stats = {"total": 0, "sent": 0, "failed": 0, "bounced": 0, "pending": 0}
        
        async for result in self.email_logs.aggregate(pipeline):
            status = result["_id"]
            count = result["count"]
            stats[status] = count
            stats["total"] += count
        
        return stats
