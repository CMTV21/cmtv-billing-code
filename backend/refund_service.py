from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class RefundService:
    """Manage refunds and returns"""
    
    def __init__(self, db, credit_service=None):
        self.db = db
        self.refunds = db.refunds
        self.orders = db.orders
        self.invoices = db.invoices
        self.users = db.users
        self.credit_service = credit_service
    
    async def request_refund(
        self,
        order_id: str,
        user_id: str,
        amount: float,
        refund_type: str,
        method: str,
        reason: str
    ) -> str:
        """Create a refund request"""
        # Validate order (handle both ObjectId and string IDs)
        from bson import ObjectId
        try:
            # Try as ObjectId first
            order = await self.orders.find_one({"_id": ObjectId(order_id), "user_id": user_id})
        except Exception:
            # Fallback to string ID
            order = await self.orders.find_one({"_id": order_id, "user_id": user_id})
        
        if not order:
            raise ValueError("Order not found")
        
        if order.get("status") != "paid":
            raise ValueError("Only paid orders can be refunded")
        
        # Check if already refunded
        existing = await self.refunds.find_one({
            "order_id": order_id,
            "status": {"$in": ["approved", "completed"]}
        })
        
        if existing:
            raise ValueError("Order already refunded")
        
        # Validate amount (use order total if amount exceeds or is 0)
        order_total = order.get("total", 0)
        if amount > order_total or amount == 0:
            amount = order_total  # Default to full order amount
        
        # Get user info for display
        user = await self.users.find_one({"_id": ObjectId(user_id)})
        
        # Create refund request
        refund = {
            "order_id": order_id,
            "user_id": user_id,
            "user_name": user.get("name", "Unknown") if user else "Unknown",
            "user_email": user.get("email", "N/A") if user else "N/A",
            "amount": amount,
            "order_total": order_total,
            "refund_type": refund_type,
            "method": method,
            "reason": reason,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "requested_at": datetime.utcnow()
        }
        
        result = await self.refunds.insert_one(refund)
        logger.info(f"Refund request created: ${amount} for order {order_id}")
        
        return str(result.inserted_id)
    
    async def approve_refund(self, refund_id: str, admin_id: str, notes: str = ""):
        """Approve and process refund"""
        from bson import ObjectId
        
        # Convert refund_id to ObjectId
        try:
            refund_oid = ObjectId(refund_id)
        except Exception:
            refund_oid = refund_id  # Fallback to string
        
        refund = await self.refunds.find_one({"_id": refund_oid})
        if not refund:
            raise ValueError("Refund not found")
        
        if refund.get("status") != "pending":
            raise ValueError(f"Refund already {refund['status']}")
        
        # Update status to approved
        await self.refunds.update_one(
            {"_id": refund_oid},
            {"$set": {
                "status": "approved",
                "processed_by": admin_id,
                "processed_at": datetime.utcnow(),
                "notes": notes
            }}
        )
        
        # Process refund based on method
        if refund["method"] == "credit":
            # Refund as account credit
            if self.credit_service:
                await self.credit_service.add_credits(
                    user_id=refund["user_id"],
                    amount=refund["amount"],
                    transaction_type="refund",
                    description=f"Refund for order #{refund['order_id']}",
                    order_id=refund["order_id"],
                    created_by=admin_id
                )
            
            # Mark as completed
            await self.refunds.update_one(
                {"_id": refund_id},
                {"$set": {"status": "completed"}}
            )
            
        elif refund["method"] == "original":
            # Refund to original payment method
            # This would integrate with payment gateways
            logger.info(f"Processing refund to original payment method for order {refund['order_id']}")
            
            # For now, mark as approved (actual processing would happen via payment gateway)
            await self.refunds.update_one(
                {"_id": refund_id},
                {"$set": {"status": "approved"}}
            )
        
        logger.info(f"Refund approved: ${refund['amount']} for order {refund['order_id']}")
        return True
    
    async def reject_refund(self, refund_id: str, admin_id: str, notes: str = ""):
        """Reject refund request"""
        await self.refunds.update_one(
            {"_id": refund_id},
            {"$set": {
                "status": "rejected",
                "processed_by": admin_id,
                "processed_at": datetime.utcnow(),
                "notes": notes
            }}
        )
        
        logger.info(f"Refund rejected: {refund_id}")
    
    async def get_pending_refunds(self):
        """Get all refund requests (sorted newest to oldest)"""
        refunds = []
        async for refund in self.refunds.find({}).sort("requested_at", -1):
            refund["id"] = str(refund["_id"])
            del refund["_id"]
            
            # Get user and order details
            user = await self.db.users.find_one({"_id": refund["user_id"]})
            order = await self.db.orders.find_one({"_id": refund["order_id"]})
            
            if user:
                refund["user_name"] = user["name"]
                refund["user_email"] = user["email"]
            
            if order:
                refund["order_total"] = order.get("total", 0)
            
            refunds.append(refund)
        
        return refunds
