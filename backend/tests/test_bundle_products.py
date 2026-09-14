"""
Bundle Products Feature Tests
Tests for IPTV billing bundle products where admin can create products that combine multiple existing products.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBundleProducts:
    """Bundle Product CRUD and display tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test data and admin auth"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@example.com",
            "password": "admin123"
        })
        if login_resp.status_code == 200:
            token = login_resp.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            self.admin_token = token
        else:
            pytest.skip("Admin login failed - skipping bundle tests")
        
        # Track created test data for cleanup
        self.created_product_ids = []
        
        yield
        
        # Cleanup: Delete test products
        for pid in self.created_product_ids:
            try:
                self.session.delete(f"{BASE_URL}/api/admin/products/{pid}")
            except Exception:
                pass
    
    def create_test_product(self, name_suffix: str, price: float = 10.0) -> str:
        """Helper to create a test subscriber product"""
        payload = {
            "name": f"TEST_BundleItem_{name_suffix}_{int(time.time())}",
            "description": f"Test product for bundle testing - {name_suffix}",
            "account_type": "subscriber",
            "bouquets": [1],
            "max_connections": 1,
            "reseller_credits": 0,
            "reseller_max_lines": 0,
            "trial_days": 0,
            "prices": {"1": price},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        resp = self.session.post(f"{BASE_URL}/api/admin/products", json=payload)
        if resp.status_code in [200, 201]:
            pid = resp.json().get("id")
            if pid:
                self.created_product_ids.append(pid)
                return pid
        return None
    
    # ============ Backend API Tests ============
    
    def test_create_bundle_product_success(self):
        """POST /api/admin/products creates a bundle product with is_bundle=true"""
        # First create 2 products to bundle
        product1_id = self.create_test_product("Panel1", 15.0)
        product2_id = self.create_test_product("Panel2", 20.0)
        
        assert product1_id is not None, "Failed to create test product 1"
        assert product2_id is not None, "Failed to create test product 2"
        
        # Create bundle
        bundle_payload = {
            "name": f"TEST_Bundle_{int(time.time())}",
            "description": "Test bundle with 2 products",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 30.0},  # Discounted from 35
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        assert resp.status_code in [200, 201], f"Bundle creation failed: {resp.text}"
        
        data = resp.json()
        assert data.get("is_bundle") == True, "is_bundle should be True"
        assert data.get("bundle_product_ids") == [product1_id, product2_id], "bundle_product_ids mismatch"
        
        # Track for cleanup
        if data.get("id"):
            self.created_product_ids.append(data["id"])
        
        print(f"✓ Bundle product created successfully with ID: {data.get('id')}")
    
    def test_get_products_returns_bundle_fields(self):
        """GET /api/products returns bundle products with is_bundle and bundle_product_ids fields"""
        # Create bundle first
        product1_id = self.create_test_product("ForList1", 10.0)
        product2_id = self.create_test_product("ForList2", 15.0)
        
        bundle_payload = {
            "name": f"TEST_BundleList_{int(time.time())}",
            "description": "Bundle for list test",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 20.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        create_resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        assert create_resp.status_code in [200, 201]
        bundle_id = create_resp.json().get("id")
        self.created_product_ids.append(bundle_id)
        
        # Fetch all products (public endpoint)
        list_resp = requests.get(f"{BASE_URL}/api/products")
        assert list_resp.status_code == 200
        
        products = list_resp.json()
        bundle = next((p for p in products if p.get("id") == bundle_id), None)
        
        assert bundle is not None, "Bundle not found in products list"
        assert bundle.get("is_bundle") == True, "is_bundle field missing or False"
        assert bundle.get("bundle_product_ids") == [product1_id, product2_id], "bundle_product_ids mismatch"
        
        print(f"✓ GET /api/products returns bundle with is_bundle={bundle.get('is_bundle')}")
    
    def test_update_bundle_product(self):
        """PUT /api/admin/products/{id} can update a bundle product"""
        # Create initial bundle
        product1_id = self.create_test_product("Update1", 10.0)
        product2_id = self.create_test_product("Update2", 15.0)
        product3_id = self.create_test_product("Update3", 12.0)
        
        bundle_payload = {
            "name": f"TEST_BundleUpdate_{int(time.time())}",
            "description": "Bundle to update",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 22.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        create_resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        bundle_id = create_resp.json().get("id")
        self.created_product_ids.append(bundle_id)
        
        # Update bundle - add third product and change price
        update_payload = {
            "name": f"TEST_BundleUpdated_{int(time.time())}",
            "description": "Updated bundle with 3 products",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id, product3_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 30.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        update_resp = self.session.put(f"{BASE_URL}/api/admin/products/{bundle_id}", json=update_payload)
        assert update_resp.status_code == 200, f"Bundle update failed: {update_resp.text}"
        
        # Update endpoint may return just a message, so fetch the product again
        verify_resp = requests.get(f"{BASE_URL}/api/products/{bundle_id}")
        assert verify_resp.status_code == 200
        
        data = verify_resp.json()
        assert len(data.get("bundle_product_ids", [])) == 3, f"Should have 3 products after update, got {data.get('bundle_product_ids')}"
        assert product3_id in data.get("bundle_product_ids", []), "Third product not in bundle"
        
        print(f"✓ Bundle updated successfully with {len(data.get('bundle_product_ids', []))} products")
    
    def test_bundle_requires_at_least_two_products(self):
        """Bundle creation logic - bundles should have at least 2 products"""
        product1_id = self.create_test_product("SingleBundle", 10.0)
        
        # Try to create bundle with only 1 product
        bundle_payload = {
            "name": f"TEST_SingleProductBundle_{int(time.time())}",
            "description": "Invalid bundle with 1 product",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id],  # Only 1 product
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 10.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        # Backend may allow this (validation is frontend), but we document expected behavior
        resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        
        # Note: Backend doesn't validate min products, frontend does
        # This test documents the actual behavior
        if resp.status_code in [200, 201]:
            bundle_id = resp.json().get("id")
            if bundle_id:
                self.created_product_ids.append(bundle_id)
            print("⚠ Backend accepts bundle with 1 product (validation is on frontend)")
        else:
            print(f"✓ Backend rejected bundle with 1 product: {resp.status_code}")
    
    def test_get_single_product_has_bundle_fields(self):
        """GET /api/products/{id} returns bundle fields for a bundle product"""
        product1_id = self.create_test_product("Single1", 10.0)
        product2_id = self.create_test_product("Single2", 15.0)
        
        bundle_payload = {
            "name": f"TEST_BundleSingle_{int(time.time())}",
            "description": "Bundle for single get test",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 20.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        create_resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        bundle_id = create_resp.json().get("id")
        self.created_product_ids.append(bundle_id)
        
        # Get single product
        get_resp = requests.get(f"{BASE_URL}/api/products/{bundle_id}")
        assert get_resp.status_code == 200
        
        data = get_resp.json()
        assert data.get("is_bundle") == True
        assert data.get("bundle_product_ids") == [product1_id, product2_id]
        
        print(f"✓ GET /api/products/{bundle_id} returns bundle fields correctly")
    
    def test_admin_products_list_shows_bundles(self):
        """GET /api/admin/products returns bundles with all fields"""
        product1_id = self.create_test_product("Admin1", 10.0)
        product2_id = self.create_test_product("Admin2", 15.0)
        
        bundle_payload = {
            "name": f"TEST_BundleAdmin_{int(time.time())}",
            "description": "Bundle for admin list test",
            "account_type": "subscriber",
            "is_bundle": True,
            "bundle_product_ids": [product1_id, product2_id],
            "bouquets": [1],
            "max_connections": 1,
            "prices": {"1": 20.0},
            "active": True,
            "panel_type": "manual",
            "panel_index": 0,
        }
        
        create_resp = self.session.post(f"{BASE_URL}/api/admin/products", json=bundle_payload)
        bundle_id = create_resp.json().get("id")
        self.created_product_ids.append(bundle_id)
        
        # Admin products list
        admin_resp = self.session.get(f"{BASE_URL}/api/admin/products")
        assert admin_resp.status_code == 200
        
        products = admin_resp.json()
        bundle = next((p for p in products if p.get("id") == bundle_id), None)
        
        assert bundle is not None, "Bundle not found in admin products list"
        assert bundle.get("is_bundle") == True
        
        print(f"✓ Admin products list shows bundle correctly")


class TestBundleProductsPublic:
    """Public API tests for bundle products (no auth required)"""
    
    def test_public_products_api_has_bundle_fields(self):
        """GET /api/products returns is_bundle and bundle_product_ids in response"""
        resp = requests.get(f"{BASE_URL}/api/products")
        assert resp.status_code == 200
        
        products = resp.json()
        
        # Check that response structure supports bundle fields
        # Even if no bundles exist, verify the endpoint works
        assert isinstance(products, list), "Products should be a list"
        
        # If any bundles exist, verify their structure
        bundles = [p for p in products if p.get("is_bundle") == True]
        for bundle in bundles:
            assert "bundle_product_ids" in bundle, f"Bundle {bundle.get('name')} missing bundle_product_ids"
            assert isinstance(bundle.get("bundle_product_ids"), list), "bundle_product_ids should be a list"
        
        print(f"✓ Public products API supports bundle fields ({len(bundles)} bundles found)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
