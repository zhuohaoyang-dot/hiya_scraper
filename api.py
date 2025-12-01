from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import asyncio
from scraper import HiyaScraper
import tempfile
import os
from datetime import datetime
import json
import sys
import base64

app = Flask(__name__)
CORS(app)  # Enable CORS for GitHub Pages

def load_cookies_from_env():
    """Load cookies from environment variable"""
    cookies_b64 = os.environ.get('HIYA_COOKIES')
    if not cookies_b64:
        return None

    try:
        cookies_json = base64.b64decode(cookies_b64).decode()
        cookies = json.loads(cookies_json)
        return cookies
    except Exception as e:
        print(f"Error loading cookies from environment: {e}")
        return None

def check_cookie_health(cookies):
    """Check the health status of cookies"""
    if not cookies:
        return {
            'status': 'missing',
            'message': 'No cookies configured',
            'session_valid': False,
            'device_trust_valid': False
        }

    import time
    current_time = time.time()

    # Check session cookies
    session_cookies = ['auth0', 'auth0_compat', 'appSession.0', 'appSession.1']
    session_valid = False
    session_expires_in = 0

    for cookie in cookies:
        if cookie.get('name') in session_cookies:
            expires = cookie.get('expires', -1)
            if expires == -1 or expires > current_time:
                session_valid = True
                if expires > 0:
                    session_expires_in = max(session_expires_in, expires - current_time)

    # Check device trust cookies (auth0-mf for 2FA skip)
    device_cookies = ['auth0-mf', 'auth0-mf_compat', 'did', 'did_compat']
    device_trust_valid = False
    device_expires_in = 0

    for cookie in cookies:
        if cookie.get('name') in device_cookies:
            expires = cookie.get('expires', -1)
            if expires == -1 or expires > current_time:
                device_trust_valid = True
                if expires > 0:
                    device_expires_in = max(device_expires_in, expires - current_time)

    # Determine status
    if session_valid and device_trust_valid:
        status = 'healthy'
        message = 'All cookies valid'
    elif session_valid and not device_trust_valid:
        status = 'warning'
        message = 'Session valid but device trust expired (2FA may be required)'
    elif not session_valid and device_trust_valid:
        status = 'auto_refresh'
        message = 'Session expired but can auto-refresh (device trusted)'
    else:
        status = 'expired'
        message = 'All cookies expired'

    return {
        'status': status,
        'message': message,
        'session_valid': session_valid,
        'session_expires_in_hours': round(session_expires_in / 3600, 1) if session_expires_in > 0 else 0,
        'device_trust_valid': device_trust_valid,
        'device_expires_in_days': round(device_expires_in / 86400, 1) if device_expires_in > 0 else 0
    }

# Add a root route for health check
@app.route('/')
def home():
    cookies = load_cookies_from_env()
    cookie_health = check_cookie_health(cookies)

    # Check if credentials are configured for auto-refresh
    has_credentials = bool(os.environ.get('HIYA_EMAIL') and os.environ.get('HIYA_PASSWORD'))

    response = {
        'status': 'running',
        'message': 'Hiya Scraper API is running',
        'cookie_health': cookie_health,
        'auto_refresh_enabled': has_credentials,
        'endpoints': {
            'scrape': '/scrape (POST)',
            'scrape_stream': '/scrape-stream (POST)'
        }
    }

    # Add helpful messages based on status
    if cookie_health['status'] == 'missing':
        response['action_required'] = 'Run capture_cookies.py and set HIYA_COOKIES environment variable'
    elif cookie_health['status'] == 'expired':
        response['action_required'] = 'Run capture_cookies.py to refresh all cookies'
    elif cookie_health['status'] == 'auto_refresh':
        if has_credentials:
            response['info'] = 'Session will auto-refresh on next scrape (credentials configured)'
        else:
            response['action_required'] = 'Set HIYA_EMAIL and HIYA_PASSWORD for auto-refresh, or run capture_cookies.py'
    elif cookie_health['status'] == 'warning':
        response['warning'] = f"Device trust expires in {cookie_health['device_expires_in_days']} days. Run capture_cookies.py before expiration."

    return jsonify(response)

