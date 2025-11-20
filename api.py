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

# Add a root route for health check
@app.route('/')
def home():
    cookies = load_cookies_from_env()
    cookies_status = "✓ Configured" if cookies else "✗ Not configured"

    return jsonify({
        'status': 'running',
        'message': 'Hiya Scraper API is running',
        'cookies_status': cookies_status,
        'endpoints': {
            'scrape': '/scrape (POST)',
            'scrape_stream': '/scrape-stream (POST)'
        }
    })

@app.route('/scrape', methods=['POST'])
def scrape_hiya():
    """Scrape endpoint - uses cookie-based authentication"""
    try:
        # Load cookies from environment
        cookies = load_cookies_from_env()

        if not cookies:
            return jsonify({
                'error': 'No cookies configured. Please run capture_cookies.py and add HIYA_COOKIES to Railway environment variables.'
            }), 503

        data = request.json
        pages = data.get('pages', 20)

        # Create scraper instance with cookies
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

        data = request.json
        pages = data.get('pages', 20)

        def generate():
            """Generator function for SSE stream"""
            try:
                # Create scraper with cookies
                scraper = HiyaScraper(cookies=cookies)
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