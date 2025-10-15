"""
Hiya Business Phone Numbers Scraper
Extracts phone registration data and exports to CSV
Fixed version with button-click pagination
"""

import asyncio
import csv
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import json

class HiyaScraper:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.base_url = "https://business.hiya.com"
        self.login_url = "https://auth-console.hiya.com/u/login?state=hKFo2SAtSWtMVzNXN1haaS1hbG5NR0lMSnNYbmY5Z1JqUUZ4SKFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIE1JekpYbWNvQUFoZDVlSm50elhabnhVZTl4b0tmU1Zso2NpZNkgUHpRQlgzd0ZUMEdiNnVuMVI0SUtQcjlaSWF3TXRkNzU"
        self.phones_url = f"{self.base_url}/registration/cross-carrier-registration/phones"
        self.data = []
        self.total_pages = 20

    
    async def login(self, page):
        """Handle login to Hiya"""
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
        try:
            await page.wait_for_url("**/registration/**", timeout=10000)
            print("✓ Login successful!")
        except PlaywrightTimeout:
            # Sometimes redirects take different paths
            await asyncio.sleep(5)
            current_url = page.url
            if "hiya.com" in current_url and "login" not in current_url:
                print("✓ Login successful!")
            else:
                raise Exception("Login failed - still on login page")
    
    async def extract_table_data(self, page):
        """Extract data from the current page using MUI table structure"""
        print("Extracting table data...")
        
        # Wait for table to be visible
        await page.wait_for_selector('tbody.MuiTableBody-root', timeout=15000)
        
        # Wait for actual data to load
        print("Waiting for data to populate...")
        await asyncio.sleep(3)
        
        # Wait for actual phone number links to appear
        try:
            await page.wait_for_selector('tbody.MuiTableBody-root a[href*="/phones/"]', timeout=10000)
        except PlaywrightTimeout:
            print("⚠ Warning: Phone links not found, might be loading...")
        
        # Additional wait to ensure all data is loaded
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
        total_pages = 20
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
            browser = await p.chromium.launch(
                headless=False,  # Set to True for production
                slow_mo=50
            )
            
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            
            page = await context.new_page()
            
            try:
                # Login
                await self.login(page)
                
                # Navigate to phones page
                print(f"\nNavigating to phones page...")
                await page.goto(self.phones_url, wait_until="domcontentloaded", timeout=60000)
                
                # Wait for table to appear
                print("Waiting for table to load...")
                await page.wait_for_selector('tbody.MuiTableBody-root', timeout=30000)
                await asyncio.sleep(3)
                
                # Take screenshot for debugging
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


async def main():
    """Main function"""
    # Configuration
    EMAIL = "julia.smith@bridgelegal.com"
    PASSWORD = "@sh2019Irish2023!"
    
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
