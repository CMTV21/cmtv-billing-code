"""
XuiOne Panel Integration Service
Similar to XtreamUI but with API key authentication
"""
import logging
import requests
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

class XuiOneService:
    """XuiOne Panel API Service"""
    
    def __init__(self, panel_url: str, api_access_code: str = "", api_key: str = "", 
                 admin_username: str = "", admin_password: str = "", ssl_verify: bool = False):
        self.panel_url = self._clean_url(panel_url)
        self.api_access_code = api_access_code  # API access code (e.g., UfPJlfai)
        self.api_key = api_key
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.ssl_verify = ssl_verify
        self.session = requests.Session()
        self.session.verify = ssl_verify
        self.logged_in = False
        
        # Set up HTTP auth if credentials in URL
        parsed = urlparse(panel_url)
        if parsed.username and parsed.password:
            self.http_auth = (parsed.username, parsed.password)
        elif admin_username and admin_password:
            self.http_auth = (admin_username, admin_password)
        else:
            self.http_auth = None
    
    def get_api_url(self) -> str:
        """Get the API base URL using the API access code"""
        if self.api_access_code:
            # Extract base domain from panel_url and use API access code
            # E.g., http://pressmonkey.net/Resellers12 -> http://pressmonkey.net/UfPJlfai/index.php
            parsed = urlparse(self.panel_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            return f"{base_url}/{self.api_access_code}/index.php"
        return f"{self.panel_url}/index.php"
    
    def _clean_url(self, url: str) -> str:
        """Remove credentials from URL"""
        parsed = urlparse(url)
        if parsed.username:
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse((parsed.scheme, netloc, parsed.path, '', '', ''))
        return url.rstrip('/')
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with API key if available"""
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
            headers['X-API-Key'] = self.api_key
        return headers
    
    def login(self) -> bool:
        """Attempt to login to XuiOne panel"""
        try:
            logger.info(f"Attempting XuiOne login to: {self.panel_url}")
            
            # XuiOne login form includes: username, password, referrer (hidden), and login (submit button)
            # Must match the exact form structure
            login_attempts = [
                # Attempt 1: Full form with all fields (including submit button name)
                {
                    'username': self.admin_username, 
                    'password': self.admin_password,
                    'referrer': '',
                    'login': 'Login'
                },
                # Attempt 2: Without submit button
                {
                    'username': self.admin_username, 
                    'password': self.admin_password,
                    'referrer': ''
                },
                # Attempt 3: Just username/password
                {
                    'username': self.admin_username, 
                    'password': self.admin_password
                },
            ]
            
            for attempt_num, login_data in enumerate(login_attempts, 1):
                logger.info(f"Login attempt {attempt_num} with fields: {list(login_data.keys())}")
                
                # POST to /login (the form action is "./login" which means POST to the login page itself)
                # The form is at /login, so we POST to /login (not /login/login)
                try_http_auth = attempt_num <= 2  # First 2 attempts with HTTP auth, last without
                
                # Construct the login URL - use just /login endpoint
                login_url = f"{self.panel_url}/login"
                # Remove duplicate /login if panel_url already ends with /login
                if self.panel_url.endswith('/login'):
                    login_url = self.panel_url
                
                logger.info(f"Posting to: {login_url}")
                
                response = self.session.post(
                    login_url,
                    data=login_data,
                    auth=self.http_auth if try_http_auth else None,
                    timeout=15,
                    allow_redirects=True  # Follow redirects to see where we end up
                )
                
                logger.info(f"XuiOne login response: status={response.status_code}, final_url={response.url}, auth={try_http_auth}")
                
                # Check if we got a PHPSESSID cookie
                has_session = 'PHPSESSID' in self.session.cookies
                logger.info(f"Has PHPSESSID cookie: {has_session}")
                
                # Check response content for success indicators
                response_text = response.text.lower()
                is_login_page = 'login' in response.url.lower() or 'data-id="login"' in response.text
                is_dashboard = 'dashboard' in response.url.lower() or 'welcome' in response_text or 'logout' in response_text
                
                logger.info(f"Response indicators: is_login_page={is_login_page}, is_dashboard={is_dashboard}")
                
                if is_dashboard and not is_login_page:
                    self.logged_in = True
                    logger.info(f"✓ XuiOne session login successful (attempt {attempt_num})")
                    return True
                
                # If we got redirected to dashboard (302 or final URL contains dashboard)
                if response.status_code in [200, 302] and has_session:
                    # Verify by trying to access dashboard
                    try:
                        dash_test = self.session.get(
                            f"{self.panel_url}/dashboard",
                            timeout=10,
                            allow_redirects=False
                        )
                        logger.info(f"Dashboard test: status={dash_test.status_code}")
                        
                        # If we can access dashboard without redirect to login, we're logged in
                        if dash_test.status_code == 200:
                            dash_content = dash_test.text.lower()
                            if 'data-id="login"' not in dash_test.text and 'logout' in dash_content:
                                self.logged_in = True
                                logger.info(f"✓ XuiOne login verified via dashboard (attempt {attempt_num})")
                                return True
                    except Exception as dash_err:
                        logger.warning(f"Dashboard verification failed: {dash_err}")
            
            logger.error(f"✗ XuiOne login failed after {len(login_attempts)} attempts")
            logger.error(f"Final response preview: {response.text[:300]}")
            return False
            
        except Exception as e:
            logger.error(f"✗ XuiOne login exception: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to XuiOne panel"""
        try:
            logger.info(f"Testing XuiOne connection to: {self.panel_url}")
            logger.info(f"Username: {self.admin_username}")
            logger.info(f"Has API key: {bool(self.api_key)}")
            logger.info(f"Has HTTP auth: {bool(self.http_auth)}")
            
            if self.login():
                # Verify we can access dashboard
                try:
                    dashboard_response = self.session.get(
                        f"{self.panel_url}/dashboard",
                        timeout=10,
                        allow_redirects=True
                    )
                    logger.info(f"Dashboard test: status={dashboard_response.status_code}")
                    
                    if dashboard_response.status_code == 200:
                        return {
                            "success": True, 
                            "message": "✓ Connection successful! Logged in and verified dashboard access."
                        }
                except Exception as dash_err:
                    logger.warning(f"Dashboard verification failed but login succeeded: {dash_err}")
                    return {
                        "success": True,
                        "message": "✓ Connection successful! (Dashboard verification skipped)"
                    }
                
                return {"success": True, "message": "✓ Connection successful!"}
            
            return {
                "success": False, 
                "error": "Login failed. Please check your username and password. See backend logs for details."
            }
        except requests.exceptions.ConnectionError as e:
            return {
                "success": False, 
                "error": f"Cannot connect to panel. Please check the URL: {self.panel_url}"
            }
        except requests.exceptions.Timeout as e:
            return {
                "success": False, 
                "error": f"Connection timeout. Panel may be slow or unreachable: {self.panel_url}"
            }
        except Exception as e:
            logger.error(f"Test connection exception: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False, 
                "error": f"Connection test failed: {str(e)}"
            }
    
    def get_packages(self) -> Dict[str, Any]:
        """Get packages from XuiOne panel by scraping HTML"""
        try:
            logger.info("XuiOne: Fetching packages via HTML scraping...")
            
            if not self.logged_in:
                logger.info("XuiOne: Not logged in, attempting login...")
                if not self.login():
                    logger.error("XuiOne: Login failed")
                    return {"success": False, "error": "Login failed", "packages": []}
            
            all_packages = []
            
            # Fetch regular packages from /line
            logger.info(f"Scraping regular packages: {self.panel_url}/line")
            regular_packages = self._scrape_packages_from_page(f"{self.panel_url}/line", is_trial=False)
            all_packages.extend(regular_packages)
            
            # Fetch trial packages from /line?trial=1
            logger.info(f"Scraping trial packages: {self.panel_url}/line?trial=1")
            trial_packages = self._scrape_packages_from_page(f"{self.panel_url}/line?trial=1", is_trial=True)
            all_packages.extend(trial_packages)
            
            logger.info(f"✓ XuiOne: Scraped {len(regular_packages)} regular + {len(trial_packages)} trial = {len(all_packages)} total packages")
            return {"success": True, "packages": all_packages}
            
        except Exception as e:
            logger.error(f"XuiOne: Exception fetching packages: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e), "packages": []}
    
    def _scrape_packages_from_page(self, url: str, is_trial: bool = False) -> list:
        """Helper method to scrape packages from a specific page"""
        try:
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                return []
            
            # Parse HTML to extract package options - ONLY from the package select dropdown
            import re
            
            # Find the <select name="package" ...> section specifically
            # This avoids picking up reseller dropdowns or other selects
            package_select_pattern = r'<select[^>]*name="package"[^>]*>(.*?)</select>'
            select_match = re.search(package_select_pattern, response.text, re.DOTALL | re.IGNORECASE)
            
            if not select_match:
                logger.warning(f"Could not find package select dropdown in {url}")
                return []
            
            package_select_html = select_match.group(1)
            
            # Now extract options from ONLY this select
            pattern = r'<option value="(\d+)">([^<]+)</option>'
            matches = re.findall(pattern, package_select_html)
            
            packages = []
            for package_id, package_name in matches:
                # Skip empty or placeholder options
                name_stripped = package_name.strip()
                if not name_stripped or name_stripped.lower().startswith('select') or name_stripped.startswith('--'):
                    continue
                
                # Parse package details from name
                name_lower = package_name.lower()
                
                # Extract duration
                duration = 1
                duration_unit = 'months'
                if 'year' in name_lower or '12 months' in name_lower:
                    duration = 12
                    duration_unit = 'months'
                elif '6 months' in name_lower:
                    duration = 6
                    duration_unit = 'months'
                elif '3 months' in name_lower:
                    duration = 3
                    duration_unit = 'months'
                elif '1 month' in name_lower:
                    duration = 1
                    duration_unit = 'months'
                
                # Extract max_connections
                max_connections = 1
                conn_match = re.search(r'(\d+)\s*connections?', name_lower)
                if conn_match:
                    max_connections = int(conn_match.group(1))
                
                packages.append({
                    'id': int(package_id),
                    'name': name_stripped,
                    'duration': duration,
                    'duration_unit': duration_unit,
                    'max_connections': max_connections,
                    'bouquets': [],  # Will be populated when package is selected
                    'credits': 0,  # Unknown from HTML
                    'is_trial': is_trial  # Set based on which page we scraped from
                })
            
            logger.info(f"Scraped {len(packages)} packages from {url} ({'trial' if is_trial else 'regular'})")
            return packages
            
        except Exception as e:
            logger.error(f"Error scraping packages from {url}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _parse_bouquets(self, bouquets_str):
        """Parse bouquets from string format "[1,2,3]" to list of integers"""
        try:
            if isinstance(bouquets_str, str):
                import json
                return json.loads(bouquets_str)
            return bouquets_str if isinstance(bouquets_str, list) else []
        except Exception:
            return []
    
    def get_bouquets(self) -> Dict[str, Any]:
        """Get bouquets from XuiOne panel using API"""
        try:
            logger.info("XuiOne: Fetching bouquets...")
            
            if not self.logged_in:
                if not self.login():
                    return {"success": False, "error": "Login failed", "bouquets": []}
            
            # First get packages to find a valid package_id
            packages_result = self.get_packages()
            package_ids = []
            if packages_result.get("success"):
                for pkg in packages_result.get("packages", []):
                    pid = pkg.get("id") or pkg.get("package_id")
                    if pid:
                        package_ids.append(str(pid))
            
            if not package_ids:
                # Fallback: try common IDs
                package_ids = ["1", "2", "31"]
            
            # Try each package_id until we get bouquets
            for pkg_id in package_ids[:5]:
                logger.info(f"Trying /api?action=get_package&package_id={pkg_id}")
                response = self.session.get(
                    f"{self.panel_url}/api",
                    params={'action': 'get_package', 'package_id': pkg_id},
                    timeout=30
                )
                
                if response.status_code == 200 and response.text.strip():
                    try:
                        data = response.json()
                        if data.get('result') and data.get('bouquets'):
                            bouquets = []
                            for bouquet in data['bouquets']:
                                bouquets.append({
                                    'id': int(bouquet.get('id')),
                                    'name': bouquet.get('bouquet_name', f"Bouquet {bouquet.get('id')}")
                                })
                            logger.info(f"XuiOne: Found {len(bouquets)} bouquets via package {pkg_id}")
                            return {"success": True, "bouquets": bouquets}
                    except Exception:
                        continue
            
            logger.warning("XuiOne: No bouquets found from any package API")
            
            # Fallback: scrape bouquets from a line edit page (/line?id=X)
            try:
                import re as _re, json as _json
                logger.info("XuiOne: Trying to scrape bouquets from line edit page...")
                
                # Find the reseller's own ID for filtering
                reseller_id = ""
                line_page = self.session.get(f"{self.panel_url}/line", timeout=30)
                if line_page.status_code == 200:
                    member_sel = _re.search(r'name=["\']member_id["\'][^>]*>(.*?)</select>', line_page.text, _re.DOTALL)
                    if member_sel:
                        for uid, uname in _re.findall(r'value=["\'](\d+)["\'][^>]*>([^<]+)', member_sel.group(1)):
                            if uname.strip() == self.admin_username:
                                reseller_id = uid
                                break
                
                # Get a line ID via DataTable
                line_id = None
                params = "draw=1&start=0&length=1&id=lines"
                if reseller_id:
                    params += f"&reseller={reseller_id}"
                resp = self.session.post(
                    f"{self.panel_url}/table",
                    data=params,
                    headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                             "X-Requested-With": "XMLHttpRequest",
                             "Referer": f"{self.panel_url}/lines"},
                    timeout=15
                )
                if resp.status_code == 200 and resp.text.strip().startswith("{"):
                    data = _json.loads(resp.text)
                    if data.get("data"):
                        line_id = _re.sub(r'<[^>]+>', '', str(data["data"][0][0])).strip()
                
                if line_id:
                    resp2 = self.session.get(f"{self.panel_url}/line?id={line_id}", timeout=15)
                    if resp2.status_code == 200:
                        # Parse inline bouquet data from the else block:
                        # rTable.row.add(["<input...value='1003' checked></input>", 'Movies', 0, 33706, 0, 0]);
                        bouquet_rows = _re.findall(
                            r"rTable\.row\.add\(\[\"<input[^\"]*value='(\d+)'[^\"]*>\",\s*'([^']*)',\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\)",
                            resp2.text
                        )
                        if bouquet_rows:
                            bouquets = [{"id": int(bid), "name": bname} for bid, bname, _, _, _, _ in bouquet_rows]
                            logger.info(f"XuiOne: Scraped {len(bouquets)} bouquets from line edit page")
                            return {"success": True, "bouquets": bouquets}
                        
                        # Looser fallback regex
                        bouquet_rows2 = _re.findall(r"value='(\d+)'[^)]*>\",\s*'([^']+)'", resp2.text)
                        if bouquet_rows2:
                            bouquets = [{"id": int(bid), "name": bname} for bid, bname in bouquet_rows2]
                            logger.info(f"XuiOne: Scraped {len(bouquets)} bouquets (loose regex)")
                            return {"success": True, "bouquets": bouquets}
                    
                    logger.warning("XuiOne: Line edit page loaded but no bouquet data found")
                else:
                    logger.warning("XuiOne: Could not find any line ID for bouquet scraping")
                    
            except Exception as scrape_err:
                logger.warning(f"XuiOne: Bouquet scrape failed: {scrape_err}")
                import traceback
                logger.warning(traceback.format_exc())
            
            return {"success": False, "error": "This panel's API doesn't support bouquet fetching. Bouquets are managed by the panel admin — you can add them manually.", "bouquets": []}
            
        except Exception as e:
            logger.error(f"Error fetching bouquets: {str(e)}")
            return {"success": False, "error": str(e), "bouquets": []}
    
    def get_users(self) -> Dict[str, Any]:
        """Get users/lines from XuiOne panel using API"""
        try:
            logger.info("XuiOne: Fetching users...")
            
            if not self.logged_in:
                if not self.login():
                    return {"success": False, "error": "Login failed", "users": []}
            
            # Try /api?action=get_lines with session (most reliable)
            for action in ["get_lines", "get_users"]:
                try:
                    response = self.session.get(
                        f"{self.panel_url}/api",
                        params={'action': action, 'api_key': self.api_key} if self.api_key else {'action': action},
                        timeout=30
                    )
                    
                    if response.status_code == 200 and response.text.strip().startswith("{"):
                        result = response.json()
                        if result.get('result') or result.get('status') == 'STATUS_SUCCESS':
                            lines_data = result.get('data', [])
                            if isinstance(lines_data, dict):
                                lines_data = list(lines_data.values())
                            
                            users = []
                            for line in lines_data:
                                expiry_timestamp = line.get('exp_date')
                                expiry_str = ""
                                if expiry_timestamp:
                                    from datetime import datetime
                                    try:
                                        expiry_dt = datetime.fromtimestamp(int(expiry_timestamp))
                                        expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")
                                    except Exception:
                                        expiry_str = str(expiry_timestamp)
                                
                                users.append({
                                    "user_id": line.get('id'),
                                    "username": line.get('username', ''),
                                    "password": line.get('password', ''),
                                    "expiry": expiry_str,
                                    "max_connections": str(line.get('max_connections', 1)),
                                    "status": "active" if str(line.get('enabled', '1')) == '1' else "disabled",
                                })
                            
                            if users:
                                logger.info(f"XuiOne: Found {len(users)} users via /api?{action}")
                                return {"success": True, "users": users, "count": len(users)}
                except Exception as e:
                    logger.warning(f"XuiOne /api?{action} failed: {e}")
            
            # Fallback: try API access code URL if configured
            if self.api_key:
                api_url = self.get_api_url()
                try:
                    response = self.session.get(
                        api_url,
                        params={'api_key': self.api_key, 'action': 'get_lines'},
                        timeout=30
                    )
                    if response.status_code == 200 and response.text.strip().startswith("{"):
                        result = response.json()
                        if result.get('result') or result.get('status') == 'STATUS_SUCCESS':
                            lines_data = result.get('data', [])
                            users = []
                            for line in lines_data:
                                expiry_timestamp = line.get('exp_date')
                                expiry_str = ""
                                if expiry_timestamp:
                                    from datetime import datetime
                                    try:
                                        expiry_dt = datetime.fromtimestamp(int(expiry_timestamp))
                                        expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")
                                    except Exception:
                                        expiry_str = str(expiry_timestamp)
                                users.append({
                                    "user_id": line.get('id'),
                                    "username": line.get('username', ''),
                                    "password": line.get('password', ''),
                                    "expiry": expiry_str,
                                    "max_connections": str(line.get('max_connections', 1)),
                                    "status": "active" if str(line.get('enabled', '1')) == '1' else "disabled",
                                })
                            if users:
                                logger.info(f"XuiOne: Found {len(users)} users via API access code")
                                return {"success": True, "users": users, "count": len(users)}
                except Exception:
                    pass
            
            logger.warning("XuiOne: Could not fetch users from any endpoint")
            
            # Final fallback: scrape via XuiOne DataTable endpoint
            try:
                import re as _re
                logger.info("XuiOne: Trying DataTable scrape from /table endpoint...")
                
                # Find the reseller's own ID from the member_id dropdown
                reseller_id = ""
                line_page = self.session.get(f"{self.panel_url}/line", timeout=30)
                if line_page.status_code == 200:
                    member_sel = _re.search(r'name=["\'\']member_id["\'\'][^>]*>(.*?)</select>', line_page.text, _re.DOTALL)
                    if member_sel:
                        for uid, uname in _re.findall(r'value=["\'\'](\d+)["\'\'][^>]*>([^<]+)', member_sel.group(1)):
                            if uname.strip() == self.admin_username:
                                reseller_id = uid
                                break
                
                logger.info(f"XuiOne: Reseller ID: {reseller_id or 'not found'}")
                
                all_users = []
                start = 0
                page_size = 500
                
                while True:
                    params = f"draw=1&start={start}&length={page_size}&id=lines&search%5Bvalue%5D=&order%5B0%5D%5Bcolumn%5D=0&order%5B0%5D%5Bdir%5D=asc"
                    if reseller_id:
                        params += f"&reseller={reseller_id}"
                    
                    resp = self.session.post(
                        f"{self.panel_url}/table",
                        data=params,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                            "X-Requested-With": "XMLHttpRequest",
                            "Referer": f"{self.panel_url}/lines"
                        },
                        timeout=30
                    )
                    
                    if resp.status_code != 200 or not resp.text.strip().startswith("{"):
                        break
                    
                    import json as _json
                    data = _json.loads(resp.text)
                    total = int(data.get("recordsTotal", 0))
                    rows = data.get("data", [])
                    
                    if not rows:
                        break
                    
                    for row in rows:
                        uid = _re.sub(r'<[^>]+>', '', str(row[0])).strip() if len(row) > 0 else ""
                        username = _re.sub(r'<[^>]+>', '', str(row[1])).strip() if len(row) > 1 else ""
                        password = _re.sub(r'<[^>]+>', '', str(row[2])).strip() if len(row) > 2 else ""
                        
                        status = "active"
                        if len(row) > 4 and ("text-danger" in str(row[4]) or "text-warning" in str(row[4])):
                            status = "disabled"
                        
                        connections = _re.sub(r'<[^>]+>', '', str(row[8])).strip() if len(row) > 8 else "1"
                        
                        # Parse expiry: HTML like "2026-08-10<br/><small>11:24:16</small>" or with <span class="expired">
                        expiry = ""
                        if len(row) > 9:
                            raw_exp = str(row[9])
                            # Strip HTML tags but replace <br/> with space
                            exp_clean = _re.sub(r'<br\s*/?>', ' ', raw_exp)
                            exp_clean = _re.sub(r'<[^>]+>', '', exp_clean).strip()
                            # Fix missing space: "2025-09-0812:10:37" -> "2025-09-08 12:10:37"
                            exp_match = _re.match(r'(\d{4}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2})', exp_clean)
                            if exp_match:
                                expiry = f"{exp_match.group(1)} {exp_match.group(2)}"
                            elif exp_clean:
                                expiry = exp_clean
                        
                        # Check expired status from expiry column HTML
                        if len(row) > 9 and "expired" in str(row[9]).lower():
                            status = "expired"
                        
                        if username:
                            all_users.append({
                                "user_id": uid,
                                "username": username,
                                "password": password,
                                "expiry": expiry,
                                "max_connections": connections or "1",
                                "status": status,
                            })
                    
                    start += page_size
                    if start >= total:
                        break
                
                if all_users:
                    logger.info(f"XuiOne: Scraped {len(all_users)} subscriber lines via DataTable")
                    return {"success": True, "users": all_users, "count": len(all_users)}
                    
            except Exception as scrape_err:
                logger.warning(f"XuiOne: DataTable scrape failed: {scrape_err}")
            
            return {"success": False, "error": "Could not fetch users from any endpoint", "users": []}
            
        except Exception as e:
            logger.error(f"Error fetching users: {str(e)}")
            return {"success": False, "error": str(e), "users": []}
    
    def get_subresellers(self) -> Dict[str, Any]:
        """Get subresellers from XuiOne panel using API"""
        try:
            logger.info("XuiOne: Fetching subresellers...")
            
            if not self.logged_in:
                if not self.login():
                    return {"success": False, "error": "Login failed", "users": []}
            
            # Use get_users API action and filter for resellers
            if self.api_key:
                api_url = self.get_api_url()
                
                try:
                    import requests
                    response = self.session.get(
                        api_url,
                        params={
                            'api_key': self.api_key,
                            'action': 'get_users'  # Gets all users
                        },
                        timeout=30
                    )
                    
                    logger.info(f"XuiOne get_users response: status={response.status_code}")
                    
                    if response.status_code == 200:
                        result = response.json()
                        
                        if result.get('status') == 'STATUS_SUCCESS' or result.get('result'):
                            users_data = result.get('data', [])
                            logger.info(f"XuiOne: Fetched {len(users_data)} total users, filtering for resellers...")
                            
                            # Filter for resellers - check multiple possible field names
                            subresellers = []
                            for user in users_data:
                                is_reseller = False
                                
                                # Check various fields that indicate reseller role
                                if user.get('role') == 'reseller':
                                    is_reseller = True
                                elif user.get('user_type') in ['reseller', 2, '2']:
                                    is_reseller = True
                                elif user.get('is_reseller') in [1, '1', True]:
                                    is_reseller = True
                                elif int(user.get('member_group_id', 0)) >= 2:
                                    # Fallback: member_group_id >= 2 usually indicates reseller
                                    is_reseller = True
                                
                                if is_reseller:
                                    # Check if owned by current reseller (filter out others)
                                    owner_id = str(user.get('owner_id', ''))
                                    
                                    subresellers.append({
                                        "user_id": user.get('id'),
                                        "username": user.get('username', ''),
                                        "owner": owner_id,
                                        "member_group": str(user.get('member_group_id', '')),
                                        "credits": str(user.get('credits', 0)),
                                        "expiry": "NEVER",  # Resellers don't expire
                                        "status": "active" if user.get('status') in ['1', 1, True] else "disabled",
                                    })
                            
                            logger.info(f"✓ XuiOne: Found {len(subresellers)} resellers (out of {len(users_data)} total users)")
                            return {"success": True, "users": subresellers, "count": len(subresellers)}
                except Exception as api_err:
                    logger.error(f"XuiOne get_users API error: {api_err}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            return {"success": False, "error": "API not available or failed", "users": []}
            
        except Exception as e:
            logger.error(f"Error fetching subresellers: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e), "users": []}

    def extend_line(self, username: str, package_id: int) -> Dict[str, Any]:
        """Extend a line's subscription using the edit_line API"""
        try:
            if not self.api_key:
                return {"success": False, "error": "API key required for extension"}
            
            # Login first
            if not self.logged_in:
                if not self.login():
                    return {"success": False, "error": "Failed to login to panel"}
            
            logger.info(f"XuiOne: Extending line {username} with package {package_id}")
            
            # First, we need to get the line ID by looking up the username
            line_id = self._get_line_id_by_username(username)
            
            if not line_id:
                return {"success": False, "error": f"Could not find line ID for username '{username}'. User may not exist on panel."}
            
            logger.info(f"XuiOne: Found line ID {line_id} for username {username}")
            
            request_data = {
                'id': str(line_id),
                'edit': str(line_id),
                'package': str(package_id),
                'trial': '0',
                'reseller_notes': 'Extended via Billing Panel',
                'is_isplock': '0'
            }
            
            logger.info(f"XuiOne: Extending line with data: {request_data}")
            
            # Primary: use post.php?action=line with session (same as web UI)
            response = self.session.post(
                f"{self.panel_url}/post.php?action=line",
                data=request_data,
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=30
            )
            
            if response.status_code != 200 or not response.text.strip():
                # Fallback: try API access code endpoint
                if self.api_key:
                    api_url = self.get_api_url()
                    response = self.session.post(
                        api_url,
                        params={'api_key': self.api_key, 'action': 'edit_line'},
                        data=request_data,
                        timeout=30
                    )
            
            logger.info(f"XuiOne edit_line response: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"XuiOne edit_line result: {result}")
                    
                    if result.get('result') == True or result.get('status') == 'STATUS_SUCCESS':
                        logger.info(f"✓ XuiOne line extended successfully")
                        return {"success": True, "result": result}
                    else:
                        error_msg = result.get('message', result.get('error', str(result.get('status', 'Unknown error'))))
                        logger.error(f"XuiOne edit_line failed: {error_msg}")
                        return {"success": False, "error": error_msg}
                except ValueError:
                    logger.error("XuiOne: Invalid JSON response from edit_line")
                    return {"success": False, "error": "Invalid API response"}
            else:
                logger.error(f"XuiOne edit_line HTTP error: {response.status_code}")
                return {"success": False, "error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            logger.error(f"XuiOne extend_line error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}
    
    def _get_line_id_by_username(self, username: str) -> Optional[str]:
        """Look up a line's ID by its username"""
        try:
            # Primary: search via DataTable endpoint
            import re as _re, json as _json
            try:
                resp = self.session.post(
                    f"{self.panel_url}/table",
                    data=f"draw=1&start=0&length=5&id=lines&search%5Bvalue%5D={username}&order%5B0%5D%5Bcolumn%5D=0&order%5B0%5D%5Bdir%5D=asc",
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": f"{self.panel_url}/lines"
                    },
                    timeout=15
                )
                if resp.status_code == 200 and resp.text.strip().startswith("{"):
                    data = _json.loads(resp.text)
                    for row in data.get("data", []):
                        row_user = _re.sub(r'<[^>]+>', '', str(row[1])).strip()
                        if row_user == username:
                            row_id = _re.sub(r'<[^>]+>', '', str(row[0])).strip()
                            if row_id:
                                return row_id
            except Exception:
                pass
            
            # Fallback: try API access code endpoint
            if self.api_key:
                api_url = self.get_api_url()
                try:
                    response = self.session.get(
                        api_url,
                        params={'api_key': self.api_key, 'action': 'get_line', 'username': username},
                        timeout=30
                    )
                    if response.status_code == 200:
                        result = response.json()
                        if result.get('status') == 'STATUS_SUCCESS':
                            line_id = result.get('data', {}).get('id')
                            if line_id:
                                return str(line_id)
                except Exception:
                    pass
            
            # Last resort: get all users
            users_result = self.get_users()
            if users_result.get('success'):
                for user in users_result.get('users', []):
                    if user.get('username') == username:
                        user_id = user.get('user_id') or user.get('id')
                        if user_id:
                            return str(user_id)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting line ID for {username}: {e}")
            return None


# Singleton instance management
_xuione_service = None

def get_xuione_service(panel_config: Dict[str, Any]) -> Optional[XuiOneService]:
    """Get or create XuiOne service instance"""
    global _xuione_service
    
    if not panel_config:
        return None
    
    panel_url = panel_config.get('panel_url', '')
    if not panel_url:
        return None
    
    _xuione_service = XuiOneService(
        panel_url=panel_url,
        api_access_code=panel_config.get('api_access_code', ''),
        api_key=panel_config.get('api_key', ''),
        admin_username=panel_config.get('admin_username', ''),
        admin_password=panel_config.get('admin_password', ''),
        ssl_verify=panel_config.get('ssl_verify', False)
    )
    
    return _xuione_service
