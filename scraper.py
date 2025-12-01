"""
Hiya Business Phone Numbers Scraper
Extracts phone registration data and exports to CSV
Fixed version for Railway deployment
"""

import asyncio
import csv
import os
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import json
import time

class HiyaScraper:
    def __init__(self, email=None, password=None, manual_login=False, cookies=None):
        self.email = email
        self.password = password
        self.manual_login = manual_login  # New flag for manual login mode
        self.cookies = cookies  # Pre-authenticated cookies
        self.base_url = "https://business.hiya.com"
        self.login_url = "https://auth-console.hiya.com/u/login?state=hKFo2SAtSWtMVzNXN1haaS1hbG5NR0lMSnNYbmY5Z1JqUUZ4SKFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIE1JekpYbWNvQUFoZDVlSm50elhabnhVZTl4b0tmU1Zso2NpZNkgUHpRQlgzd0ZUMEdiNnVuMVI0SUtQcjlaSWF3TXRkNzU"
        self.phones_url = f"{self.base_url}/registration/cross-carrier-registration/phones"
        self.data = []
        self.total_pages = 20
        self.context = None  # Store browser context for cookie updates
        self.device_cookies = []  # Store device trust cookies separately

    def check_cookies_expired(self):
        """Check if session cookies are expired or about to expire"""
        if not self.cookies:
            return True

        current_time = time.time()
        critical_cookies = ['auth0', 'auth0_compat', 'appSession.0', 'appSession.1']

        for cookie in self.cookies:
            if cookie.get('name') in critical_cookies:
                expires = cookie.get('expires', -1)

                # If expires is -1, it's a session cookie (expires when browser closes)
                if expires == -1:
                    continue

                # Check if cookie expires within the next hour (3600 seconds)
                if expires < current_time + 3600:
                    print(f"⚠️  Cookie '{cookie.get('name')}' is expired or expiring soon")
                    return True

        return False

    def separate_device_cookies(self):
        """Separate device trust cookies from session cookies"""
        if not self.cookies:
            return

        # Device trust cookies that should be preserved during re-authentication
        device_cookie_names = ['did', 'did_compat', 'auth0-mf', 'auth0-mf_compat',
                               '_cfuvid', 'hubspotutk', '__hstc', '_lfa']

        self.device_cookies = [
            cookie for cookie in self.cookies
            if cookie.get('name') in device_cookie_names
        ]

        print(f"📌 Preserved {len(self.device_cookies)} device trust cookies")

    async def refresh_session_cookies(self, page):
        """Refresh session by re-authenticating with email/password (2FA skipped via device cookies)"""
        print("\n" + "="*60)
        print("🔄 SESSION REFRESH: Re-authenticating to get fresh cookies")
        print("="*60)

        if not self.email or not self.password:
            raise Exception("Cannot refresh session: email/password not provided")

        # Preserve device trust cookies
        self.separate_device_cookies()

        # Navigate to login page
        print("📍 Navigating to login page...")
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        # Wait for login form
        print("⏳ Waiting for login form...")
        await page.wait_for_selector('input[type="email"], input[type="text"]', timeout=10000)

        # Fill in credentials
        print(f"🔑 Entering credentials for: {self.email}")
        email_input = page.locator('input[type="email"], input[name="username"], input[name="email"]').first
        await email_input.fill(self.email)

        password_input = page.locator('input[type="password"], input[name="password"]').first
        await password_input.fill(self.password)

        # Click login button
        print("👆 Clicking login button...")
        login_button = page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Continue")').first
        await login_button.click()

        # Wait for navigation after login
        print("⏳ Waiting for authentication...")
        await asyncio.sleep(5)

        # Check current URL
        current_url = page.url
        print(f"📍 Current URL: {current_url}")

        # Check if we're asked for 2FA
        if "mfa" in current_url.lower() or "verify" in current_url.lower():
            print("⚠️  2FA verification page detected!")
            print("💡 This should NOT happen if device cookies are valid")
            print("🔧 Possible solutions:")
            print("   1. Run capture_cookies.py again and check 'Remember this device'")
            print("   2. Ensure auth0-mf cookie is included in HIYA_COOKIES")
            raise Exception("2FA required but cannot be automated. Please refresh device cookies.")

        # Wait for successful redirect to business portal
        try:
            await page.wait_for_url("**/business.hiya.com/**", timeout=15000)
            print("✅ Login successful! Skipped 2FA via device trust cookies")
        except PlaywrightTimeout:
            await asyncio.sleep(3)
            current_url = page.url
            if "business.hiya.com" in current_url:
                print("✅ Login successful!")
            else:
                raise Exception(f"Login failed - unexpected URL: {current_url}")

        # Capture fresh cookies
        print("🍪 Capturing fresh session cookies...")
        fresh_cookies = await self.context.cookies()

        # Merge device cookies with fresh session cookies
        # Remove duplicates, preferring device cookies for device-related ones
        device_cookie_names = [c['name'] for c in self.device_cookies]
        merged_cookies = self.device_cookies.copy()

        for cookie in fresh_cookies:
            if cookie['name'] not in device_cookie_names:
                merged_cookies.append(cookie)

        self.cookies = merged_cookies
        print(f"✅ Updated cookie store with {len(self.cookies)} total cookies")

        # Navigate to phones page
        print("📍 Navigating to phones page...")
        await page.goto(self.phones_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        print("="*60)
        print("✅ SESSION REFRESH COMPLETE")
        print("="*60 + "\n")

    async def wait_for_manual_login(self, page):
        """Wait for user to manually complete login and reach the phones page"""
        print("\n" + "="*60)
        print("🔐 MANUAL LOGIN REQUIRED")
        print("="*60)
        print("Please complete the following steps in the browser window:")
        print("1. Complete the Google OAuth login")
        print("2. Navigate to the phones page if not automatically redirected")
        print("3. The scraper will automatically detect when you're ready")
        print("="*60 + "\n")

        # Wait for user to reach the phones page (or any hiya.com page with registration)
        max_wait_time = 300  # 5 minutes max
        start_time = asyncio.get_event_loop().time()

        while True:
            current_url = page.url

            # Check if we've reached the target page
            if "business.hiya.com" in current_url and "registration" in current_url:
                print("✓ Login detected! You've reached the Hiya portal")
                await asyncio.sleep(2)  # Small delay to ensure page is fully loaded
                return True

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > max_wait_time:
                raise Exception("Manual login timeout - please try again")

            # Check every 2 seconds
            await asyncio.sleep(2)

            # Print progress every 10 seconds
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                remaining = int(max_wait_time - elapsed)
                print(f"⏳ Waiting for login... ({remaining}s remaining)")

    async def login(self, page):
        """Handle login to Hiya - supports cookie, manual, and automatic modes"""

        # Cookie-based authentication (preferred method)
        if self.cookies:
            print("Using cookie-based authentication...")
            # Cookies will be loaded in the scrape() method via context
            print("✓ Cookies loaded, skipping login")
            return

        if self.manual_login:
            # Manual login mode - open login page and wait for user
            print("Opening login page for manual authentication...")
            await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
            await self.wait_for_manual_login(page)
            print("✓ Manual login successful!")
            return

        # Automatic login mode (keeping old logic for backwards compatibility)
        print("Navigating to login page...")
        await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for login form
        await page.wait_for_selector('input[type="email"], input[type="text"]', timeout=10000)

        # Fill in credentials
        print("Entering credentials...")
        email_input = page.locator('input[type="email"], input[name="username"], input[name="email"]').first
        await email_input.fill(self.email)

        password_input = page.locator('input[type="password"], input[name="password"]').first
        await password_input.fill(self.password)

        # Click login button
        login_button = page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Continue")').first
        await login_button.click()

        # Wait for navigation after login
        print("Waiting for authentication...")
        await asyncio.sleep(5)

        # Check for "Remember this device" or verification page
        current_url = page.url
        print(f"Current URL after login: {current_url}")

        # Look for common verification/remember device buttons
        try:
            # Check for "Remember this device", "Trust this device", "Continue", "Yes", "Verify" buttons
            verification_buttons = [
                'button:has-text("Remember")',
                'button:has-text("Trust")',
                'button:has-text("Yes")',
                'button:has-text("Continue")',
                'button:has-text("Verify")',
                'button:has-text("Skip")',
                'button[type="submit"]'
            ]

            for selector in verification_buttons:
                button = page.locator(selector).first
                if await button.count() > 0:
                    try:
                        is_visible = await button.is_visible()
                        if is_visible:
                            print(f"Found verification button: {selector}")
                            await button.click()
                            print("✓ Clicked verification button")
                            await asyncio.sleep(3)
                            break
                    except:
                        continue
        except Exception as e:
            print(f"No verification button found or already past verification: {e}")

        # Wait for final navigation to complete
        try:
            await page.wait_for_url("**/registration/**", timeout=15000)
            print("✓ Login successful!")
        except PlaywrightTimeout:
            # Sometimes redirects take different paths
            await asyncio.sleep(5)
            current_url = page.url
            print(f"Final URL: {current_url}")
            if "hiya.com" in current_url and "login" not in current_url:
                print("✓ Login successful!")
            else:
                raise Exception("Login failed - still on login page")
    
    async def extract_table_data(self, page):
        """Extract data from the current page using MUI table structure"""
        print("Extracting table data...")
        
        # Wait for table to be visible
        await page.wait_for_selector('tbody.MuiTableBody-root', timeout=15000)
        
        # Wait for actual phone number links to appear
        try:
            await page.wait_for_selector('tbody.MuiTableBody-root a[href*="/phones/"]', timeout=10000)
            # Reduced wait time - data should be loaded by now
            await asyncio.sleep(1)
        except PlaywrightTimeout:
            print("⚠ Warning: Phone links not found, might be loading...")
            await asyncio.sleep(2)
        
        # Get all table rows from tbody
        rows = await page.locator('tbody.MuiTableBody-root tr.MuiTableRow-root').all()
        
        # Filter out rows that don't have phone data
        valid_rows = []
        for row in rows:
            links = await row.locator('a').count()
            if links > 0:
                valid_rows.append(row)
        
        print(f"Found {len(rows)} total rows, {len(valid_rows)} with data")
        
        if not valid_rows:
            print("⚠ No data rows found")
            return []
        
        return await self.extract_from_mui_table(page, valid_rows)
    
    async def extract_from_mui_table(self, page, rows):
        """Extract data from MUI table rows"""
        data = []
        
        for i, row in enumerate(rows):
            try:
                # Get all table cells in the row
                cells = await row.locator('td.MuiTableCell-root').all()
                
                # Debug: print cell count for first row
                if i == 0:
                    print(f"First row has {len(cells)} cells")
                
                if len(cells) < 7:
                    continue
                
                # Extract phone number (2nd cell, inside <a> tag)
                phone_number = await cells[1].locator('a').inner_text()
                
                # Extract submitted date and email (3rd cell, has two spans)
                spans = await cells[2].locator('span').all()
                submitted_date = await spans[0].inner_text() if len(spans) > 0 else ''
                submitted_email = await spans[1].inner_text() if len(spans) > 1 else ''
                
                # Extract registration job name (4th cell)
                job_name = await cells[3].inner_text()
                
                # Extract branded call (5th cell) - Try to get from SVG title attribute
                try:
                    svg_element = cells[4].locator('svg')
                    branded_call_title = await svg_element.get_attribute('title')
                    if branded_call_title:
                        branded_call = branded_call_title
                    else:
                        branded_call = await cells[4].inner_text()
                except:
                    branded_call = await cells[4].inner_text()
                
                # Extract spam labeling (6th cell)
                spam_labeling = await cells[5].inner_text()
                
                # Extract spam category (7th cell)
                spam_category = await cells[6].inner_text()
                
                # Extract registration status (8th cell, if exists)
                registration_status = await cells[7].inner_text() if len(cells) > 7 else ''
                
                row_data = {
                    'phone_number': phone_number.strip(),
                    'submitted_date': submitted_date.strip(),
                    'submitted_email': submitted_email.strip(),
                    'registration_job_name': job_name.strip(),
                    'branded_call': branded_call.strip(),
                    'spam_labeling': spam_labeling.strip(),
                    'spam_category': spam_category.strip(),
                    'registration_status': registration_status.strip(),
                }
                
                data.append(row_data)
                
            except Exception as e:
                print(f"Error extracting row {i}: {e}")
                try:
                    cells_count = await row.locator('td.MuiTableCell-root').count()
                    print(f"  Row {i} has {cells_count} cells")
                except:
                    pass
                continue
        
        return data
    
    async def click_next_page(self, page):
        """Click the next page button"""
        try:
            # Find the next button using data-id attribute
            next_button = page.locator('button[data-id="pagination-next-button"]')
            
            # Check if button is disabled
            is_disabled = await next_button.is_disabled()
            if is_disabled:
                print("Next button is disabled - reached last page")
                return False
            
            # Click the next button
            print("Clicking next page button...")
            await next_button.click()
            
            # Wait for page to load
            await asyncio.sleep(3)
            
            # Wait for table to update with new data
            await page.wait_for_selector('tbody.MuiTableBody-root', timeout=10000)
            
            # Additional wait for data to populate
            await asyncio.sleep(2)
            
            return True
            
        except Exception as e:
            print(f"Error clicking next button: {e}")
            return False
    
    async def handle_pagination(self, page):
        """Navigate through all pages using next button clicks"""
        all_data = []
        
        # Total pages is 20
        total_pages = self.total_pages
        current_page = 1
        
        while current_page <= total_pages:
            print(f"\n--- Processing Page {current_page} of {total_pages} ---")
            
            # Extract data from current page
            page_data = await self.extract_table_data(page)
            
            if page_data:
                all_data.extend(page_data)
                print(f"✓ Extracted {len(page_data)} records from page {current_page}")
            else:
                print(f"⚠ No data found on page {current_page}")
                # If we hit an empty page, we might be done
                if current_page > 1:
                    print("No more data, stopping pagination")
                    break
            
            print(f"Total records so far: {len(all_data)}")
            
            # Check if we're on the last page
            if current_page >= total_pages:
                print("Reached target page count")
                break
            
            # Click next page button
            success = await self.click_next_page(page)
            
            if not success:
                print("Could not navigate to next page, stopping")
                break
            
            current_page += 1
        
        return all_data
    
    async def scrape(self):
        """Main scraping logic"""
        async with async_playwright() as p:
            # Launch browser
            print("Launching browser...")

            # FIXED: Use headless mode for production, but NEVER for manual login
            is_production = os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('PORT')

            # Force headless=False for manual login mode
            use_headless = bool(is_production) and not self.manual_login

            browser = await p.chromium.launch(
                headless=use_headless,  # False for manual login or local, True for production
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu'
                ] if is_production else []
            )

            self.context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )

            # Load cookies if provided
            if self.cookies:
                print(f"Loading {len(self.cookies)} cookies into browser context...")
                await self.context.add_cookies(self.cookies)

            page = await self.context.new_page()

            try:
                # Check if cookies need refreshing
                needs_refresh = False
                if self.cookies:
                    print("\n🔍 Checking cookie expiration status...")
                    needs_refresh = self.check_cookies_expired()

                    if needs_refresh:
                        print("⚠️  Session cookies are expired or expiring soon")

                        # Check if we have credentials for auto-refresh
                        if self.email and self.password:
                            print("✅ Credentials available - will attempt automatic session refresh")
                            await self.refresh_session_cookies(page)
                        else:
                            print("❌ No credentials provided for automatic refresh")
                            raise Exception("Cookies expired and no credentials available for auto-refresh. Please run capture_cookies.py or provide HIYA_EMAIL and HIYA_PASSWORD")
                    else:
                        print("✅ Session cookies are still valid")

                # Login (or skip if using cookies)
                if self.cookies and not needs_refresh:
                    # Skip login, go directly to phones page
                    print("Navigating directly to phones page with cookies...")
                    await page.goto(self.phones_url, wait_until="domcontentloaded", timeout=60000)

                    # Verify we're logged in by checking URL
                    await asyncio.sleep(3)
                    current_url = page.url

                    if "login" in current_url or "auth" in current_url:
                        print("⚠️  Redirected to login page - cookies may be invalid")

                        # Try automatic refresh if credentials available
                        if self.email and self.password:
                            print("🔄 Attempting automatic session refresh...")
                            await self.refresh_session_cookies(page)
                        else:
                            raise Exception("Cookies expired or invalid - please capture new cookies")

                    if "business.hiya.com" not in current_url:
                        raise Exception("Failed to access Hiya business portal - cookies may be expired")

                    print("✓ Successfully authenticated with cookies!")
                elif not needs_refresh:
                    # Traditional login flow (no cookies provided)
                    await self.login(page)

                    # Navigate to phones page (only if not using cookies)
                    print(f"\nNavigating to phones page...")
                    await page.goto(self.phones_url, wait_until="domcontentloaded", timeout=60000)
                
                # Wait for table to appear
                print("Waiting for table to load...")
                await page.wait_for_selector('tbody.MuiTableBody-root', timeout=30000)
                await asyncio.sleep(3)
                
                # FIXED: Only save screenshots locally, not in production
                if not is_production:
                    await page.screenshot(path="hiya_page_debug.png")
                    print("✓ Screenshot saved as hiya_page_debug.png")
                
                # Extract all data with pagination
                print("\nStarting data extraction...")
                self.data = await self.handle_pagination(page)
                
                print(f"\n{'='*50}")
                print(f"✓ Scraping complete!")
                print(f"Total records extracted: {len(self.data)}")
                print(f"{'='*50}\n")
                
            except Exception as e:
                print(f"\n❌ Error during scraping: {e}")
                # FIXED: Only save error screenshots locally
                if not is_production:
                    await page.screenshot(path="hiya_error.png")
                    print("Error screenshot saved as hiya_error.png")
                raise
            
            finally:
                await browser.close()
        
        return self.data
    
    def save_to_csv(self, filename=None):
        """Save scraped data to CSV"""
        if not self.data:
            print("No data to save!")
            return
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"hiya_phones_{timestamp}.csv"
        
        # Get all unique keys from all records
        fieldnames = set()
        for record in self.data:
            fieldnames.update(record.keys())
        fieldnames = sorted(list(fieldnames))
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.data)
        
        print(f"✓ Data saved to {filename}")
        return filename


# REMOVED: Hardcoded credentials from main function
async def main():
    """Main function for local testing"""
    # Get credentials from environment variables
    EMAIL = os.environ.get('HIYA_EMAIL')
    PASSWORD = os.environ.get('HIYA_PASSWORD')
    
    if not EMAIL or not PASSWORD:
        print("❌ Error: HIYA_EMAIL and HIYA_PASSWORD environment variables required")
        print("Usage: HIYA_EMAIL=your@email.com HIYA_PASSWORD=yourpass python scraper.py")
        return
    
    # Create scraper
    scraper = HiyaScraper(EMAIL, PASSWORD)
    
    # Run scraper
    try:
        data = await scraper.scrape()
        
        # Save to CSV
        scraper.save_to_csv()
        
        # Print sample
        if data:
            print("\nSample of extracted data:")
            print(json.dumps(data[0], indent=2))
            
    except Exception as e:
        print(f"\n❌ Scraping failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())