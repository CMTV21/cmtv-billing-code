import requests
import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import logging
import re

logger = logging.getLogger(__name__)

async def xtream_api_call(panel: dict, action: str, extra_data: dict = None) -> dict:
    """JSON POST to XtreamUI panels exposing an api_key-based reseller_api.php endpoint."""
    import httpx
    api_key = panel.get("api_key", "")
    panel_url = panel.get("panel_url", "").rstrip("/")
    
    if not panel_url.endswith(".php"):
        panel_url = f"{panel_url}/reseller_api.php"
    
    payload = {"api_key": api_key, "action": action}
    if extra_data:
        payload.update(extra_data)
    
    logger.info(f"XtreamAPI POST {panel_url} action={action}")
    
    async with httpx.AsyncClient(verify=panel.get("ssl_verify", False), timeout=30.0) as client:
        resp = await client.post(
            panel_url,
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        logger.info(f"XtreamAPI response: status={resp.status_code}, body={resp.text[:500]}")
        
        data = resp.json()
        
        if isinstance(data, dict) and data.get("status") == "error":
            raise Exception(data.get("message", "API error"))
        
        resp.raise_for_status()
        return data


class XtreamUIService:
    """XtreamUI R22F API Service - Python version of WHMCS module"""
    
    def __init__(self, panel_url: str, admin_username: str, admin_password: str, ssl_verify: bool = False,
                 http_basic_user: str = None, http_basic_pass: str = None, proxy_url: str = None, api_key: str = None):
        self.panel_url = panel_url.rstrip('/')
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.ssl_verify = ssl_verify
        self.http_basic_user = http_basic_user
        self.http_basic_pass = http_basic_pass
        self.proxy_url = proxy_url
        self.api_key = api_key or None
        self.session = requests.Session()
        # Use separate basic auth if provided, otherwise panel creds
        if http_basic_user and http_basic_pass:
            self.session.auth = (http_basic_user, http_basic_pass)
        else:
            self.session.auth = (admin_username, admin_password)
        self.session.verify = ssl_verify
        if proxy_url:
            self.session.proxies = {'http': proxy_url, 'https': proxy_url}
        self._session_client = None  # Persistent session client
    
    def _make_request(self, endpoint: str, method: str = 'GET', data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make API request to XtreamUI panel"""
        url = f"{self.panel_url}{endpoint}"
        
        # Inject api_key into POST data if configured
        if self.api_key and method == 'POST' and data is not None:
            data['api_key'] = self.api_key
        
        try:
            logger.info(f"XtreamUI API: {method} {endpoint}")
            
            if method == 'GET':
                response = self.session.get(url, timeout=30)
            elif method == 'POST':
                response = self.session.post(url, data=data, timeout=30)
            elif method == 'DELETE':
                response = self.session.delete(url, params=data, timeout=30)
            else:
                return {'success': False, 'error': f'Unsupported method: {method}'}
            
            logger.info(f"XtreamUI Response: {response.status_code}")
            
            # R22F returns 200 for success even with non-JSON
            if response.status_code == 200:
                return {
                    'success': True,
                    'data': response.text,
                    'status_code': response.status_code
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}',
                    'data': response.text
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"XtreamUI API Error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to XtreamUI panel"""
        return self._make_request('/api.php?action=test', 'GET')
    
    def create_subscriber(self, username: str, password: str, bouquets: List[int], 
                         max_connections: int, expiry_date: int) -> Dict[str, Any]:
        """Create subscriber line - DEPRECATED: Use create_subscriber_via_form instead"""
        data = {
            'username': username,
            'password': password,
            'exp_date': expiry_date,
            'max_connections': max_connections,
            'bouquets': json.dumps(bouquets)
        }
        return self._make_request('/api.php?action=user', 'POST', data)
    
    def create_subscriber_via_form(self, username: str, password: str, package_id: int, 
                                   bouquets: list, customer_name: str = None,
                                   is_trial: bool = False, exp_date: int = None) -> Dict[str, Any]:
        """
        Create subscriber via reseller form POST (associates with reseller & deducts credits)
        This is the correct method for reseller-owned accounts
        """
        try:
            # First login to get session
            self.session.post(
                f"{self.panel_url}/login.php",
                data={'username': self.admin_username, 'password': self.admin_password},
                timeout=30
            )
            
            if 'PHPSESSID' not in self.session.cookies:
                return {'success': False, 'error': 'Login failed - no session'}
            
            # Build reseller notes with customer name
            reseller_notes = f"IPTV Billing System: {customer_name}" if customer_name else "IPTV Billing System"
            
            # Get reseller member_id by fetching the form page
            member_id = '0'
            soup = None
            try:
                from bs4 import BeautifulSoup
                page_url = f"{self.panel_url}/user_reseller.php?trial" if is_trial else f"{self.panel_url}/user_reseller.php"
                page_resp = self.session.get(page_url, timeout=15)
                if page_resp.status_code == 200:
                    soup = BeautifulSoup(page_resp.text, 'html.parser')
                    member_select = soup.find('select', {'name': 'member_id'})
                    if member_select:
                        options = member_select.find_all('option')
                        # Find the option matching the logged-in reseller username
                        for opt in options:
                            if opt.text.strip().lower() == self.admin_username.lower():
                                member_id = opt.get('value', '0')
                                logger.info(f"Matched member_id {member_id} for reseller '{self.admin_username}'")
                                break
                        if member_id == '0' and options:
                            # Fallback: use first option if no match found
                            member_id = options[0].get('value', '0')
                            logger.warning(f"Could not match reseller '{self.admin_username}', using first member_id: {member_id}")
            except Exception as e:
                logger.warning(f"Could not auto-detect member_id: {e}")
            
            # Submit form to create user
            form_data = {
                'username': username,
                'password': password,
                'package': str(package_id),
                'member_id': member_id,
                'reseller_notes': reseller_notes,
                'bouquets_selected': json.dumps(bouquets),
            }

            # GhostAPK: if the reseller has it connected, the form exposes a 'ghostapk_sync' checkbox
            ghostapk_enabled = bool(soup and soup.find('input', {'name': 'ghostapk_sync'}))
            if ghostapk_enabled:
                form_data['ghostapk_sync'] = '1'
                logger.info("GhostAPK connected for reseller - requesting login pin generation")
            
            # Trial form has a hidden 'trial' field and submit value is 'Purchase'
            if is_trial:
                form_data['trial'] = '1'
                form_data['submit_user'] = 'Purchase'
            else:
                form_data['submit_user'] = '1'
            
            logger.info(f"Creating user via form: url={'?trial' if is_trial else ''}, package={package_id}, is_trial={is_trial}, member_id={member_id}")
            
            # Trial users use a different form URL
            form_url = f"{self.panel_url}/user_reseller.php?trial" if is_trial else f"{self.panel_url}/user_reseller.php"
            
            response = self.session.post(
                form_url,
                data=form_data,
                allow_redirects=False,
                timeout=30
            )
            
            logger.info(f"Form POST status: {response.status_code}")
            
            if response.status_code == 302:
                redirect_url = response.headers.get('Location', '')
                if 'user_reseller.php?id=' in redirect_url:
                    user_id = redirect_url.split('id=')[1].split('&')[0] if '=' in redirect_url else 'unknown'
                    logger.info(f"User created successfully: {username} (ID: {user_id})")
                    ghostapk_code = ""
                    if ghostapk_enabled:
                        ghostapk_code = self.get_ghostapk_code(username, password, login=False)
                    return {
                        'success': True,
                        'user_id': user_id,
                        'username': username,
                        'ghostapk_code': ghostapk_code,
                        'message': f'User created under reseller (ID: {user_id})'
                    }
            
            return {
                'success': False,
                'error': f'Form POST returned {response.status_code}',
                'response': response.text[:200]
            }
            
        except Exception as e:
            logger.error(f"Form POST error: {e}")
            return {'success': False, 'error': str(e)}

    def _session_login(self) -> bool:
        """Login the reseller web session (HTTP basic auth is already on the session)"""
        self.session.post(
            f"{self.panel_url}/login.php",
            data={'username': self.admin_username, 'password': self.admin_password},
            timeout=30
        )
        return 'PHPSESSID' in self.session.cookies

    def get_ghostapk_status(self) -> Dict[str, Any]:
        """Check whether this reseller has GhostAPK connected on the panel"""
        try:
            if not self._session_login():
                return {'connected': False, 'error': 'Login failed'}
            resp = self.session.get(f"{self.panel_url}/api.php", params={'action': 'ghostapk_status'}, timeout=15)
            if resp.status_code != 200 or not resp.text.strip():
                return {'connected': False, 'error': f'HTTP {resp.status_code}'}
            data = resp.json()
            return {'connected': bool(data.get('connected')), 'panel_url': data.get('panel_url', '')}
        except Exception as e:
            logger.warning(f"GhostAPK status check failed: {e}")
            return {'connected': False, 'error': str(e)}

    def get_ghostapk_code(self, username: str, password: str, login: bool = True) -> str:
        """Fetch the GhostAPK login pin for a line (empty string if none)"""
        try:
            if login and not self._session_login():
                return ""
            resp = self.session.get(
                f"{self.panel_url}/api.php",
                params={'action': 'get_label_data', 'username': username, 'password': password},
                timeout=15
            )
            if resp.status_code != 200 or not resp.text.strip():
                return ""
            data = resp.json()
            code = str(data.get('gapk_code') or "").strip()
            if code:
                logger.info(f"GhostAPK pin retrieved for {username}")
            return code
        except Exception as e:
            logger.warning(f"GhostAPK code fetch failed for {username}: {e}")
            return ""

    def ghostapk_sync_all(self) -> Dict[str, Any]:
        """Ask the panel to sync all of this reseller's lines to GhostAPK (generates pins)"""
        try:
            if not self._session_login():
                return {'success': False, 'error': 'Login failed'}
            resp = self.session.get(f"{self.panel_url}/api.php", params={'action': 'ghostapk_sync_all'}, timeout=310)
            if resp.status_code != 200 or not resp.text.strip():
                return {'success': False, 'error': f'HTTP {resp.status_code}'}
            data = resp.json()
            if not data.get('result'):
                return {'success': False, 'error': data.get('message', 'Sync failed')}
            return {
                'success': True,
                'created': data.get('created', 0),
                'updated': data.get('updated', 0),
                'codes_generated': data.get('codes_generated', 0),
                'errors': data.get('errors', []),
            }
        except Exception as e:
            logger.error(f"GhostAPK sync-all failed: {e}")
            return {'success': False, 'error': str(e)}
    

    def create_subscriber_via_api(self, username: str, password: str, package_id: int,
                                  bouquets: list, max_connections: int = 1,
                                  is_trial: bool = False, exp_date: int = None,
                                  reseller_notes: str = "") -> Dict[str, Any]:
        """Create subscriber via XtreamUI API (supports trial packages properly)"""
        try:
            user_data = {
                'username': username,
                'password': password,
                'max_connections': str(max_connections),
                'is_trial': '1' if is_trial else '0',
                'bouquet': json.dumps(bouquets) if bouquets else '[]',
                'reseller_notes': reseller_notes,
            }
            
            if package_id:
                user_data['package_id'] = str(package_id)
            
            if exp_date:
                user_data['exp_date'] = str(exp_date)
            
            post_data = {
                'username': self.admin_username,
                'password': self.admin_password,
                'user_data': json.dumps(user_data)
            }
            
            logger.info(f"Creating user via API: package={package_id}, is_trial={is_trial}, exp_date={exp_date}")
            
            response = self.session.post(
                f"{self.panel_url}/api.php?action=user&sub=create",
                data=post_data,
                timeout=30
            )
            
            logger.info(f"API create response: {response.status_code} - {response.text[:300]}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('success') or result.get('result'):
                        return {
                            'success': True,
                            'user_id': result.get('user_id', result.get('id', 'unknown')),
                            'username': username,
                            'message': 'User created via API'
                        }
                    else:
                        return {'success': False, 'error': result.get('error', result.get('message', 'API returned failure'))}
                except json.JSONDecodeError:
                    # Some XtreamUI versions return plain text
                    if 'success' in response.text.lower() or response.text.strip() == '1':
                        return {'success': True, 'username': username, 'message': 'User created via API'}
                    return {'success': False, 'error': f'Unexpected API response: {response.text[:200]}'}
            
            return {'success': False, 'error': f'API returned HTTP {response.status_code}'}
            
        except Exception as e:
            logger.error(f"API create error: {e}")
            return {'success': False, 'error': str(e)}


    def _get_session_client(self):
        """Get or create persistent session client (WHMCS pattern)"""
        if self._session_client is None:
            from xtreamui_session_client import XtreamUISessionClient
            
            self._session_client = XtreamUISessionClient(
                panel_url=self.panel_url,
                username=self.admin_username,
                password=self.admin_password,
                ssl_verify=self.ssl_verify,
                http_basic_user=self.http_basic_user,
                http_basic_pass=self.http_basic_pass,
                proxy_url=self.proxy_url
            )
        
        return self._session_client
    
    def create_reseller(self, username: str, password: str, credits: float, email: str = "", member_group_id: int = 2) -> Dict[str, Any]:
        """Create reseller using persistent session"""
        try:
            # Get persistent session client (same instance each time)
            session_client = self._get_session_client()
            
            # Login if not already logged in
            if not session_client.logged_in:
                if not session_client.login():
                    return {'success': False, 'error': 'Failed to login to XtreamUI panel'}
            
            # Create reseller (session persists in cookie file)
            result = session_client.create_reseller(
                username=username,
                password=password,
                credits=credits,
                email=email,
                member_group_id=member_group_id
            )
            return result
                
        except Exception as e:
            logger.error(f"Session-based reseller creation failed: {str(e)}")
            return {'success': False, 'error': str(e)}

    def get_live_streams_by_category(self, category_id: int) -> Dict[str, Any]:
        """Get live streams for a specific category/bouquet using XtreamUI table API"""
        try:
            # Use session client to access the admin panel table API
            session_client = self._get_session_client()
            if not session_client:
                return {"success": False, "error": "Failed to initialize session", "streams": []}
            
            # Login to admin panel
            if not session_client.login():
                return {"success": False, "error": "Login failed", "streams": []}
            
            # Use the table.php API that XtreamUI provides
            # This endpoint returns streams filtered by category_id
            url = f"{self.panel_url}/table.php"
            params = {
                "id": "streams_short",
                "category_id": category_id,
                "start": 0,
                "length": 500  # Get up to 500 channels
            }
            
            response = session_client.session.get(url, params=params, timeout=20)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    streams = []
                    
                    # XtreamUI table API returns data in 'data' array
                    if isinstance(data, dict) and 'data' in data:
                        for row in data['data']:
                            # row format: [id, stream_display_name, category_name, buttons]
                            if len(row) >= 2:
                                streams.append({
                                    "stream_id": row[0],
                                    "name": row[1]
                                })
                    
                    return {
                        "success": True,
                        "streams": streams,
                        "count": len(streams)
                    }
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Failed to parse JSON: {str(e)}")
                    return {"success": False, "error": "Invalid JSON response", "streams": []}
            else:
                logger.error(f"Table API returned {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}", "streams": []}
                
        except Exception as e:
            return {"success": False, "error": str(e), "streams": []}
    
    def get_reseller_users(self) -> Dict[str, Any]:
        """Get all users owned by the reseller using DataTables API"""
        try:
            import time
            import requests
            
            session_client = self._get_session_client()
            if not session_client:
                return {"success": False, "error": "Failed to initialize session", "users": []}
            
            # Login to admin panel
            if not session_client.login():
                return {"success": False, "error": "Login failed", "users": []}
            
            logger.info("Session established, fetching users...")
            
            # Get our reseller member_id to filter only OUR users (not subreseller users)
            reseller_info = session_client.get_reseller_info()
            member_id = reseller_info.get('member_id', 0)
            
            if member_id:
                logger.info(f"Using detected member_id: {member_id}")
            else:
                logger.warning("Could not detect member_id, will return all visible users")
            
            # Build DataTables parameters - EXACT same format as extend_subscriber
            search_params = {
                'draw': '1',
                'order[0][column]': '0',
                'order[0][dir]': 'desc',
                'start': '0',
                'length': '5000',  # Get up to 5000 users
                'search[value]': '',  # Empty = get ALL users
                'search[regex]': 'false',
                'id': 'users',  # Table ID
                'filter': '',  # No status filter
                'reseller': str(member_id) if member_id else '',  # Filter by our reseller ID
                '_': str(int(time.time() * 1000))
            }
            
            # Add 12 columns (required by DataTables)
            for i in range(12):
                search_params[f'columns[{i}][data]'] = str(i)
                search_params[f'columns[{i}][name]'] = ''
                search_params[f'columns[{i}][searchable]'] = 'true'
                search_params[f'columns[{i}][orderable]'] = 'true'
                search_params[f'columns[{i}][search][value]'] = ''
                search_params[f'columns[{i}][search][regex]'] = ''
            
            # Build URL with query string (same as extend_subscriber)
            # Use session_client.panel_url which has been cleaned (no embedded credentials)
            search_url = f"{session_client.panel_url}/table_search.php"
            query_string_url = f"{search_url}?{requests.compat.urlencode(search_params)}"
            
            logger.info("Fetching users from table_search.php...")
            
            # Try GET first (some panels only respond to GET), fallback to POST
            search_url = f"{session_client.panel_url}/table_search.php"
            response = session_client.session.get(
                search_url,
                params=search_params,
                auth=session_client.http_auth,
                timeout=30
            )
            
            if response.status_code == 200 and len(response.text.strip()) == 0:
                response = session_client.session.post(
                    search_url,
                    data=search_params,
                    auth=session_client.http_auth,
                    timeout=30
                )
            
            logger.info(f"Response: status={response.status_code}, length={len(response.text)}")
            
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}", "users": []}
            
            if len(response.text) == 0:
                return {"success": False, "error": "Empty response", "users": []}
            
            try:
                result = response.json()
            except Exception as e:
                logger.error(f"JSON parse error: {str(e)}")
                logger.error(f"Response text: {response.text[:500]}")
                return {"success": False, "error": "Invalid JSON response", "users": []}
            
            records_total = result.get('recordsTotal', 0)
            logger.info(f"Records total: {records_total}")
            
            users_data = result.get('data', [])
            if not users_data:
                logger.warning("No users found in response")
                return {"success": True, "users": [], "count": 0}
            
            logger.info(f"✓ SUCCESS! Found {len(users_data)} users")
            
            # Parse user data from DataTables response
            # Format based on test: [id, username, password, owner, status_icons..., expiry, connections, max_conn, ...]
            users = []
            import re
            from panel_expiry import row_expiry, to_panel_string
            
            conn_re = re.compile(r'^\d+\s*/\s*(\d+)$')

            def _strip(cell) -> str:
                return re.sub(r'<[^>]+>', '', str(cell).replace('<br>', ' ').replace('<br/>', ' ')).strip()

            def _find_expiry(row) -> tuple:
                # Prefer the exact epoch XtreamUI embeds in data-order (timezone-safe); fall back to displayed text
                dt, unlimited, raw = row_expiry(row)
                return to_panel_string(dt, unlimited), raw

            def _find_max_conn(row) -> str:
                for idx in range(3, len(row)):
                    text = _strip(row[idx])
                    m = conn_re.match(text)
                    if m:
                        return m.group(1)
                if len(row) > 9:
                    fallback = _strip(row[9])
                    if fallback.isdigit():
                        return fallback
                return "1"

            for row in users_data:
                if len(row) >= 2:
                    # Extract username - may be wrapped in <strong> tags
                    username_raw = str(row[1]) if len(row) > 1 else ""
                    username = re.sub(r'<[^>]+>', '', username_raw).strip()
                    
                    # Extract password (column 2)
                    password = _strip(row[2]) if len(row) > 2 else ""
                    
                    expiry, expiry_raw = _find_expiry(row)
                    
                    # Log first few to help debug expiry format issues
                    if len(users) < 3:
                        logger.info(f"User {username}: expiry_raw='{expiry_raw[:60]}', parsed='{expiry}'")
                        if not expiry:
                            logger.info(f"User {username} full row: {[_strip(c)[:40] for c in row]}")
                    
                    max_conn = _find_max_conn(row)
                    
                    # Extract user ID (column 0)
                    user_id = _strip(row[0]) if len(row) > 0 else ""
                    
                    # Determine status from icons (scan status icon cells for disabled markers)
                    status = "active"
                    for idx in range(3, min(len(row), 8)):
                        cell = str(row[idx])
                        if '<i' in cell and ("text-danger" in cell or "fa-times" in cell or "fa-ban" in cell):
                            status = "disabled"
                            break
                    
                    users.append({
                        "user_id": user_id,
                        "username": username,
                        "password": password,
                        "expiry": expiry,
                        "max_connections": max_conn,
                        "status": status,
                    })
            
            return {
                "success": True,
                "users": users,
                "count": len(users)
            }
                
        except Exception as e:
            logger.error(f"Failed to fetch reseller users: {str(e)}")
            return {"success": False, "error": str(e), "users": []}
    
    def get_subresellers(self) -> Dict[str, Any]:
        """Get all subresellers (reg_users) owned by the reseller using DataTables API"""
        try:
            import time
            import requests
            
            session_client = self._get_session_client()
            if not session_client:
                return {"success": False, "error": "Failed to initialize session", "users": []}
            
            # Login to admin panel
            if not session_client.login():
                return {"success": False, "error": "Login failed", "users": []}
            
            logger.info("Session established, fetching subresellers...")
            
            # Build DataTables parameters for reg_users table
            search_params = {
                'draw': '1',
                'order[0][column]': '0',
                'order[0][dir]': 'desc',
                'start': '0',
                'length': '5000',  # Get up to 5000 resellers
                'search[value]': '',  # Empty = get ALL
                'search[regex]': 'false',
                'id': 'reg_users',  # Table ID for resellers/subresellers
                'filter': '',
                'reseller': '',  # Empty to get all under current reseller
                '_': str(int(time.time() * 1000))
            }
            
            # Add 12 columns (required by DataTables)
            for i in range(12):
                search_params[f'columns[{i}][data]'] = str(i)
                search_params[f'columns[{i}][name]'] = ''
                search_params[f'columns[{i}][searchable]'] = 'true'
                search_params[f'columns[{i}][orderable]'] = 'true'
                search_params[f'columns[{i}][search][value]'] = ''
                search_params[f'columns[{i}][search][regex]'] = ''
            
            # Build URL with query string
            search_url = f"{session_client.panel_url}/table_search.php"
            query_string_url = f"{search_url}?{requests.compat.urlencode(search_params)}"
            
            logger.info("Fetching subresellers from table_search.php (reg_users)...")
            
            # Try GET first (some panels only respond to GET), fallback to POST
            response = session_client.session.get(
                search_url,
                params=search_params,
                auth=session_client.http_auth,
                timeout=30
            )
            
            if response.status_code == 200 and len(response.text.strip()) == 0:
                response = session_client.session.post(
                    search_url,
                    data=search_params,
                    auth=session_client.http_auth,
                    timeout=30
                )
            
            logger.info(f"Response: status={response.status_code}, length={len(response.text)}")
            
            if response.status_code != 200:
                return {"success": False, "error": f"HTTP {response.status_code}", "users": []}
            
            if len(response.text) == 0:
                return {"success": False, "error": "Empty response", "users": []}
            
            try:
                result = response.json()
            except Exception as e:
                logger.error(f"JSON parse error: {str(e)}")
                return {"success": False, "error": "Invalid JSON response", "users": []}
            
            records_total = result.get('recordsTotal', 0)
            logger.info(f"Records total: {records_total}")
            
            users_data = result.get('data', [])
            if not users_data:
                logger.warning("No subresellers found in response")
                return {"success": True, "users": [], "count": 0}
            
            logger.info(f"✓ SUCCESS! Found {len(users_data)} subresellers")
            
            # Parse subreseller data from DataTables response
            # Format: [id, username, owner, email?, member_group, status_icon, credits, ?, expiry, ...]
            users = []
            import re
            
            for row in users_data:
                if len(row) >= 2:
                    # Extract user ID (column 0)
                    user_id = str(row[0]) if len(row) > 0 else ""
                    
                    # Extract username (column 1)
                    username = str(row[1]) if len(row) > 1 else ""
                    
                    # Extract owner/parent reseller (column 2)
                    owner = str(row[2]) if len(row) > 2 else ""
                    
                    # Extract member group (column 4) - e.g., "Tier 3 Reseller"
                    member_group = str(row[4]) if len(row) > 4 else ""
                    
                    # Extract credits (column 6)
                    credits = str(row[6]) if len(row) > 6 else "0"
                    
                    # Extract expiry (column 8) - usually "NEVER" for resellers
                    expiry = str(row[8]) if len(row) > 8 else "NEVER"
                    
                    users.append({
                        "user_id": user_id,
                        "username": username,
                        "owner": owner,
                        "member_group": member_group,
                        "credits": credits,
                        "expiry": expiry,
                        "status": "active",  # TODO: Parse from status icon
                    })
            
            # Filter to only include our DIRECT subresellers (where owner = our username)
            our_username = self.admin_username
            direct_subresellers = [u for u in users if u.get('owner', '').lower() == our_username.lower()]
            
            logger.info(f"Filtered to {len(direct_subresellers)} direct subresellers (owned by '{our_username}')")
            
            return {
                "success": True,
                "users": direct_subresellers,
                "count": len(direct_subresellers)
            }
                
        except Exception as e:
            logger.error(f"Failed to fetch subresellers: {str(e)}")
            return {"success": False, "error": str(e), "users": []}
    
    def _scrape_users_from_page(self, session_client) -> Dict[str, Any]:
        """Fallback: Scrape users from users.php HTML page"""
        try:
            # First verify session by accessing dashboard
            dashboard_url = f"{self.panel_url}/dashboard.php"
            dash_response = session_client.session.get(dashboard_url, timeout=15)
            logger.info(f"Dashboard check: status={dash_response.status_code}, has 'logout'={('logout' in dash_response.text.lower())}")
            
            if 'login' in dash_response.text.lower() and 'logout' not in dash_response.text.lower():
                logger.warning("Session expired, re-logging in...")
                if not session_client.login():
                    return {"success": False, "error": "Re-login failed", "users": []}
            
            # Now try users.php with fresh session
            url = f"{self.panel_url}/users.php"
            response = session_client.session.get(url, timeout=30)
            
            logger.info(f"Scraping users.php: status={response.status_code}, length={len(response.text)}")
            logger.info(f"Page has logout link: {('logout' in response.text.lower())}")
            logger.info(f"Page is login page: {('login.php' in response.text.lower() and 'logout' not in response.text.lower())}")
            
            if response.status_code == 200:
                # Check if we got login page instead of users page
                if 'login.php' in response.text and 'logout' not in response.text.lower():
                    logger.error("Got login page instead of users page - session authentication failed")
                    # Save for debugging
                    with open('/tmp/users_page_response.html', 'w') as f:
                        f.write(response.text)
                    return {"success": False, "error": "Session not authenticated for users.php", "users": []}
                
                # We have the actual users page - parse it
                with open('/tmp/users_page_response.html', 'w') as f:
                    f.write(response.text)
                
                users = []
                import re
                
                # Look for username patterns in the actual content
                # Try to find table rows or data structures
                username_patterns = [
                    r'<td[^>]*>([a-zA-Z0-9_-]{3,30})</td>',
                    r'data-id=["\'](\d+)["\'][^>]*>([a-zA-Z0-9_-]+)',
                    r'"username":\s*"([^"]+)"',
                ]
                
                for pattern in username_patterns:
                    matches = re.findall(pattern, response.text)
                    if matches:
                        logger.info(f"Found {len(matches)} potential usernames with pattern")
                        for match in matches[:50]:
                            username = match if isinstance(match, str) else match[-1]
                            if len(username) >= 3 and len(username) <= 30:
                                users.append({
                                    "username": username,
                                    "expiry": "",
                                    "max_connections": "1",
                                    "status": "active",
                                    "password": ""
                                })
                        if users:
                            break
                
                # Remove duplicates
                unique_users = []
                seen = set()
                for user in users:
                    if user["username"] not in seen and user["username"] not in ['username', 'admin', 'root', 'user']:
                        seen.add(user["username"])
                        unique_users.append(user)
                
                logger.info(f"Extracted {len(unique_users)} unique usernames")
                
                return {
                    "success": len(unique_users) > 0,
                    "users": unique_users,
                    "count": len(unique_users),
                    "note": "Check /tmp/users_page_response.html if extraction failed"
                }
            else:
                return {"success": False, "error": f"HTTP {response.status_code}", "users": []}
                
        except Exception as e:
            logger.error(f"HTML scraping failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e), "users": []}
    
    def add_credits(self, username: str, email: str, credits: float) -> Dict[str, Any]:
        """Add credits using SAME session as create_reseller"""
        try:
            # Get SAME session client (reuses cookies!)
            session_client = self._get_session_client()
            
            # Session already established from create_reseller
            # Cookies loaded from file automatically
            if not session_client.logged_in:
                logger.info("Session not active, logging in...")
                if not session_client.login():
                    return {'success': False, 'error': 'Failed to login'}
            
            # Add credits (uses same session/cookies)
            result = session_client.add_credits(
                username=username,
                email=email,
                credits=credits
            )
            return result
                
        except Exception as e:
            logger.error(f"Add credits failed: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def extend_subscriber(self, username: str, password: str, package_id: int, bouquets: list, max_connections: int, reseller_notes: str = "") -> Dict[str, Any]:
        """Extend existing subscriber expiry"""
        from xtreamui_session_client import XtreamUISessionClient
        
        try:
            session_client = self._get_session_client()
            
            if not session_client.logged_in:
                if not session_client.login():
                    return {'success': False, 'error': 'Failed to login'}
            
            result = session_client.extend_subscriber(
                username=username,
                password=password,  # Pass subscriber password
                package_id=package_id,
                bouquets=bouquets,
                max_connections=max_connections,
                reseller_notes=reseller_notes
            )
            return result
                
        except Exception as e:
            logger.error(f"Extend subscriber failed: {str(e)}")
            return {'success': False, 'error': str(e)}

    def suspend_account(self, username: str, password: str, user_id: str = None) -> Dict[str, Any]:
        """Suspend account - always use fresh session to ensure valid cookie"""
        try:
            from xtreamui_session_client import XtreamUISessionClient
            session_client = self._get_session_client()
            
            # Force fresh login to get valid PHPSESSID
            logger.info("Forcing fresh login for suspend operation")
            if not session_client.login():
                return {'success': False, 'error': 'Login failed'}
            
            # If user_id not provided, we need to search for it
            if not user_id:
                logger.info(f"Searching for user: {username}")
                import time
                
                search_params = {
                    'draw': '1',
                    'order[0][column]': '0',
                    'order[0][dir]': 'desc',
                    'start': '0',
                    'length': '25',
                    'search[value]': username,
                    'search[regex]': 'false',
                    'id': 'users',
                    'filter': '',
                    'reseller': '',
                    '_': str(int(time.time() * 1000))
                }
                
                for i in range(12):
                    search_params[f'columns[{i}][data]'] = str(i)
                    search_params[f'columns[{i}][searchable]'] = 'true'
                    search_params[f'columns[{i}][orderable]'] = 'true'
                    search_params[f'columns[{i}][search][value]'] = ''
                
                search_url = f"{session_client.panel_url}/table_search.php"
                search_response = session_client.session.get(
                    search_url,
                    params=search_params,
                    auth=session_client.http_auth,
                    timeout=30
                )
                if search_response.status_code == 200 and len(search_response.text.strip()) == 0:
                    search_response = session_client.session.post(
                        search_url, data=search_params, auth=session_client.http_auth, timeout=30
                    )
                
                logger.info(f"Search response: {search_response.status_code}")
                
                if search_response.status_code == 200 and search_response.text:
                    try:
                        result = search_response.json()
                        users_data = result.get('data', [])
                        
                        if users_data and len(users_data) > 0:
                            user_id = str(users_data[0][0])
                            logger.info(f"Found user_id from search: {user_id}")
                    except Exception as e:
                        logger.error(f"Search parse error: {e}")
                        return {'success': False, 'error': 'Search failed'}
                
                if not user_id:
                    return {'success': False, 'error': 'User not found'}
            
            # Now disable using the user_id
            logger.info(f"Disabling user_id: {user_id}")
            logger.info(f"HTTP Basic Auth: {session_client.http_auth}")
            logger.info(f"Session has cookies: {len(session_client.session.cookies)}")
            
            disable_url = f"{session_client.panel_url}/api.php?action=user&sub=disable&user_id={user_id}"
            
            headers = {
                'Referer': f'{session_client.panel_url}/users.php',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            # Try GET first (most XtreamUI versions), then POST as fallback
            disable_response = session_client.session.get(
                disable_url,
                auth=session_client.http_auth,
                headers=headers,
                timeout=30
            )
            
            logger.info(f"Disable response (GET): {disable_response.status_code}, body: {disable_response.text[:200]}")
            
            # If GET doesn't work, try POST
            if disable_response.status_code != 200 or ('"result":false' in disable_response.text.lower() and 'already' not in disable_response.text.lower()):
                disable_response = session_client.session.post(
                    disable_url,
                    auth=session_client.http_auth,
                    headers=headers,
                    timeout=30
                )
                logger.info(f"Disable response (POST): {disable_response.status_code}, body: {disable_response.text[:200]}")
            
            if disable_response.status_code == 200:
                try:
                    result = disable_response.json()
                    logger.info(f"Disable result: {result}")
                    # Check for both result=1 and result=true
                    if result.get('result') in [1, True, 'true', '1']:
                        logger.info(f"✓ User {username} disabled successfully")
                        return {'success': True}
                except Exception as e:
                    logger.warning(f"JSON parse error: {e}, response: {disable_response.text}")
                    pass
                
                # HTTP 200 = success
                return {'success': True}
            
            return {'success': False, 'error': f'HTTP {disable_response.status_code}'}
                    
        except Exception as e:
            logger.error(f"Suspend error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}
    
    def unsuspend_account(self, username: str, password: str, user_id: str = None) -> Dict[str, Any]:
        """Enable/unsuspend account - same as suspend but with sub=enable"""
        try:
            from xtreamui_session_client import XtreamUISessionClient
            session_client = self._get_session_client()
            
            # Force fresh login
            logger.info("Forcing fresh login for unsuspend operation")
            if not session_client.login():
                return {'success': False, 'error': 'Login failed'}
            
            # If no user_id, search for it (same as suspend)
            if not user_id:
                logger.info(f"Searching for user: {username}")
                import time
                
                search_params = {
                    'draw': '1',
                    'order[0][column]': '0',
                    'order[0][dir]': 'desc',
                    'start': '0',
                    'length': '25',
                    'search[value]': username,
                    'search[regex]': 'false',
                    'id': 'users',
                    'filter': '',
                    'reseller': '',
                    '_': str(int(time.time() * 1000))
                }
                
                for i in range(12):
                    search_params[f'columns[{i}][data]'] = str(i)
                    search_params[f'columns[{i}][searchable]'] = 'true'
                    search_params[f'columns[{i}][orderable]'] = 'true'
                    search_params[f'columns[{i}][search][value]'] = ''
                
                search_url = f"{session_client.panel_url}/table_search.php"
                search_response = session_client.session.get(
                    search_url, params=search_params, auth=session_client.http_auth, timeout=30
                )
                if search_response.status_code == 200 and len(search_response.text.strip()) == 0:
                    search_response = session_client.session.post(
                        search_url, data=search_params, auth=session_client.http_auth, timeout=30
                    )
                
                if search_response.status_code == 200 and search_response.text:
                    try:
                        result = search_response.json()
                        users_data = result.get('data', [])
                        
                        if users_data and len(users_data) > 0:
                            user_id = str(users_data[0][0])
                            logger.info(f"Found user_id: {user_id}")
                    except Exception as e:
                        logger.error(f"Search error: {e}")
                
                if not user_id:
                    return {'success': False, 'error': 'User not found'}
            
            # Enable using api.php?action=user&sub=enable&user_id=ID
            logger.info(f"Enabling user_id: {user_id}")
            enable_url = f"{session_client.panel_url}/api.php?action=user&sub=enable&user_id={user_id}"
            
            headers = {
                'Referer': f'{session_client.panel_url}/users.php',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            
            enable_response = session_client.session.get(
                enable_url, auth=session_client.http_auth, headers=headers, timeout=30
            )
            
            logger.info(f"Enable response (GET): {enable_response.status_code}, body: {enable_response.text[:200]}")
            
            if enable_response.status_code != 200 or ('"result":false' in enable_response.text.lower() and 'already' not in enable_response.text.lower()):
                enable_response = session_client.session.post(
                    enable_url, auth=session_client.http_auth, headers=headers, timeout=30
                )
                logger.info(f"Enable response (POST): {enable_response.status_code}, body: {enable_response.text[:200]}")
            
            if enable_response.status_code == 200:
                try:
                    result = enable_response.json()
                    if result.get('result') in [1, True, 'true', '1']:
                        logger.info(f"✓ User {username} enabled successfully")
                        return {'success': True}
                except Exception as e:
                    logger.warning(f"JSON parse error: {e}")
                    pass
                
                return {'success': True}
            
            return {'success': False, 'error': f'HTTP {enable_response.status_code}'}
                    
        except Exception as e:
            logger.error(f"Unsuspend error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}
    
    def terminate_account(self, username: str, password: str) -> Dict[str, Any]:
        """Terminate/delete account"""
        data = {
            'username': username,
            'password': password,
            'delete': 1
        }
        return self._make_request('/api.php?action=user', 'DELETE', data)
    
    def get_subscriber_info(self, username: str, password: str) -> Dict[str, Any]:
        """Get subscriber information"""
        endpoint = f'/api.php?action=user&username={username}&password={password}'
        return self._make_request(endpoint, 'GET')
    
    def get_reseller_info(self, username: str, password: str) -> Dict[str, Any]:
        """Get reseller information"""
        endpoint = f'/api.php?action=reseller&username={username}&password={password}'
        return self._make_request(endpoint, 'GET')
    
    def get_bouquets(self) -> Dict[str, Any]:
        """Get all available bouquets from XtreamUI panel"""
        # Try multiple endpoints for R22F
        endpoints_to_try = [
            '/api.php?action=get_bouquets',
            '/panel_api.php?action=get_bouquets',
            '/api.php?action=bouquets',
        ]
        
        for endpoint in endpoints_to_try:
            result = self._make_request(endpoint, 'GET')
            if result['success']:
                # Try to parse the response
                data = result.get('data', '')
                # R22F may return HTML or non-JSON
                # Return success but empty list if can't parse
                return {
                    'success': True,
                    'bouquets': [],
                    'raw_response': data[:200] if isinstance(data, str) else str(data)[:200]
                }
        
        return {
            'success': False,
            'error': 'Could not fetch bouquets from panel',
            'bouquets': []
        }
    
    def get_packages(self) -> Dict[str, Any]:
        """Get all available reseller packages from XtreamUI panel"""
        endpoints_to_try = [
            '/api.php?action=get_packages',
            '/panel_api.php?action=get_packages',
            '/api.php?action=packages',
        ]
        
        for endpoint in endpoints_to_try:
            result = self._make_request(endpoint, 'GET')
            if result['success']:
                data = result.get('data', '')
                return {
                    'success': True,
                    'packages': [],
                    'raw_response': data[:200] if isinstance(data, str) else str(data)[:200]
                }
        
        return {
            'success': False,
            'error': 'Could not fetch packages from panel',
            'packages': []
        }

# Singleton instance
def get_xtream_service(settings: Optional[Dict] = None) -> Optional[XtreamUIService]:
    """Get XtreamUI service instance — creates a NEW instance per call to avoid session mixing between panels"""
    if not settings or not settings.get('panel_url'):
        return None
    
    return XtreamUIService(
        panel_url=settings.get('panel_url', ''),
        admin_username=settings.get('admin_username', ''),
        admin_password=settings.get('admin_password', ''),
        ssl_verify=settings.get('ssl_verify', False),
        http_basic_user=settings.get('http_basic_user', ''),
        http_basic_pass=settings.get('http_basic_pass', ''),
        proxy_url=settings.get('proxy_url', ''),
        api_key=settings.get('api_key', '')
    )
