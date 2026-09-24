"""
Auto-Update System for IPTV Billing Panel - SAFE VERSION
Pulls updates from GitHub using overlay method (no file deletion)
"""
import os
import subprocess
import shutil
import json
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class UpdateManager:
    def __init__(self):
        self.repo_url = "https://github.com/asherpoirier/iptvbcms.git"
        
        # Detect if running in production (/opt) or development (/app)
        if os.path.exists("/opt/backend"):
            self.app_dir = "/opt"
        else:
            self.app_dir = "/app"
        
        self.backup_dir = f"{self.app_dir}/backups"
        self.version_file = f"{self.app_dir}/VERSION.json"
        
        logger.info(f"UpdateManager initialized with app_dir: {self.app_dir}")
        
    def get_current_version(self):
        """Get current installed version"""
        try:
            if os.path.exists(self.version_file):
                with open(self.version_file, 'r') as f:
                    data = json.load(f)
                    return data.get('version'), data.get('commit_hash')
            return None, None
        except Exception as e:
            logger.error(f"Failed to read version: {e}")
            return None, None
    
    def get_latest_version(self):
        """Check GitHub for latest version"""
        try:
            # Get latest commit hash from GitHub
            cmd = f"git ls-remote {self.repo_url} HEAD"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                commit_hash = result.stdout.split()[0]
                return commit_hash
            
            return None
        except Exception as e:
            logger.error(f"Failed to check GitHub: {e}")
            return None
    
    def check_for_updates(self):
        """Check if updates are available"""
        try:
            current_version, current_commit = self.get_current_version()
            latest_commit = self.get_latest_version()
            
            logger.info(f"Current commit: {current_commit}")
            logger.info(f"Latest commit: {latest_commit}")
            
            if not latest_commit:
                return {
                    "update_available": False,
                    "error": "Failed to check GitHub",
                    "current_commit": current_commit,
                    "latest_commit": None
                }
            
            update_available = current_commit != latest_commit if current_commit else True
            
            return {
                "update_available": update_available,
                "current_commit": current_commit,
                "latest_commit": latest_commit,
                "current_version": current_version
            }
        except Exception as e:
            logger.error(f"Update check error: {e}")
            return {
                "update_available": False,
                "error": str(e)
            }
    
    def create_backup(self):
        """Create backup of current installation"""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.backup_dir}/backup_{timestamp}"
            
            os.makedirs(self.backup_dir, exist_ok=True)
            
            logger.info(f"Creating backup at {backup_path}")
            logger.info(f"Backing up from: {self.app_dir}")
            
            # Only backup if directories exist
            if os.path.exists(f"{self.app_dir}/backend"):
                shutil.copytree(
                    f"{self.app_dir}/backend", 
                    f"{backup_path}/backend", 
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.venv', 'venv', '*.log')  # CMTV local change 2026-09-24: the folder is 'venv' (no dot); copying it added 1.4 GB to every update backup
                )
            
            if os.path.exists(f"{self.app_dir}/frontend"):
                shutil.copytree(
                    f"{self.app_dir}/frontend", 
                    f"{backup_path}/frontend", 
                    ignore=shutil.ignore_patterns('node_modules', 'build')
                )
            
            if os.path.exists(self.version_file):
                shutil.copy(self.version_file, f"{backup_path}/VERSION.json")
            
            logger.info(f"✓ Backup created: {backup_path}")
            return backup_path
            
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            raise Exception(f"Failed to create backup: {e}")
    
    def apply_update(self, backup_path=None):
        """SAFE UPDATE: Overlay files without deleting infrastructure"""
        try:
            logger.info("Starting SAFE update process...")
            
            temp_dir = "/tmp/iptvbcms_update"
            
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            
            logger.info(f"Cloning from {self.repo_url}")
            cmd = f"git clone --depth 1 {self.repo_url} {temp_dir}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")
            
            cmd = f"cd {temp_dir} && git rev-parse HEAD"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            new_commit = result.stdout.strip()
            
            logger.info(f"Downloaded commit: {new_commit}")
            
            # SAFE OVERLAY METHOD - Never delete .venv, node_modules, .env
            logger.info("Overlaying backend files...")
            if os.path.exists(f"{temp_dir}/backend"):
                for root, dirs, files in os.walk(f"{temp_dir}/backend"):
                    # Skip git directories
                    dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__']]
                    
                    rel_path = os.path.relpath(root, f"{temp_dir}/backend")
                    target_dir = f"{self.app_dir}/backend/{rel_path}" if rel_path != '.' else f"{self.app_dir}/backend"
                    os.makedirs(target_dir, exist_ok=True)
                    
                    for file in files:
                        if file not in ['.env']:
                            src = os.path.join(root, file)
                            dst = os.path.join(target_dir, file)
                            shutil.copy2(src, dst)
            
            logger.info("Overlaying frontend files...")
            if os.path.exists(f"{temp_dir}/frontend"):
                for root, dirs, files in os.walk(f"{temp_dir}/frontend"):
                    dirs[:] = [d for d in dirs if d not in ['node_modules', 'build', '.git', '__pycache__']]
                    
                    rel_path = os.path.relpath(root, f"{temp_dir}/frontend")
                    target_dir = f"{self.app_dir}/frontend/{rel_path}" if rel_path != '.' else f"{self.app_dir}/frontend"
                    os.makedirs(target_dir, exist_ok=True)
                    
                    for file in files:
                        if file not in ['.env']:
                            src = os.path.join(root, file)
                            dst = os.path.join(target_dir, file)
                            shutil.copy2(src, dst)
                
                # Rebuild frontend for production
                logger.info("Rebuilding frontend...")
                cmd = f"cd {self.app_dir}/frontend && yarn build"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
                
                if result.returncode != 0:
                    logger.warning(f"Frontend build had warnings: {result.stderr}")
                else:
                    logger.info("✓ Frontend rebuilt successfully")
            
            # Update version file
            version_data = {
                "version": datetime.utcnow().strftime("%Y.%m.%d.%H%M"),
                "commit_hash": new_commit,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            with open(self.version_file, 'w') as f:
                json.dump(version_data, f, indent=2)
            
            shutil.rmtree(temp_dir)
            
            # DON'T restart here - let the API respond first
            logger.info("✓ Update applied successfully (safe overlay mode)")
            logger.info("Services will be restarted by API endpoint after response is sent")
            
            return {
                "success": True,
                "version": version_data,
                "message": "Update applied successfully. Services restarting..."
            }
            
        except Exception as e:
            logger.error(f"Update failed: {e}")
            
            if backup_path and os.path.exists(backup_path):
                logger.info(f"Rolling back to backup: {backup_path}")
                self.rollback(backup_path)
                return {
                    "success": False,
                    "error": str(e),
                    "rolled_back": True
                }
            
            return {
                "success": False,
                "error": str(e),
                "rolled_back": False
            }
    
    def rollback(self, backup_path):
        """Restore from backup - SAFE: overlay only"""
        try:
            logger.info(f"Restoring from backup: {backup_path}")
            
            # SAFE: Just copy backup files over existing (don't delete anything)
            if os.path.exists(f"{backup_path}/backend"):
                for root, dirs, files in os.walk(f"{backup_path}/backend"):
                    rel_path = os.path.relpath(root, f"{backup_path}/backend")
                    target_dir = f"{self.app_dir}/backend/{rel_path}" if rel_path != '.' else f"{self.app_dir}/backend"
                    os.makedirs(target_dir, exist_ok=True)
                    
                    for file in files:
                        src = os.path.join(root, file)
                        dst = os.path.join(target_dir, file)
                        shutil.copy2(src, dst)
            
            if os.path.exists(f"{backup_path}/frontend"):
                for root, dirs, files in os.walk(f"{backup_path}/frontend"):
                    rel_path = os.path.relpath(root, f"{backup_path}/frontend")
                    target_dir = f"{self.app_dir}/frontend/{rel_path}" if rel_path != '.' else f"{self.app_dir}/frontend"
                    os.makedirs(target_dir, exist_ok=True)
                    
                    for file in files:
                        src = os.path.join(root, file)
                        dst = os.path.join(target_dir, file)
                        shutil.copy2(src, dst)
            
            if os.path.exists(f"{backup_path}/VERSION.json"):
                shutil.copy(f"{backup_path}/VERSION.json", self.version_file)
            
            logger.info("✓ Rollback completed")
            return True
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False
    
    def restart_services(self):
        """Restart backend and frontend services"""
        try:
            logger.info("Restarting services...")
            subprocess.run("supervisorctl restart backend frontend", shell=True, timeout=30)
            logger.info("✓ Services restarted")
            return True
        except Exception as e:
            logger.error(f"Failed to restart services: {e}")
            return False
    
    def list_backups(self):
        """List available backups"""
        try:
            if not os.path.exists(self.backup_dir):
                return []
            
            backups = []
            for item in os.listdir(self.backup_dir):
                backup_path = f"{self.backup_dir}/{item}"
                if os.path.isdir(backup_path):
                    stat = os.stat(backup_path)
                    backups.append({
                        "name": item,
                        "path": backup_path,
                        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                        "size_mb": sum(f.stat().st_size for f in Path(backup_path).rglob('*') if f.is_file()) / (1024 * 1024)
                    })
            
            return sorted(backups, key=lambda x: x['created'], reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

# Singleton instance
update_manager = UpdateManager()
