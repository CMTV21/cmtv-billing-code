#!/usr/bin/env python3
"""
Backend API Testing for WHMCS-style IPTV Billing Platform
Focus: Testing extend/create service feature at checkout
"""

import requests
import sys
import time
from datetime import datetime
import random
import string

# Use public endpoint
BASE_URL = "https://admin-analytics-46.preview.emergentagent.com/api"

class BackendTester:
    def __init__(self):
        self.token = None
        self.admin_token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_user_email = f"test_extend_{int(time.time())}@example.com"
        self.test_user_password = "TestPass123!"
        
    def log(self, message, status="INFO"):
        """Log test messages"""
        symbols = {"INFO": "ℹ️", "PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
        print(f"{symbols.get(status, 'ℹ️')} {message}")
    
    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{BASE_URL}/{endpoint}"
        default_headers = {'Content-Type': 'application/json'}
        
        if self.token and not headers:
            default_headers['Authorization'] = f'Bearer {self.token}'
        elif headers:
            default_headers.update(headers)
        
        self.tests_run += 1
        self.log(f"Testing {name}...", "INFO")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=default_headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=default_headers, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=default_headers, timeout=30)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=default_headers, timeout=30)
            
            success = response.status_code == expected_status
            
            if success:
                self.tests_passed += 1
                self.log(f"PASSED - {name} (Status: {response.status_code})", "PASS")
                try:
                    return True, response.json()
                except Exception:
                    return True, {}
            else:
                self.log(f"FAILED - {name} (Expected {expected_status}, got {response.status_code})", "FAIL")
                try:
                    error_detail = response.json()
                    self.log(f"Error: {error_detail}", "FAIL")
                except Exception:
                    self.log(f"Response: {response.text[:200]}", "FAIL")
                return False, {}
        
        except Exception as e:
            self.log(f"FAILED - {name} (Exception: {str(e)})", "FAIL")
            return False, {}
    
    def test_health(self):
        """Test health endpoint"""
        return self.run_test("Health Check", "GET", "health", 200)
    
    def test_register(self):
        """Register test user"""
        success, response = self.run_test(
            "User Registration",
            "POST",
            "auth/register",
            200,
            data={
                "email": self.test_user_email,
                "name": "Test User",
                "password": self.test_user_password
            }
        )
        
        # Verify email using MongoDB (bypass email verification for testing)
        if success:
            import subprocess
            verify_cmd = f"""mongosh --quiet --eval 'db.getSiblingDB("iptv_billing").users.updateOne({{email: "{self.test_user_email}"}}, {{$set: {{email_verified: true, verification_token: null}}}})'"""
            try:
                result = subprocess.run(verify_cmd, shell=True, capture_output=True, timeout=5, text=True)
                if result.returncode == 0:
                    self.log("Email verified via database", "INFO")
                else:
                    self.log(f"Failed to verify email: {result.stderr}", "WARN")
            except Exception as e:
                self.log(f"Failed to verify email: {e}", "WARN")
        
        return success, response
    
    def test_login(self):
        """Login test user"""
        success, response = self.run_test(
            "User Login",
            "POST",
            "auth/login",
            200,
            data={
                "email": self.test_user_email,
                "password": self.test_user_password
            }
        )
        
        if success and 'access_token' in response:
            self.token = response['access_token']
            self.user_id = response['user']['id']
            self.log(f"Logged in as user: {self.user_id}", "PASS")
            return True, response
        return False, {}
    
    def test_admin_login(self):
        """Login as admin"""
        success, response = self.run_test(
            "Admin Login",
            "POST",
            "auth/login",
            200,
            data={
                "email": "admin@example.com",
                "password": "admin123"
            }
        )
        
        if success and 'access_token' in response:
            self.admin_token = response['access_token']
            self.log(f"Logged in as admin", "PASS")
            return True, response
        return False, {}
    
    def test_get_products(self):
        """Get products list"""
        success, response = self.run_test(
            "Get Products",
            "GET",
            "products",
            200
        )
        return success, response
    
    def test_create_order(self, items, coupon_code=None, use_credits=0):
        """Create an order"""
        order_data = {
            "items": items,
            "total": sum(item['price'] for item in items)
        }
        
        if coupon_code:
            order_data["coupon_code"] = coupon_code
        if use_credits > 0:
            order_data["use_credits"] = use_credits
        
        success, response = self.run_test(
            "Create Order",
            "POST",
            "orders",
            200,
            data=order_data
        )
        return success, response
    
    def test_mark_order_paid(self, order_id):
        """Mark order as paid (admin action)"""
        # Use admin token
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.admin_token}'
        }
        
        success, response = self.run_test(
            f"Mark Order {order_id} as Paid",
            "POST",
            f"admin/orders/{order_id}/mark-paid",
            200,
            headers=headers
        )
        return success, response
    
    def test_get_services(self):
        """Get user services"""
        success, response = self.run_test(
            "Get User Services",
            "GET",
            "services",
            200
        )
        return success, response
    
    def test_get_orders(self):
        """Get user orders"""
        success, response = self.run_test(
            "Get User Orders",
            "GET",
            "orders",
            200
        )
        return success, response
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print(f"📊 TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {self.tests_run - self.tests_passed}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run*100):.1f}%")
        print("="*60 + "\n")
        
        return 0 if self.tests_passed == self.tests_run else 1