@app.route('/scrape', methods=['POST'])
def scrape_hiya():
    """Scrape endpoint - uses cookie-based authentication with auto-refresh"""
    try:
        # Load cookies from environment
        cookies = load_cookies_from_env()

        if not cookies:
            return jsonify({
                'error': 'No cookies configured. Please run capture_cookies.py and add HIYA_COOKIES to Railway environment variables.'
            }), 503

        # Load credentials for auto-refresh
        email = os.environ.get('HIYA_EMAIL')
        password = os.environ.get('HIYA_PASSWORD')

        data = request.json
        pages = data.get('pages', 20)

        # Create scraper instance with cookies AND credentials for auto-refresh
        scraper = HiyaScraper(email=email, password=password, cookies=cookies)
        scraper.total_pages = pages
        
        # Run async scraper
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(scraper.scrape())
        loop.close()
        
        # Save to temporary CSV
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8') as tmp:
            filename = tmp.name
        
        scraper.save_to_csv(filename)
        
        # Send file and clean up
        response = send_file(
            filename,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'hiya_phones_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
        # Clean up temp file after sending
        @response.call_on_close
        def cleanup():
            try:
                os.unlink(filename)
            except:
                pass
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/auth-and-capture', methods=['POST'])
def auth_and_capture():
    """Authenticate user and capture cookies with device trust"""
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        twofa_code = data.get('twofa_code')

        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        # Create scraper with manual login mode
        scraper = HiyaScraper(email=email, password=password, manual_login=False, cookies=None)

        # Run async authentication and cookie capture
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Custom authentication with 2FA support
        cookies = loop.run_until_complete(authenticate_and_capture(scraper, twofa_code))
        loop.close()

        if not cookies:
            return jsonify({'error': 'Authentication failed. Please check your credentials.'}), 401

        # Encode cookies to base64
        cookies_json = json.dumps(cookies, indent=2)
        cookies_base64 = base64.b64encode(cookies_json.encode()).decode()

        return jsonify({
            'status': 'success',
            'cookies': cookies_base64,
            'cookie_count': len(cookies),
            'message': 'Authentication successful! Device remembered for 30 days.'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

async def authenticate_and_capture(scraper, twofa_code=None):
    """Authenticate with Hiya and capture cookies with device trust"""
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )

        page = await context.new_page()

        try:
            print(f"🔐 Authenticating user: {scraper.email}")

            # Navigate to login page
            await page.goto(scraper.login_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            # Wait for login form
            await page.wait_for_selector('input[type="email"], input[type="text"]', timeout=10000)

            # Fill in credentials
            print("📝 Entering credentials...")
            email_input = page.locator('input[type="email"], input[name="username"], input[name="email"]').first
            await email_input.fill(scraper.email)

            password_input = page.locator('input[type="password"], input[name="password"]').first
            await password_input.fill(scraper.password)

            # Click login button
            print("👆 Clicking login button...")
            login_button = page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Continue")').first
            await login_button.click()

            # Wait for navigation
            await asyncio.sleep(5)

            # Check if 2FA is required
            current_url = page.url
            print(f"📍 Current URL: {current_url}")

            if "mfa" in current_url.lower() or "verify" in current_url.lower():
                print("📱 2FA required")

                if not twofa_code:
                    raise Exception("2FA code required but not provided")

                # Enter 2FA code
                print(f"🔢 Entering 2FA code...")
                twofa_input = page.locator('input[type="text"], input[name="code"], input[placeholder*="code"]').first
                await twofa_input.fill(twofa_code)

                # Look for "Remember this device" checkbox and check it
                try:
                    remember_checkbox = page.locator('input[type="checkbox"]').first
                    if await remember_checkbox.count() > 0:
                        await remember_checkbox.check()
                        print("✅ Checked 'Remember this device'")
                except Exception as e:
                    print(f"⚠️ Could not find remember checkbox: {e}")

                # Click verify/continue button
                verify_button = page.locator('button[type="submit"], button:has-text("Verify"), button:has-text("Continue")').first
                await verify_button.click()

                await asyncio.sleep(5)

            # Check for additional "Remember device" buttons
            try:
                remember_buttons = [
                    'button:has-text("Remember")',
                    'button:has-text("Trust")',
                    'button:has-text("Yes")',
                ]

                for selector in remember_buttons:
                    button = page.locator(selector).first
                    if await button.count() > 0:
                        is_visible = await button.is_visible()
                        if is_visible:
                            print(f"Found and clicking: {selector}")
                            await button.click()
                            await asyncio.sleep(3)
                            break
            except Exception as e:
                print(f"No additional remember buttons found: {e}")

            # Wait for successful login
            await page.wait_for_url("**/business.hiya.com/**", timeout=20000)
            print("✅ Login successful!")

            # Capture all cookies
            print("🍪 Capturing cookies...")
            all_cookies = await context.cookies()

            # Filter for Hiya-related cookies
            important_domains = ['hiya.com', 'auth-console.hiya.com', 'business.hiya.com']
            filtered_cookies = [
                cookie for cookie in all_cookies
                if any(domain in cookie.get('domain', '') for domain in important_domains)
            ]

            print(f"✅ Captured {len(filtered_cookies)} cookies")

            # Print cookie expiration info
            for cookie in filtered_cookies:
                if cookie.get('name') in ['auth0-mf', 'did', 'auth0']:
                    expires = cookie.get('expires', -1)
                    if expires > 0:
                        from datetime import datetime
                        expire_date = datetime.fromtimestamp(expires)
                        print(f"   {cookie.get('name')}: expires {expire_date}")

            await browser.close()
            return filtered_cookies

        except PlaywrightTimeout as e:
            print(f"❌ Timeout during authentication: {e}")
            await browser.close()
            raise Exception("Authentication timeout. Please try again.")
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            await browser.close()
            raise

@app.route('/scrape-with-cookies', methods=['POST'])
def scrape_with_user_cookies():
    """Scrape endpoint that accepts cookies from the request body (user-specific)"""
    try:
        data = request.json
        pages = data.get('pages', 20)
        cookies_b64 = data.get('cookies')

        if not cookies_b64:
            return jsonify({
                'error': 'No cookies provided. Please authenticate first.'
            }), 401

        # Decode user's cookies
        try:
            cookies_json = base64.b64decode(cookies_b64).decode()
            cookies = json.loads(cookies_json)
        except Exception as e:
            return jsonify({
                'error': 'Invalid cookies format. Please re-authenticate.'
            }), 400

        # Create scraper instance with user's cookies
        scraper = HiyaScraper(cookies=cookies)
        scraper.total_pages = pages

        # Run async scraper
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(scraper.scrape())
        loop.close()

        # Save to temporary CSV
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8') as tmp:
            filename = tmp.name

        scraper.save_to_csv(filename)

        # Send file and clean up
        response = send_file(
            filename,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'hiya_phones_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )

        # Clean up temp file after sending
        @response.call_on_close
        def cleanup():
            try:
                os.unlink(filename)
            except:
                pass

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/scrape-stream', methods=['POST'])
def scrape_hiya_stream():
    """Streaming endpoint with real-time progress updates via Server-Sent Events"""
    try:
        # Load cookies from environment
        cookies = load_cookies_from_env()

        if not cookies:
            return jsonify({
                'error': 'No cookies configured. Please run capture_cookies.py and add HIYA_COOKIES to Railway environment variables.'
            }), 503

        # Load credentials for auto-refresh
        email = os.environ.get('HIYA_EMAIL')
        password = os.environ.get('HIYA_PASSWORD')

        data = request.json
        pages = data.get('pages', 20)

        def generate():
            """Generator function for SSE stream"""
            try:
                # Create scraper with cookies AND credentials for auto-refresh
                scraper = HiyaScraper(email=email, password=password, cookies=cookies)
                scraper.total_pages = pages
                
                # Override print to capture logs
                class LogCapture:
                    def write(self, message):
                        if message.strip():
                            # Send log as SSE event
                            yield f"event: log\ndata: {json.dumps({'message': message.strip()})}\n\n"
                    
                    def flush(self):
                        pass
                
                # Capture stdout
                old_stdout = sys.stdout
                
                # Send starting event
                yield f"event: status\ndata: {json.dumps({'status': 'starting', 'message': 'Initializing scraper...'})}\n\n"
                
                # Run scraper (logs will be captured)
                sys.stdout = LogCapture()
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(scraper.scrape())
                loop.close()
                
                # Restore stdout
                sys.stdout = old_stdout
                
                # Save to temporary CSV
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', newline='', encoding='utf-8') as tmp:
                    filename = tmp.name
                
                scraper.save_to_csv(filename)
                
                # Read CSV content
                with open(filename, 'r', encoding='utf-8') as f:
                    csv_content = f.read()
                
                # Clean up temp file
                try:
                    os.unlink(filename)
                except:
                    pass
                
                # Send completion event with CSV data
                yield f"event: complete\ndata: {json.dumps({'status': 'complete', 'records': len(result), 'csv': csv_content})}\n\n"
                
            except Exception as e:
                sys.stdout = old_stdout
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)