from datetime import datetime
import logging
from bson import ObjectId

logger = logging.getLogger(__name__)


def _uid(user_id):
    # CMTV local change 2026-09-24: users._id is an ObjectId, but callers pass the id as a string.
    # Matching on the string never found the user, so balances always read $0 and updates did nothing.
    return ObjectId(user_id) if isinstance(user_id, str) and ObjectId.is_valid(user_id) else user_id

class CreditService:
    """Manage customer credit balances"""
    
    def __init__(self, db, settings_getter=None):
        self.db = db
        self.users = db.users
        self.transactions = db.credit_transactions
        self.get_settings = settings_getter
    
    async def is_enabled(self) -> bool:
        """Check if credit system is enabled"""
        if not self.get_settings:
            return True  # Default to enabled if no settings
        
        settings = await self.get_settings()
        return settings.get("credit", {}).get("enabled", True)
    
    async def get_balance(self, user_id: str) -> float:
        """Get user's credit balance"""
        user = await self.users.find_one({"_id": _uid(user_id)})
        return user.get("credit_balance", 0.0) if user else 0.0
    
    async def add_credits(
        self,
        user_id: str,
        amount: float,
        transaction_type: str,
        description: str,
        order_id: str = None,
        referral_id: str = None,
        created_by: str = None,
        bypass_enabled_check: bool = False
    ) -> float:
        """Add credits to user account"""
        # Check if credit system is enabled
        if not bypass_enabled_check and not await self.is_enabled():
            logger.warning("Credit system is disabled, credits not added")
            return await self.get_balance(user_id)
        
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        # Get current balance
        current_balance = await self.get_balance(user_id)
        new_balance = current_balance + amount
        
        # Update user balance
        await self.users.update_one(
            {"_id": _uid(user_id)},
            {"$set": {"credit_balance": new_balance}}
        )
        
        # Log transaction
        await self.transactions.insert_one({
            "user_id": user_id,
            "amount": amount,
            "transaction_type": transaction_type,
            "description": description,
            "order_id": order_id,
            "referral_id": referral_id,
            "balance_after": new_balance,
            "created_by": created_by,
            "created_at": datetime.utcnow()
        })
        
        logger.info(f"Credits added: ${amount} to user {user_id} ({transaction_type})")
        return new_balance
    
    async def deduct_credits(
        self,
        user_id: str,
        amount: float,
        transaction_type: str,
        description: str,
        order_id: str = None
    ) -> float:
        """Deduct credits from user account"""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        current_balance = await self.get_balance(user_id)
        
        if current_balance < amount:
            raise ValueError(f"Insufficient credits. Balance: ${current_balance}")
        
        new_balance = current_balance - amount
        
        # Update balance
        await self.users.update_one(
            {"_id": _uid(user_id)},
            {"$set": {"credit_balance": new_balance}}
        )
        
        # Log transaction
        await self.transactions.insert_one({
            "user_id": user_id,
            "amount": -amount,  # Negative for deduction
            "transaction_type": transaction_type,
            "description": description,
            "order_id": order_id,
            "balance_after": new_balance,
            "created_at": datetime.utcnow()
        })
        
        logger.info(f"Credits deducted: ${amount} from user {user_id} ({transaction_type})")
        return new_balance
    
    async def get_transaction_history(self, user_id: str, limit: int = 50):
        """Get credit transaction history for user"""
        transactions = []
        async for txn in self.transactions.find({"user_id": user_id}).sort("created_at", -1).limit(limit):
            txn["id"] = str(txn["_id"])
            del txn["_id"]
            transactions.append(txn)
        return transactions