def main():
    """Main test execution"""
    tester = BackendTester()
    
    print("\n" + "="*60)
    print("🧪 BACKEND API TESTING - EXTEND/CREATE SERVICE FEATURE")
    print("="*60 + "\n")
    
    # 1. Health check
    tester.log("=== PHASE 1: Basic Health Check ===", "INFO")
    success, _ = tester.test_health()
    if not success:
        tester.log("Health check failed, aborting tests", "FAIL")
        return 1
    
    # 2. Get products
    tester.log("\n=== PHASE 2: Get Products ===", "INFO")
    success, products_response = tester.test_get_products()
    if not success or not products_response:
        tester.log("Failed to get products, aborting tests", "FAIL")
        return 1
    
    # Find a subscriber product
    subscriber_products = [p for p in products_response if p.get('account_type') == 'subscriber']
    if not subscriber_products:
        tester.log("No subscriber products found, aborting tests", "FAIL")
        return 1
    
    test_product = subscriber_products[0]
    tester.log(f"Using product: {test_product['name']} (ID: {test_product['id']})", "INFO")
    
    # Get price for 1 month
    prices = test_product.get('prices', {})
    price_1m = prices.get('1', prices.get(1, 15.0))
    
    # 3. Register and login
    tester.log("\n=== PHASE 3: User Registration & Login ===", "INFO")
    success, _ = tester.test_register()
    if not success:
        tester.log("Registration failed, aborting tests", "FAIL")
        return 1
    
    # Wait a bit for registration to complete
    time.sleep(1)
    
    success, _ = tester.test_login()
    if not success:
        tester.log("Login failed, aborting tests", "FAIL")
        return 1
    
    # 4. Admin login
    tester.log("\n=== PHASE 4: Admin Login ===", "INFO")
    success, _ = tester.test_admin_login()
    if not success:
        tester.log("Admin login failed, aborting tests", "FAIL")
        return 1
    
    # 5. Create first order (to get an existing service)
    tester.log("\n=== PHASE 5: Create Initial Order (to get existing service) ===", "INFO")
    order_item = {
        "product_id": test_product['id'],
        "product_name": test_product['name'],
        "term_months": 1,
        "price": price_1m,
        "account_type": "subscriber"
    }
    
    success, order_response = tester.test_create_order([order_item])
    if not success or 'order_id' not in order_response:
        tester.log("Failed to create initial order, aborting tests", "FAIL")
        return 1
    
    initial_order_id = order_response['order_id']
    tester.log(f"Initial order created: {initial_order_id}", "PASS")
    
    # 6. Mark order as paid (to provision service)
    tester.log("\n=== PHASE 6: Mark Initial Order as Paid (Provision Service) ===", "INFO")
    success, _ = tester.test_mark_order_paid(initial_order_id)
    if not success:
        tester.log("Failed to mark order as paid, aborting tests", "FAIL")
        return 1
    
    # Wait for provisioning
    tester.log("Waiting 5 seconds for service provisioning...", "INFO")
    time.sleep(5)
    
    # 7. Get services to verify initial service was created
    tester.log("\n=== PHASE 7: Verify Initial Service Created ===", "INFO")
    success, services_response = tester.test_get_services()
    if not success:
        tester.log("Failed to get services, aborting tests", "FAIL")
        return 1
    
    # Filter out credit add-ons
    main_services = [s for s in services_response if not s.get('is_credit_addon', False)]
    
    if not main_services:
        tester.log("No services found after provisioning, aborting tests", "FAIL")
        return 1
    
    initial_service = main_services[0]
    tester.log(f"Initial service created: {initial_service['xtream_username']}", "PASS")
    tester.log(f"Service ID: {initial_service['id']}", "INFO")
    tester.log(f"Expiry: {initial_service.get('expiry_date', 'N/A')}", "INFO")
    
    # 8. Test EXTEND flow - Create order with renewal_service_id and action_type='extend'
    tester.log("\n=== PHASE 8: Test EXTEND Flow ===", "INFO")
    tester.log("Creating order with action_type='extend' and renewal_service_id", "INFO")
    
    extend_order_item = {
        "product_id": test_product['id'],
        "product_name": test_product['name'],
        "term_months": 1,
        "price": price_1m,
        "account_type": "subscriber",
        "action_type": "extend",
        "renewal_service_id": initial_service['id']
    }
    
    success, extend_order_response = tester.test_create_order([extend_order_item])
    if not success or 'order_id' not in extend_order_response:
        tester.log("Failed to create extend order", "FAIL")
    else:
        extend_order_id = extend_order_response['order_id']
        tester.log(f"Extend order created: {extend_order_id}", "PASS")
        
        # Mark as paid
        success, _ = tester.test_mark_order_paid(extend_order_id)
        if success:
            tester.log("Waiting 5 seconds for extension provisioning...", "INFO")
            time.sleep(5)
            
            # Get services again to verify extension
            success, services_after_extend = tester.test_get_services()
            if success:
                main_services_after = [s for s in services_after_extend if not s.get('is_credit_addon', False)]
                
                # Should still have only 1 service (extended, not new)
                if len(main_services_after) == 1:
                    tester.log("✅ EXTEND FLOW PASSED: Service count remained 1 (extended, not created new)", "PASS")
                    extended_service = main_services_after[0]
                    tester.log(f"Extended service expiry: {extended_service.get('expiry_date', 'N/A')}", "INFO")
                    
                    # Verify it's the same service
                    if extended_service['id'] == initial_service['id']:
                        tester.log("✅ Verified: Same service ID (extended existing service)", "PASS")
                    else:
                        tester.log("❌ ERROR: Different service ID (created new instead of extending)", "FAIL")
                else:
                    tester.log(f"❌ EXTEND FLOW FAILED: Expected 1 service, found {len(main_services_after)}", "FAIL")
                    tester.log("This means a new service was created instead of extending existing one", "FAIL")
    
    # 9. Test CREATE NEW flow - Create order with action_type='create_new'
    tester.log("\n=== PHASE 9: Test CREATE NEW Flow ===", "INFO")
    tester.log("Creating order with action_type='create_new'", "INFO")
    
    create_new_order_item = {
        "product_id": test_product['id'],
        "product_name": test_product['name'],
        "term_months": 1,
        "price": price_1m,
        "account_type": "subscriber",
        "action_type": "create_new"
    }
    
    success, create_new_order_response = tester.test_create_order([create_new_order_item])
    if not success or 'order_id' not in create_new_order_response:
        tester.log("Failed to create 'create new' order", "FAIL")
    else:
        create_new_order_id = create_new_order_response['order_id']
        tester.log(f"Create new order created: {create_new_order_id}", "PASS")
        
        # Mark as paid
        success, _ = tester.test_mark_order_paid(create_new_order_id)
        if success:
            tester.log("Waiting 5 seconds for new service provisioning...", "INFO")
            time.sleep(5)
            
            # Get services again to verify new service was created
            success, services_after_create = tester.test_get_services()
            if success:
                main_services_final = [s for s in services_after_create if not s.get('is_credit_addon', False)]
                
                # Should now have 2 services (original + new)
                if len(main_services_final) == 2:
                    tester.log("✅ CREATE NEW FLOW PASSED: Service count increased to 2 (new service created)", "PASS")
                    for svc in main_services_final:
                        tester.log(f"  - Service: {svc['xtream_username']} (ID: {svc['id']})", "INFO")
                else:
                    tester.log(f"❌ CREATE NEW FLOW FAILED: Expected 2 services, found {len(main_services_final)}", "FAIL")
    
    # Print summary
    return tester.print_summary()


if __name__ == "__main__":
    sys.exit(main())
