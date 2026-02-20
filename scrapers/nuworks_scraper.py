from .base_scraper import BaseScraper
from datetime import datetime
import os
import time
import threading


class NUWorksScraper(BaseScraper):
    def __init__(self, username: str = None, password: str = None, headless: bool = False):
        super().__init__()
        self.source_name = "nuworks"
        self.base_url = "https://northeastern-csm.symplicity.com"
        self.login_url = f"{self.base_url}/sso/students/"
        self.jobs_url = f"{self.base_url}/students/app/jobs"
        
        self.username = username or os.getenv('NUWORKS_USERNAME', '')
        self.password = password or os.getenv('NUWORKS_PASSWORD', '')
        
        self.driver = None
        self.logged_in = False
        self.headless = headless
        self.duo_completed = False
        self.login_status = "idle"  # idle, waiting_credentials, waiting_duo, logged_in, failed
    
    def _init_browser(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            
            options = Options()
            
            # Use Brave browser instead of Chrome
            brave_paths = [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Users\varsv\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"
            ]
            
            brave_path = None
            import os
            for path in brave_paths:
                if os.path.exists(path):
                    brave_path = path
                    break
            
            if brave_path:
                options.binary_location = brave_path
                print(f"Using Brave browser at: {brave_path}")
            else:
                print("Brave not found, falling back to Chrome")
            
            if self.headless:
                options.add_argument('--headless=new')
            
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--start-maximized')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Selenium 4.6+ has built-in driver management - no need for webdriver_manager
            # It will automatically download the correct ChromeDriver version
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            
            print("Browser initialized successfully (visible mode for Duo 2FA)")
            return True
        except Exception as e:
            print(f"Error initializing browser: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def start_login(self) -> dict:
        """
        Start the login process - opens browser and enters credentials.
        Returns status for the frontend to display.
        """
        if not self.username or not self.password:
            return {
                'status': 'error',
                'message': 'Credentials not provided. Please enter your NUWorks username and password.'
            }
        
        if not self.driver:
            if not self._init_browser():
                return {
                    'status': 'error', 
                    'message': 'Failed to initialize browser. Make sure Chrome is installed.'
                }
        
        self.login_status = "waiting_duo"
        
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            print("Navigating to NUWorks login page...")
            self.driver.get(self.login_url)
            time.sleep(2)
            
            username_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            username_field.clear()
            username_field.send_keys(self.username)
            
            password_field = self.driver.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(self.password)
            
            login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
            login_button.click()
            
            print("Credentials entered. Waiting for Duo 2FA...")
            print(">>> Please complete Duo authentication in the browser window <<<")
            
            return {
                'status': 'waiting_duo',
                'message': 'Credentials entered. Please complete Duo 2FA in the browser window, then click "I Completed Duo".'
            }
            
        except Exception as e:
            self.login_status = "failed"
            return {
                'status': 'error',
                'message': f'Login error: {str(e)}'
            }
    
    def check_login_status(self) -> dict:
        """
        Check if user has completed Duo and is now logged in.
        """
        if not self.driver:
            return {'status': 'error', 'message': 'Browser not initialized'}
        
        try:
            current_url = self.driver.current_url.lower()
            
            if "students" in current_url and "sso" not in current_url:
                self.logged_in = True
                self.login_status = "logged_in"
                print("Successfully logged into NUWorks!")
                return {
                    'status': 'logged_in',
                    'message': 'Successfully logged into NUWorks! You can now scrape jobs.'
                }
            
            if "duo" in current_url or "sso" in current_url:
                return {
                    'status': 'waiting_duo',
                    'message': 'Still waiting for Duo authentication. Please complete 2FA in the browser.'
                }
            
            return {
                'status': 'checking',
                'message': 'Checking login status...'
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Error checking status: {str(e)}'
            }
    
    def wait_for_duo_completion(self, timeout: int = 120) -> bool:
        """
        Wait for user to complete Duo 2FA.
        Polls every 2 seconds for up to `timeout` seconds.
        """
        print(f"Waiting up to {timeout} seconds for Duo completion...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.check_login_status()
            
            if status['status'] == 'logged_in':
                return True
            elif status['status'] == 'error':
                print(f"Error: {status['message']}")
                return False
            
            time.sleep(2)
        
        print("Timeout waiting for Duo authentication")
        return False
    
    def login(self, wait_for_duo: bool = True, duo_timeout: int = 120) -> bool:
        """
        Full login flow with Duo 2FA support.
        Opens browser, enters credentials, waits for manual Duo completion.
        """
        result = self.start_login()
        
        if result['status'] == 'error':
            print(f"Login failed: {result['message']}")
            return False
        
        if result['status'] == 'waiting_duo' and wait_for_duo:
            return self.wait_for_duo_completion(duo_timeout)
        
        return self.logged_in
    
    def search_jobs(self, keyword: str, location: str, page: int = 1) -> list:
        jobs = []
        
        if not self.logged_in:
            print("Cannot search NUWorks - not logged in")
            return jobs
        
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from urllib.parse import quote
            
            encoded_keyword = quote(keyword)
            encoded_location = quote(location)
            search_url = f"{self.jobs_url}?keywords={encoded_keyword}&location={encoded_location}"
            
            print(f"Searching NUWorks for: {keyword} in {location}")
            self.driver.get(search_url)
            time.sleep(3)
            
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 
                        ".job-listing, .posting-item, [data-job-id], .list-item, .job-row, tr[data-id]"))
                )
            except:
                print("No job listings found or page structure different")
                return jobs
            
            job_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                ".job-listing, .posting-item, [data-job-id], .list-item, .job-row, tr[data-id], .posting")
            
            print(f"Found {len(job_elements)} job elements")
            
            for elem in job_elements:
                try:
                    job_data = self._parse_selenium_listing(elem)
                    if job_data:
                        jobs.append(job_data)
                except Exception as e:
                    print(f"Error parsing NUWorks job element: {e}")
                    continue
            
            print(f"Parsed {len(jobs)} valid jobs")
            
        except Exception as e:
            print(f"Error searching NUWorks: {e}")
        
        return jobs
    
    def _parse_selenium_listing(self, element) -> dict:
        from selenium.webdriver.common.by import By
        
        title = ""
        company = ""
        location = ""
        job_url = ""
        
        title_selectors = [
            ".job-title", ".posting-title", "h3", "h4", "a.title",
            ".title", "[data-field='title']", ".position-title"
        ]
        for selector in title_selectors:
            try:
                title_elem = element.find_element(By.CSS_SELECTOR, selector)
                title = title_elem.text.strip()
                if title:
                    break
            except:
                continue
        
        company_selectors = [
            ".employer-name", ".company-name", ".organization",
            ".employer", "[data-field='employer']", ".company"
        ]
        for selector in company_selectors:
            try:
                company_elem = element.find_element(By.CSS_SELECTOR, selector)
                company = company_elem.text.strip()
                if company:
                    break
            except:
                continue
        
        location_selectors = [
            ".location", ".job-location", ".city",
            "[data-field='location']", ".posting-location"
        ]
        for selector in location_selectors:
            try:
                location_elem = element.find_element(By.CSS_SELECTOR, selector)
                location = location_elem.text.strip()
                if location:
                    break
            except:
                continue
        
        try:
            link_elem = element.find_element(By.CSS_SELECTOR, "a[href*='jobs'], a[href*='posting'], a.job-link, a")
            job_url = link_elem.get_attribute('href')
        except:
            pass
        
        try:
            date_elem = element.find_element(By.CSS_SELECTOR, ".date-posted, .posted-date, .date, [data-field='date']")
            date_text = date_elem.text.strip()
            date_posted = self.parse_relative_date(date_text)
        except:
            date_posted = datetime.utcnow()
        
        if not title and not company:
            try:
                text_content = element.text.strip()
                lines = [l.strip() for l in text_content.split('\n') if l.strip()]
                if len(lines) >= 2:
                    title = lines[0]
                    company = lines[1]
                    if len(lines) >= 3:
                        location = lines[2]
            except:
                pass
        
        if not title or not company:
            return None
        
        return self.create_job_dict(
            title=title,
            company=company,
            location=location,
            job_url=job_url,
            date_posted=date_posted,
            job_type='co-op'
        )
    
    def parse_job_listing(self, listing) -> dict:
        return None
    
    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
            self.logged_in = False
            self.login_status = "idle"
    
    def __del__(self):
        self.close()
