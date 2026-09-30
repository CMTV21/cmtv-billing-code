import requests
import json
import logging
import os
import tempfile
from http.cookiejar import MozillaCookieJar
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class XtreamUISessionClient:
    """XtreamUI R22F Client with Cookie File Persistence (WHMCS Method)"""
    
    def __init__(self, panel_url: str, username: str, password: str, ssl_verify: bool = False,
                 http_basic_user: str = None, http_basic_pass: str = None, proxy_url: str = None):
        from urllib.parse import urlparse, urlunparse
        
        # Parse URL to extract any embedded credentials and clean hostname
        parsed = urlparse(panel_url)
        
        # Store credentials - either from URL or from parameters
        self.username = parsed.username or username
        self.password = parsed.password or password
        
        # Build clean URL without embedded credentials
        hostname = parsed.hostname or parsed.netloc.split('@')[-1].split(':')[0]
        port = parsed.port
        
        if port:
            netloc = f"{hostname}:{port}"
        else:
            netloc = hostname
        
        clean_url = urlunparse((
            parsed.scheme or 'https',
            netloc,
            parsed.path or '',
            '', '', ''
        ))
        
        # Use ONLY clean URL - auth will be passed via requests auth parameter
        self.panel_url = clean_url.rstrip('/')
        self.ssl_verify = ssl_verify
        
        # HTTP Basic Auth - use separate basic auth creds if provided, otherwise use panel creds
        if http_basic_user and http_basic_pass:
            self.http_auth = (http_basic_user, http_basic_pass)
        else:
            self.http_auth = (self.username, self.password)
        
        logger.info(f"Panel URL (clean): {self.panel_url}")
        logger.info(f"HTTP Basic Auth user: {self.http_auth[0]}")
        if proxy_url:
            logger.info(f"Using proxy: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")
        
        # Create cookie file — include username to prevent session mixing between different admins on the same panel
        cookie_dir = os.path.join(tempfile.gettempdir(), 'xtreamui_sessions')
        os.makedirs(cookie_dir, exist_ok=True)
        
        safe_panel_name = self.panel_url.replace('://', '_').replace('/', '_').replace(':', '_')
        safe_username = self.username.replace(' ', '_').replace('/', '_')
        self.cookie_file = os.path.join(cookie_dir, f'{safe_panel_name}_{safe_username}_cookies.txt')
        
        # Create session with cookie jar
        self.session = requests.Session()
        self.session.verify = ssl_verify
        self.session.cookies = MozillaCookieJar(self.cookie_file)
        
        # Set proxy if provided
        if proxy_url:
            self.session.proxies = {'http': proxy_url, 'https': proxy_url}
        
        # Load existing cookies
        if os.path.exists(self.cookie_file):
            try:
                self.session.cookies.load(ignore_discard=True, ignore_expires=True)
                logger.info(f"Loaded existing session from {self.cookie_file}")
            except Exception:
                pass
        
        self.logged_in = False
    
    def login(self) -> bool:
        """Login to XtreamUI panel - EXACT PHP method: POST credentials as form data"""
        try:
            login_url = f"{self.panel_url}/login.php"
            
            # PHP sends credentials as form data
            login_data = {
                'username': self.username,
                'password': self.password
            }
            
            logger.info(f"Logging in with form POST to: {login_url}")
            logger.info(f"POST data: username={self.username}")
            
            # Use auth parameter for HTTP Basic Auth (Nginx) - keeps cookies clean!
            response = self.session.post(login_url, data=login_data, auth=self.http_auth, 
                                         timeout=30, allow_redirects=True)
            
            # Check if login succeeded
            if response.status_code == 200:
                # Debug: Log all cookies
                cookie_names = [cookie.name for cookie in self.session.cookies]
                logger.info(f"Cookies after login: {cookie_names}")
                logger.info(f"Cookie jar type: {type(self.session.cookies).__name__}")
                
                # Check if we have session cookies
                if 'PHPSESSID' in cookie_names or 'hash' in cookie_names:
                    self.logged_in = True
                    
                    # Save cookies to file (WHMCS method!)
                    try:
                        self.session.cookies.save(ignore_discard=True, ignore_expires=True)
                        logger.info(f"✓ Session saved to cookie file: {self.cookie_file}")
                    except Exception as e:
                        logger.warning(f"Failed to save cookies: {str(e)}")
                    
                    logger.info("✓ XtreamUI login successful - session established")
                    return True
                elif 'dashboard' in response.url.lower():
                    self.logged_in = True
                    
                    # Save cookies
                    try:
                        self.session.cookies.save(ignore_discard=True, ignore_expires=True)
                        logger.info(f"✓ Session saved to cookie file")
                    except Exception:
                        pass
                    
                    logger.info("✓ XtreamUI login successful - redirected to dashboard")
                    return True
                else:
                    logger.warning("Login returned 200 but no session cookie found")
                    logger.warning(f"Response URL: {response.url}")
                    logger.warning(f"Response preview: {response.text[:200]}")
                    return False
            else:
                logger.error(f"Login failed: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False
    

    
    def get_reseller_info(self) -> Dict[str, Any]:
        """Get logged-in reseller's info (ID and permissions)"""
        if not self.logged_in:
            if not self.login():
                return {}
        
        try:
            import re
            
            # Method 1: Check users.php page for the reseller dropdown
            # The dropdown shows all resellers including the logged-in one
            # Our username will be in the list with its member_id
            users_response = self.session.get(f"{self.panel_url}/users.php", auth=self.http_auth, timeout=15)
            if users_response.status_code == 200:
                html = users_response.text
                
                # Look for our username in the reseller dropdown
                # Format: <option value="1622">whmcs</option>
                pattern = rf'<option\s+value=["\']?(\d+)["\']?[^>]*>\s*{re.escape(self.username)}\s*</option>'
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    member_id = int(match.group(1))
                    logger.info(f"Detected member_id from users.php dropdown: {member_id}")
                    return {'user_id': member_id, 'member_id': member_id, 'can_create_subreseller': True}
                
                # Alternative: Look for user_reseller select with our username
                reseller_select = re.search(r'id=["\']user_reseller["\'][^>]*>(.+?)</select>', html, re.DOTALL | re.IGNORECASE)
                if reseller_select:
                    options_html = reseller_select.group(1)
                    option_pattern = rf'value=["\']?(\d+)["\']?[^>]*>\s*{re.escape(self.username)}\s*<'
                    opt_match = re.search(option_pattern, options_html, re.IGNORECASE)
                    if opt_match:
                        member_id = int(opt_match.group(1))
                        logger.info(f"Detected member_id from reseller select: {member_id}")
                        return {'user_id': member_id, 'member_id': member_id, 'can_create_subreseller': True}
            
            # Method 2: Try dashboard page
            response = self.session.get(f"{self.panel_url}/dashboard.php", auth=self.http_auth, timeout=10)
            
            if response.status_code == 200:
                html = response.text
                
                # Look for member_id in hidden inputs or data attributes
                member_match = re.search(r'member_id["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE)
                if member_match:
                    member_id = int(member_match.group(1))
                    logger.info(f"Detected member_id from dashboard: {member_id}")
                    return {'user_id': member_id, 'member_id': member_id, 'can_create_subreseller': True}
                
                # Look for data-id or user id patterns
                id_patterns = [
                    r'data-member-id=["\']?(\d+)',
                    r'data-id=["\']?(\d+)',
                    r'user_id["\']?\s*[:=]\s*["\']?(\d+)',
                    r'reseller_id["\']?\s*[:=]\s*["\']?(\d+)',
                ]
                
                for pattern in id_patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        user_id = int(match.group(1))
                        if user_id > 0:
                            logger.info(f"Detected user/member ID: {user_id}")
                            return {'user_id': user_id, 'member_id': user_id, 'can_create_subreseller': True}
            
            # Fallback: return defaults
            logger.warning("Could not detect member_id from panel")
            return {'user_id': 0, 'member_id': 0, 'can_create_subreseller': False}
            
        except Exception as e:
            logger.error(f"Error getting reseller info: {str(e)}")
            return {'user_id': 0, 'member_id': 0, 'can_create_subreseller': False}
    
    def get_reseller_member_id(self) -> Optional[int]:
        """Get the reseller's member_id from the panel"""
        info = self.get_reseller_info()
        return info.get('member_id', 0) if info else 0
    
    def get_member_groups(self) -> Dict[int, str]:
        """Get available member groups from panel"""
        if not self.logged_in:
            if not self.login():
                return {}
        
        return {}  # Placeholder for now
    
    def add_credits(self, username: str, email: str, credits: float) -> Dict[str, Any]:
        """Add credits - Exact WHMCS method with search"""
        if not self.logged_in:
            if not self.login():
                return {'success': False, 'error': 'Failed to login'}
        
        try:
            import time
            
            # Build search parameters (WHMCS getSearchingArrayStreamline)
            search_params = {}
            
            # CRITICAL: PHP sets draw=1
            search_params['draw'] = '1'
            
            for i in range(12):
                search_params[f'columns[{i}][data]'] = str(i)
                search_params[f'columns[{i}][name]'] = ''
                search_params[f'columns[{i}][searchable]'] = 'true'
                search_params[f'columns[{i}][orderable]'] = 'true'
                search_params[f'columns[{i}][search][value]'] = ''
                search_params[f'columns[{i}][search][regex]'] = ''
            
            search_params['order[0][column]'] = '0'
            search_params['order[0][dir]'] = 'desc'
            search_params['start'] = '0'
            search_params['length'] = '25'
            search_params['search[value]'] = username  # Search by username
            search_params['search[regex]'] = 'false'
            search_params['id'] = 'reg_users'
            search_params['filter'] = ''
            search_params['reseller'] = ''
            search_params['_'] = str(int(time.time() * 1000))  # Milliseconds timestamp
            
            # WHMCS uses query string in URL + POST data (both!)
            # Use clean URL with auth parameter
            search_url = f"{self.panel_url}/table_search.php"
            query_string_url = f"{search_url}?{requests.compat.urlencode(search_params)}"
            
            logger.info(f"Searching for user: {username}")
            logger.info(f"Query URL: {query_string_url[:200]}...")
            
            # GET with parameters (some panels only respond to GET for table_search.php)
            response = self.session.get(search_url, params=search_params, auth=self.http_auth, timeout=15)
            
            # Fallback to POST if GET returns empty
            if response.status_code == 200 and len(response.text.strip()) == 0:
                response = self.session.post(search_url, data=search_params, auth=self.http_auth, timeout=15)
            
            logger.info(f"Search response: {response.status_code}")
            logger.info(f"Response: {response.text[:300]}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    
                    # Use getexactfromsearch logic
                    user_data = None
                    records_total = int(result.get('recordsTotal', 0)) if result.get('recordsTotal') else 0
                    
                    if records_total > 0:
                        # Find exact match by username (column 1)
                        for row in result.get('data', []):
                            if len(row) > 1 and str(row[1]).strip() == username:
                                user_data = row
                                break
                        
                        # Or use first result if only one
                        if not user_data and records_total == 1:
                            user_data = result['data'][0]
                    
                    if user_data and len(user_data) > 0:
                        user_id = user_data[0]  # Column 0 is ID
                        current_credits = user_data[6] if len(user_data) > 6 else '0'  # Column 6 is credits
                        
                        logger.info(f"Found user ID: {user_id}, current credits: {current_credits}")
                        
                        # Add credits (WHMCS exact format)
                        credits_data = {
                            'id': user_id,
                            'credits': str(int(credits)),
                            'submit_credits': 'Purchase'
                        }
                        
                        # URL has credits in query string
                        credits_url = f"{self.panel_url}/credits_add.php?id={int(credits)}"
                        
                        logger.info(f"Adding {credits} credits to user ID {user_id}")
                        logger.info(f"URL: {credits_url}")
                        logger.info(f"Data: {credits_data}")
                        
                        credits_response = self.session.post(credits_url, data=credits_data, auth=self.http_auth, timeout=10)
                        
                        logger.info(f"Credits response: {credits_response.status_code}")
                        
                        if credits_response.status_code == 200:
                            logger.info(f"✓ {credits} credits added to {username}")
                            return {'success': True, 'credits': credits}
                        else:
                            return {'success': False, 'error': f'HTTP {credits_response.status_code}'}
                    else:
                        logger.error(f"User {username} not found in search results")
                        return {'success': False, 'error': 'User not found'}
                        
                except Exception as e:
                    logger.error(f"Search parse error: {str(e)}")
                    logger.error(f"Response was: {response.text[:500]}")
                    return {'success': False, 'error': f'Search failed: {str(e)}'}
            else:
                return {'success': False, 'error': 'Search request failed'}
                
        except Exception as e:
            logger.error(f"Add credits error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_reseller_id(self) -> Optional[int]:
        """Get the ID of the logged-in reseller (for owner_id)"""

    
    def extend_subscriber(self, username: str, password: str, package_id: int, bouquets: list, max_connections: int, reseller_notes: str = "") -> Dict[str, Any]:
        """Extend existing subscriber - EXACT WHMCS PHP method"""
        if not self.logged_in:
            if not self.login():
                return {'success': False, 'error': 'Failed to login'}
        
        try:
            import time
            
            # Step 1: Search for user to get ID - EXACT PHP parameters!
            # PHP: getSearchingArrayStreamline() equivalent
            search_params = {}
            
            # CRITICAL: PHP sets draw=1 (integer, but becomes string in http_build_query)
            search_params['draw'] = '1'
            
            for i in range(12):
                search_params[f'columns[{i}][data]'] = str(i)
                search_params[f'columns[{i}][name]'] = ''
                search_params[f'columns[{i}][searchable]'] = 'true'
                search_params[f'columns[{i}][orderable]'] = 'true'
                search_params[f'columns[{i}][search][value]'] = ''
                search_params[f'columns[{i}][search][regex]'] = ''  # PHP uses empty string
            
            # PHP uses 0 for extend action, 2 for disable/enable/delete
            search_params['order[0][column]'] = '0'
            search_params['order[0][dir]'] = 'desc'
            search_params['start'] = '0'
            search_params['length'] = '25'
            search_params['search[value]'] = username
            search_params['search[regex]'] = 'false'
            search_params['id'] = 'users'  # "users" for streaming lines
            search_params['filter'] = ''
            search_params['reseller'] = ''
            search_params['_'] = str(int(time.time() * 1000))  # WSxtreamUI_milliseconds()
            
            # Use clean URL with auth parameter for search
            search_url = f"{self.panel_url}/table_search.php"
            query_string_url = f"{search_url}?{requests.compat.urlencode(search_params)}"
            
            logger.info(f"Extending subscriber: Searching for {username}")
            
            response = self.session.get(search_url, params=search_params, auth=self.http_auth, timeout=15)
            
            # Fallback to POST if GET returns empty
            if response.status_code == 200 and len(response.text.strip()) == 0:
                response = self.session.post(search_url, data=search_params, auth=self.http_auth, timeout=15)
            
            logger.info(f"Search response status: {response.status_code}")
            logger.info(f"Search response content: {response.text[:500]}")
            
            if response.status_code == 200:
                try:
                    result = response.json()
                    records_total = int(result.get('recordsTotal', 0)) if result.get('recordsTotal') else 0
                    
                    if records_total > 0:
                        # Get user ID and previous expiry date
                        user_data = result.get('data', [[]])[0]
                        user_id = user_data[0] if user_data else None
                        
                        # Get previous expiry date (column 7) - PHP: $PrevioudNextDueDate = strip_tags($ara["data"][0][7]);
                        import re
                        prev_date_str = ''
                        if len(user_data) > 7:
                            prev_date_str = re.sub('<[^<]+?>', '', str(user_data[7])).strip()
                        logger.info(f"Previous expiry date: {prev_date_str}")
                        
                        if user_id:
                            logger.info(f"Found user ID: {user_id}")
                            
                            # Step 2: POST to user_reseller.php with package bouquets
                            edit_url = f"{self.panel_url}/user_reseller.php?id={user_id}"
                            
                            logger.info(f"Edit URL: {edit_url}")
                            logger.info(f"Using package bouquets for extension: {bouquets}")
                            
                            from datetime import datetime, timedelta
                            import re
                            import json
                            
                            # Calculate new expiry
                            current_exp = prev_date_str.replace('<br>', ' ').strip()
                            try:
                                current_exp_clean = re.sub(r'(\d{4}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2})', r'\1 \2', current_exp)
                                exp_dt = datetime.strptime(current_exp_clean.strip(), "%Y-%m-%d %H:%M:%S")
                                new_exp_dt = exp_dt + timedelta(days=365)
                                new_exp_str = new_exp_dt.strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                new_exp_str = ""
                            
                            # Auto-detect member_id from logged-in reseller
                            reseller_info = self.get_reseller_info()
                            member_id = str(reseller_info.get('member_id', 0))
                            logger.info(f"Using member_id: {member_id}")
                            
                            # Use package bouquets — these determine what channels the user gets
                            edit_data = {
                                'edit': str(user_id),
                                'submit_user': '1',
                                'username': username,
                                'password': password,
                                'package': str(package_id),
                                'member_id': member_id,
                                'exp_date': new_exp_str,
                                'reseller_notes': reseller_notes or '',
                                'bouquets_selected': json.dumps(bouquets if bouquets else []),
                            }
                            
                            logger.info(f"POST data: {edit_data}")
                            
                            edit_response = self.session.post(edit_url, data=edit_data, auth=self.http_auth, timeout=30)
                            
                            logger.info(f"Extend response: {edit_response.status_code}")
                            logger.info(f"Response headers: {dict(edit_response.headers)}")
                            logger.info(f"Response content (first 500 chars): {edit_response.text[:500] if edit_response.text else 'EMPTY'}")
                            
                            # PHP method: Don't check edit response - search again to verify!
                            # Search again to verify the date changed
                            logger.info("Verifying extension by searching again...")
                            verify_response = self.session.get(search_url, params=search_params, auth=self.http_auth, timeout=15)
                            if verify_response.status_code == 200 and len(verify_response.text.strip()) == 0:
                                verify_response = self.session.post(search_url, data=search_params, auth=self.http_auth, timeout=15)
                            
                            if verify_response.status_code == 200:
                                try:
                                    verify_result = verify_response.json()
                                    if verify_result.get('data') and len(verify_result['data']) > 0:
                                        from panel_expiry import row_expiry, to_panel_string
                                        new_dt, new_unlimited, new_date_str = row_expiry(verify_result['data'][0])
                                        # Strip HTML tags
                                        import re
                                        new_date_clean = re.sub('<[^<]+?>', '', str(new_date_str)).strip()
                                        new_expiry_utc = to_panel_string(new_dt, new_unlimited) or new_date_clean
                                        logger.info(f"Previous date: {prev_date_str}, New date: {new_date_clean} (UTC: {new_expiry_utc})")
                                        
                                        # Compare dates to verify extension worked
                                        if new_date_clean != prev_date_str:
                                            logger.info(f"✓ Date changed! Subscriber {username} extended successfully")
                                            return {'success': True, 'username': username, 'new_expiry': new_expiry_utc}
                                        else:
                                            logger.warning(f"Date did not change - extension may have failed")
                                            if edit_response.status_code == 200:
                                                return {'success': True, 'username': username, 'new_expiry': new_expiry_utc}
                                except Exception as ve:
                                    logger.error(f"Verification error: {ve}")
                            
                            # Fallback — use the exp_date we sent in the POST
                            if edit_response.status_code == 200:
                                logger.info(f"✓ Subscriber {username} extended (HTTP 200)")
                                return {'success': True, 'username': username, 'new_expiry': edit_data.get('exp_date', '')}
                            else:
                                logger.error(f"Extension failed with HTTP {edit_response.status_code}")
                                return {'success': False, 'error': f'HTTP {edit_response.status_code}'}
                        else:
                            return {'success': False, 'error': 'User ID not found'}
                    else:
                        return {'success': False, 'error': f'User {username} not found'}
                except Exception as e:
                    logger.error(f"Search parse error: {str(e)}")
                    return {'success': False, 'error': str(e)}
            else:
                return {'success': False, 'error': 'Search failed'}
                
        except Exception as e:
            logger.error(f"Extend error: {str(e)}")
            return {'success': False, 'error': str(e)}

        info = self.get_reseller_info()
        return info.get('user_id', 0)
    
    def create_subreseller(self, username: str, password: str, credits: float, email: str = "") -> Dict[str, Any]:
        """Create subreseller using subreseller.php endpoint (DISCOVERED FROM WHMCS!)"""
        if not self.logged_in:
            if not self.login():
                return {'success': False, 'error': 'Failed to login'}
        
        try:
            # POST to subreseller.php (the REAL endpoint for creating subresellers!)
            url = f"{self.panel_url}/subreseller.php"
            
            # Post data matching WHMCS Super module
            form_data = {
                'username': username,
                'password': password,
                'reseller_dns': '',  # Empty for now
                'email': email or f"{username}@subreseller.local",
                'notes': f'Billing Panel Customer - {credits} credits',
                'submit_user': 'Purchase'
            }
            
            logger.info(f"Creating subreseller via subreseller.php: {username}")
            logger.info(f"Post data: {form_data}")
            
            # POST with session cookies and HTTP Basic Auth
            response = self.session.post(url, data=form_data, auth=self.http_auth, timeout=30, allow_redirects=True)
            
            logger.info(f"subreseller.php response: {response.status_code}")
            
            # Log response for debugging
            response_preview = response.text[:1000] if len(response.text) > 1000 else response.text
            logger.info(f"Response preview: {response_preview}")
            
            # Check for success
            # Look for actual error messages, not just CSS class in template
            if '<div class="alert alert-danger' in response.text or 'alert-danger">Error' in response.text:
                # Actual error div with content
                logger.error("Error message found in response")
                # Try to extract error message
                import re
                error_match = re.search(r'alert-danger[^>]*>(.*?)</div>', response.text, re.DOTALL)
                if error_match:
                    error_msg = error_match.group(1).strip()[:200]
                    logger.error(f"Error message: {error_msg}")
                return {'success': False, 'error': 'Subreseller creation failed'}
            elif response.status_code in [200, 302]:
                # No error found, subreseller created successfully
                logger.info("✓ Subreseller created via subreseller.php (no errors detected)")
                
                # Now add credits to the newly created subreseller
                if credits > 0:
                    logger.info(f"Adding {credits} credits to new subreseller {username}")
                    credits_result = self.add_credits(
                        username=username,
                        email=email or f"{username}@subreseller.local",
                        credits=credits
                    )
                    if not credits_result.get('success'):
                        logger.warning(f"Failed to add credits: {credits_result.get('error')}")
                        # Subreseller was created, but credits failed - return partial success
                        return {
                            'success': True, 
                            'username': username, 
                            'credits': 0,
                            'credits_warning': f"Subreseller created but credits not added: {credits_result.get('error')}"
                        }
                    logger.info(f"✓ {credits} credits added successfully")
                
                return {'success': True, 'username': username, 'credits': credits}
            else:
                logger.warning(f"Unexpected status: {response.status_code}")
                return {'success': False, 'error': f'HTTP {response.status_code}'}
                
        except Exception as e:
            logger.error(f"subreseller.php error: {str(e)}")
            return {'success': False, 'error': str(e)}

    def create_reseller(self, username: str, password: str, credits: float, email: str = "", member_group_id: int = 3) -> Dict[str, Any]:
        """Create subreseller under the panel's reseller account"""
        # Customers purchasing "reseller packages" are actually subresellers
        # Created under the whmcs reseller account (owner_id = whmcs's ID)
        return self.create_subreseller(username, password, credits, email)
    
    def add_reseller_credits(self, username: str, credits: float) -> Dict[str, Any]:
        """Add credits to existing reseller"""
        # Ensure logged in
        if not self.logged_in:
            if not self.login():
                return {'success': False, 'error': 'Failed to login'}
        
        try:
            # Find reseller ID first (might need API call)
            # Then update credits via API or direct update
            
            # For now, return not implemented
            logger.warning("add_reseller_credits not yet implemented")
            return {'success': False, 'error': 'Not implemented'}
            
        except Exception as e:
            logger.error(f"Add credits error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def create_subscriber(self, username: str, password: str, package_id: int, bouquets: list, expiry: int) -> Dict[str, Any]:
        """Create subscriber (still using HTTP Basic Auth - works fine)"""
        # Subscribers work with the existing auth method
        # Use the old approach
        pass


    def get_user_info(self, username: str) -> Optional[Dict[str, Any]]:
        """Fetch a user's info from the panel to get actual expiry date"""
        try:
            if not self.logged_in:
                if not self.login():
                    return None
            
            # Try API endpoint first
            api_resp = self.session.get(
                f"{self.panel_url}/api.php",
                params={"username": self.username, "password": self.password, "action": "user", "sub": "info", "user_username": username},
                timeout=15
            )
            if api_resp.status_code == 200:
                try:
                    data = api_resp.json()
                    if data.get("user_info") or data.get("exp_date"):
                        info = data.get("user_info", data)
                        return {"exp_date": info.get("exp_date", ""), "username": username}
                except Exception:
                    pass
            
            # Fallback: scrape from reseller panel user list
            resp = self.session.get(f"{self.panel_url}/user_reseller.php", timeout=15)
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                rows = soup.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if cells and len(cells) > 2:
                        row_username = cells[0].text.strip() if cells else ""
                        if row_username == username:
                            # Find expiry cell (usually contains a date)
                            for cell in cells:
                                text = cell.text.strip()
                                if '-' in text and len(text) >= 10:
                                    return {"exp_date": text, "username": username}
            return None
        except Exception as e:
            logger.warning(f"get_user_info error for {username}: {e}")
            return None


    def fetch_packages(self) -> List[Dict]:
        """Fetch available packages from reseller panel"""
        if not self.logged_in:
            if not self.login():
                return []
        
        try:
            from bs4 import BeautifulSoup
            
            # Get user creation page
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php", auth=self.http_auth, timeout=30)
            
            if page_response.status_code != 200:
                logger.error(f"Failed to fetch packages page: HTTP {page_response.status_code}")
                return []
            
            # Parse HTML
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            
            if not package_select:
                logger.warning("Package select element not found")
                return []
            
            # Extract packages
            packages = []
            options = package_select.find_all('option')
            
            for option in options:
                package_id = option.get('value')
                package_name = option.text.strip()
                
                if package_id and package_id.isdigit():
                    # Fetch package details
                    api_response = self.session.get(
                        f"{self.panel_url}/api.php?action=get_package&package_id={package_id}",
                        auth=self.http_auth,
                        timeout=10
                    )
                    
                    if api_response.status_code == 200:
                        try:
                            data = api_response.json()
                            if data.get('result') == True:
                                # Extract bouquet IDs from package data
                                # data['data']['bouquets'] is a JSON string like "[1,2,3]"
                                pkg_bouquet_ids = []
                                try:
                                    raw_bouquets = data['data'].get('bouquets', '[]')
                                    if isinstance(raw_bouquets, str):
                                        pkg_bouquet_ids = json.loads(raw_bouquets)
                                    elif isinstance(raw_bouquets, list):
                                        pkg_bouquet_ids = raw_bouquets
                                except (json.JSONDecodeError, TypeError):
                                    pkg_bouquet_ids = []
                                
                                # Fallback: extract IDs from top-level bouquet objects
                                if not pkg_bouquet_ids and data.get('bouquets'):
                                    top_bouquets = data.get('bouquets', [])
                                    if isinstance(top_bouquets, list) and top_bouquets:
                                        if isinstance(top_bouquets[0], dict):
                                            pkg_bouquet_ids = [int(b['id']) for b in top_bouquets if 'id' in b]
                                        elif isinstance(top_bouquets[0], (int, str)):
                                            pkg_bouquet_ids = [int(b) for b in top_bouquets]
                                
                                packages.append({
                                    'id': int(package_id),
                                    'name': package_name,
                                    'credits': data['data'].get('cost_credits', 0),
                                    'duration': data['data'].get('official_duration', 0),
                                    'duration_unit': data['data'].get('official_duration_in', 'months'),
                                    'max_connections': data['data'].get('max_connections', 1),
                                    'bouquets': pkg_bouquet_ids
                                })
                                logger.info(f"Package {package_id} ({package_name}): {len(pkg_bouquet_ids)} bouquets")
                        except Exception as e:
                            logger.warning(f"Error parsing package {package_id}: {e}")
            
            logger.info(f"Fetched {len(packages)} packages")
            return packages
            
        except Exception as e:
            logger.error(f"Error fetching packages: {e}")
            return []


    def fetch_bouquets_from_packages(self) -> List[Dict]:
        """Fetch bouquets by getting them from the first available package"""
        if not self.logged_in:
            if not self.login():
                return []
        try:
            from bs4 import BeautifulSoup
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php", auth=self.http_auth, timeout=30)
            if page_response.status_code != 200:
                return []
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            if not package_select:
                return []
            package_ids = [opt.get('value') for opt in package_select.find_all('option') if opt.get('value', '').isdigit()]
            if not package_ids:
                return []
            api_response = self.session.get(
                f"{self.panel_url}/api.php?action=get_package&package_id={package_ids[0]}",
                auth=self.http_auth, timeout=10
            )
            if api_response.status_code == 200:
                data = api_response.json()
                if data.get('result') == True and 'bouquets' in data:
                    return [{'id': b['id'], 'name': b.get('bouquet_name', f"Bouquet {b['id']}")} for b in data['bouquets']]
            return []
        except Exception as e:
            logger.error(f"Error fetching bouquets: {e}")
            return []

    def fetch_trial_packages(self) -> List[Dict]:
        """Fetch trial packages accessible to this reseller"""
        if not self.logged_in:
            if not self.login():
                return []
        try:
            from bs4 import BeautifulSoup
            from concurrent.futures import ThreadPoolExecutor, as_completed
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php?trial", auth=self.http_auth, timeout=30)
            if page_response.status_code != 200:
                return []
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            if not package_select:
                return []
            trial_map = {}
            for opt in package_select.find_all('option'):
                pid = opt.get('value')
                if pid and pid.isdigit():
                    trial_map[int(pid)] = opt.text.strip()

            def fetch_details(package_id, package_name):
                try:
                    r = self.session.get(
                        f"{self.panel_url}/api.php?action=get_package_trial&package_id={package_id}",
                        auth=self.http_auth, timeout=5
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get('result') == True:
                            pd = data.get('data', {})
                            dur = pd.get('trial_duration', 0)
                            dur = int(dur) if str(dur).isdigit() else 0
                            pkg_bouquet_ids = []
                            try:
                                raw = pd.get('bouquets', '[]')
                                pkg_bouquet_ids = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
                            except Exception:
                                pass
                            if not pkg_bouquet_ids and data.get('bouquets'):
                                top = data.get('bouquets', [])
                                if isinstance(top, list) and top and isinstance(top[0], dict):
                                    pkg_bouquet_ids = [int(b['id']) for b in top if 'id' in b]
                            return {
                                'id': int(package_id), 'name': package_name,
                                'credits': float(pd.get('cost_credits', 0) or 0),
                                'duration': dur, 'duration_unit': pd.get('trial_duration_in', 'days'),
                                'max_connections': pd.get('max_connections', 1),
                                'bouquets': pkg_bouquet_ids, 'is_trial': True
                            }
                except Exception:
                    pass
                return None

            packages = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(fetch_details, pid, name): pid for pid, name in trial_map.items()}
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        packages.append(result)
            logger.info(f"Found {len(packages)} trial packages")
            return packages
        except Exception as e:
            logger.error(f"Error fetching trial packages: {e}")
            return []
