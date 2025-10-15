from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import asyncio
from scraper import HiyaScraper
import tempfile
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for GitHub Pages

# Add a root route for health check
@app.route('/')
def home():
    return jsonify({
        'status': 'running',
        'message': 'Hiya Scraper API is running',
        'endpoint': '/scrape'
    })

@app.route('/scrape', methods=['POST'])
def scrape_hiya():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        pages = data.get('pages', 20)
        
        # Create scraper instance
        scraper = HiyaScraper(email, password)
        scraper.total_pages = pages  # Override page limit
        
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

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
