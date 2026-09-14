import requests
from bs4 import BeautifulSoup
import json
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class XtreamUISessionClient:
    """XtreamUI Admin/Reseller Panel Client with Session Authentication"""
    
    def __init__(self, panel_url: str, username: str, password: str):
        # Remove embedded credentials from URL if present
        if '@' in panel_url:
            parts = panel_url.split('@')
            if len(parts) == 2:
                protocol = parts[0].split('//')[0]
                self.panel_url = f"{protocol}//{parts[1]}"
                # Use embedded credentials
                cred_part = parts[0].split('//')[1]
                if ':' in cred_part:
                    self.http_user, self.http_pass = cred_part.split(':', 1)
                else:
                    self.http_user, self.http_pass = username, password
            else:
                self.panel_url = panel_url
                self.http_user, self.http_pass = username, password
        else:
            self.panel_url = panel_url
            self.http_user, self.http_pass = username, password
        
        self.panel_url = self.panel_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.auth = (self.http_user, self.http_pass)
        self.session.verify = False
        self.logged_in = False
    
    def login(self) -> bool:
        """Login to XtreamUI panel"""
        try:
            response = self.session.post(
                f"{self.panel_url}/login.php",
                data={'username': self.username, 'password': self.password},
                allow_redirects=False,
                timeout=30
            )
            
            if 'PHPSESSID' in self.session.cookies:
                self.logged_in = True
                logger.info(f"Logged in to XtreamUI panel as {self.username}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"XtreamUI login failed: {e}")
            return False
    
    def fetch_bouquets_from_packages(self) -> List[Dict]:
        """Fetch bouquets by scraping packages from reseller panel"""
        if not self.logged_in:
            if not self.login():
                return []
        
        try:
            # Get user creation page
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php", timeout=30)
            
            if page_response.status_code != 200 or len(page_response.text) == 0:
                logger.warning("Could not access user_reseller.php page")
                return []
            
            # Parse HTML
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            
            if not package_select:
                logger.warning("No package select found")
                return []
            
            # Get package IDs
            options = package_select.find_all('option')
            package_ids = [opt.get('value') for opt in options if opt.get('value') and opt.get('value').isdigit()]
            
            if not package_ids:
                logger.warning("No package IDs found")
                return []
            
            logger.info(f"Found {len(package_ids)} packages")
            
            # Fetch bouquets from first package (they usually all have same bouquets)
            first_package_id = package_ids[0]
            
            api_response = self.session.get(
                f"{self.panel_url}/api.php?action=get_package&package_id={first_package_id}",
                timeout=10
            )
            
            if api_response.status_code == 200:
                data = api_response.json()
                
                if data.get('result') == True and 'bouquets' in data:
                    bouquets = data['bouquets']
                    logger.info(f"Fetched {len(bouquets)} bouquets from package {first_package_id}")
                    
                    # Convert to simplified format
                    bouquet_list = [
                        {
                            'id': b['id'],
                            'name': b['bouquet_name']
                        }
                        for b in bouquets
                    ]
                    
                    return bouquet_list
            
            return []
            
        except Exception as e:
            logger.error(f"Error fetching bouquets: {e}")
            return []
    
    def fetch_packages(self) -> List[Dict]:
        """Fetch available packages from reseller panel"""
        if not self.logged_in:
            if not self.login():
                return []
        
        try:
            # Get user creation page
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php", timeout=30)
            
            if page_response.status_code != 200:
                return []
            
            # Parse HTML
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            
            if not package_select:
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
                        timeout=10
                    )
                    
                    if api_response.status_code == 200:
                        try:
                            data = api_response.json()
                            if data.get('result') == True:
                                packages.append({
                                    'id': int(package_id),
                                    'name': package_name,
                                    'credits': data['data'].get('cost_credits', 0),
                                    'duration': data['data'].get('official_duration', 0),
                                    'duration_unit': data['data'].get('official_duration_in', 'months'),
                                    'max_connections': data['data'].get('max_connections', 1),
                                    'bouquets': data.get('bouquets', [])
                                })
                        except Exception:
                            pass
            
            return packages
            
        except Exception as e:
            logger.error(f"Error fetching packages: {e}")
            return []

    def fetch_trial_packages(self) -> List[Dict]:
        """Fetch trial packages that the reseller has access to
        
        Uses user_reseller.php?trial to get the list of trial packages
        assigned to this reseller account.
        """
        if not self.logged_in:
            if not self.login():
                return []
        
        try:
            # Get trial package IDs from user_reseller.php?trial
            page_response = self.session.get(f"{self.panel_url}/user_reseller.php?trial", timeout=30)
            
            if page_response.status_code != 200:
                logger.warning(f"Could not access user_reseller.php?trial")
                return []
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page_response.text, 'html.parser')
            package_select = soup.find('select', {'id': 'package'})
            
            if not package_select:
                logger.warning("No package select found on trial page")
                return []
            
            # Get trial package IDs and names
            options = package_select.find_all('option')
            trial_package_map = {}
            
            for opt in options:
                pkg_id = opt.get('value')
                if pkg_id and pkg_id.isdigit():
                    trial_package_map[int(pkg_id)] = opt.text.strip()
            
            logger.info(f"Found {len(trial_package_map)} trial packages accessible to this reseller")
            
            packages = []
            
            # Use threading for parallel requests
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def fetch_trial_details(package_id, package_name):
                """Fetch trial package details"""
                try:
                    api_response = self.session.get(
                        f"{self.panel_url}/api.php?action=get_package_trial&package_id={package_id}",
                        timeout=3
                    )
                    
                    if api_response.status_code == 200:
                        data = api_response.json()
                        
                        if data.get('result') == True:
                            package_data = data.get('data', {})
                            
                            # Get trial duration
                            trial_duration = package_data.get('trial_duration', 0)
                            if isinstance(trial_duration, str):
                                trial_duration = int(trial_duration) if trial_duration.isdigit() else 0
                            else:
                                trial_duration = int(trial_duration) if trial_duration else 0
                            
                            trial_credits = package_data.get('cost_credits', 0)
                            if isinstance(trial_credits, str):
                                trial_credits = float(trial_credits) if trial_credits.replace('.', '').replace('-', '').isdigit() else 0
                            else:
                                trial_credits = float(trial_credits) if trial_credits else 0
                            
                            return {
                                'id': int(package_id),
                                'name': package_name,  # Actual name from dropdown
                                'credits': trial_credits,
                                'duration': trial_duration,
                                'duration_unit': package_data.get('trial_duration_in', 'days'),
                                'max_connections': package_data.get('max_connections', 1),
                                'bouquets': data.get('bouquets', []),
                                'is_trial': True
                            }
                except Exception:
                    pass
                
                return None
            
            # Fetch details for all trial packages in parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(fetch_trial_details, pid, name): pid 
                          for pid, name in trial_package_map.items()}
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        packages.append(result)
                        logger.info(f"  ✓ Trial: {result['name']} (ID {result['id']}) - {result['duration']} {result['duration_unit']}")
            
            logger.info(f"Found {len(packages)} trial packages accessible to reseller")
            return packages
            
        except Exception as e:
            logger.error(f"Error fetching trial packages: {e}")
            return []

